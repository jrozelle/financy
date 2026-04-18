"""
Providers de cours de marché.

Architecture :
- PriceProvider : interface abstraite (resolve_ticker, fetch_last_price, fetch_history).
- YahooProvider : implémentation via yfinance + Yahoo Finance search API.
- MockProvider  : cours fictifs stables (mode démo, tests unitaires).
- get_provider() : renvoie le provider approprié selon is_demo_mode().

Robustesse :
- Batch de 10 tickers maximum, délai entre batches pour eviter 429 Yahoo.
- Try/except systématique : un échec isole ne doit jamais planter un refresh global.
- Timeout HTTP strict (5s) sur resolve_ticker.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import logging
import time

logger = logging.getLogger('financy.prices')

BATCH_SIZE = 10
BATCH_DELAY = 1.0  # secondes entre batches
HTTP_TIMEOUT = 5.0


# ─── Interface ───────────────────────────────────────────────────────────────

class PriceProvider(ABC):
    """Interface abstraite. Tous les providers doivent l'implementer."""

    name = 'abstract'

    @abstractmethod
    def resolve_ticker(self, isin):
        """Retourne le ticker correspondant a l'ISIN, ou None si introuvable."""
        ...

    @abstractmethod
    def fetch_last_price(self, ticker):
        """Retourne (price, date_iso) ou None si indisponible."""
        ...

    @abstractmethod
    def fetch_history(self, ticker, period='30d'):
        """Retourne une liste de (date_iso, price) pour la periode demandee.
        period : '1d', '7d', '30d', '90d', '1y', '5y'."""
        ...


# ─── Yahoo Finance (prod) ────────────────────────────────────────────────────

class YahooProvider(PriceProvider):
    name = 'yahoo'

    _session = None

    @classmethod
    def _get_session(cls):
        if cls._session is None:
            import requests
            s = requests.Session()
            s.headers.update({
                # Yahoo bloque les User-Agents vides
                'User-Agent': 'Mozilla/5.0 (Financy) PriceRefresh/1.0',
                'Accept': 'application/json',
            })
            cls._session = s
        return cls._session

    def resolve_ticker(self, isin):
        """Interroge l'endpoint Yahoo search pour trouver le ticker."""
        try:
            s = self._get_session()
            url = f'https://query1.finance.yahoo.com/v1/finance/search?q={isin}&quotesCount=5&newsCount=0'
            resp = s.get(url, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            quotes = data.get('quotes', [])
            # Priorite : match exact ISIN, puis premier resultat coherent
            for q in quotes:
                sym = q.get('symbol')
                if sym:
                    return sym
        except Exception as e:
            logger.warning('resolve_ticker(%s) failed: %s', isin, e)
        return None

    def fetch_last_price(self, ticker):
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            hist = t.history(period='5d', auto_adjust=False)
            if hist.empty:
                return None
            last = hist.iloc[-1]
            price = float(last['Close'])
            date = hist.index[-1].strftime('%Y-%m-%d')
            return (price, date)
        except Exception as e:
            logger.warning('fetch_last_price(%s) failed: %s', ticker, e)
            return None

    def fetch_history(self, ticker, period='30d'):
        yf_period = {
            '1d': '2d', '7d': '7d', '30d': '1mo',
            '90d': '3mo', '1y': '1y', '5y': '5y',
        }.get(period, '1mo')
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            hist = t.history(period=yf_period, auto_adjust=False)
            if hist.empty:
                return []
            return [
                (idx.strftime('%Y-%m-%d'), float(row['Close']))
                for idx, row in hist.iterrows()
            ]
        except Exception as e:
            logger.warning('fetch_history(%s, %s) failed: %s', ticker, period, e)
            return []


# ─── Mock (demo + tests) ─────────────────────────────────────────────────────

class MockProvider(PriceProvider):
    """Cours deterministes derives de l'ISIN. Aucun appel reseau."""
    name = 'mock'

    def resolve_ticker(self, isin):
        return f'MOCK_{isin[:6].replace("_", "")}' if isin else None

    def _seed_price(self, ticker):
        base = sum(ord(c) for c in (ticker or 'X'))
        return 50 + (base % 200) + (base % 7) * 0.5

    def fetch_last_price(self, ticker):
        return (round(self._seed_price(ticker), 2), datetime.now().strftime('%Y-%m-%d'))

    def fetch_history(self, ticker, period='30d'):
        days = {'1d': 1, '7d': 7, '30d': 30, '90d': 90, '1y': 365, '5y': 1825}.get(period, 30)
        base = self._seed_price(ticker)
        out = []
        today = datetime.now().date()
        # Walk deterministe : petite variation sinusoidale
        import math
        for i in range(days + 1):
            d = today - timedelta(days=days - i)
            variation = math.sin(i / 7) * 0.05 * base  # +-5%
            out.append((d.strftime('%Y-%m-%d'), round(base + variation, 2)))
        return out


# ─── Selection automatique ───────────────────────────────────────────────────

_mock = MockProvider()


def get_provider(force=None):
    """Renvoie le provider a utiliser.

    Ordre de decision :
    1. force='mock' | 'yahoo' : override explicite (tests).
    2. env var PRICE_PROVIDER=mock : override global (tests, dev).
    3. mode demo (is_demo_mode) : MockProvider.
    4. defaut : YahooProvider.
    """
    import os
    if force == 'mock':
        return _mock
    if force == 'yahoo':
        return YahooProvider()
    if os.environ.get('PRICE_PROVIDER', '').lower() == 'mock':
        return _mock
    try:
        from models import is_demo_mode
        if is_demo_mode():
            return _mock
    except Exception:
        pass
    return YahooProvider()


# ─── Orchestration : refresh ─────────────────────────────────────────────────

def refresh_securities(conn, provider=None, only_stale=False, stale_hours=20):
    """Rafraichit last_price pour toutes les securities priceables.

    - conn : connexion SQLite ouverte.
    - provider : instance PriceProvider (par defaut get_provider()).
    - only_stale : si True, ignore les titres deja rafraichis depuis <stale_hours>.
    - stale_hours : seuil en heures pour considerer un cours comme frais.

    Retourne un dict : {refreshed, skipped, errors, resolved_tickers}.
    """
    if provider is None:
        provider = get_provider()

    stats = {'refreshed': 0, 'skipped': 0, 'errors': 0, 'resolved_tickers': 0}
    rows = conn.execute(
        'SELECT isin, ticker, last_price_date FROM securities WHERE is_priceable=1'
    ).fetchall()

    if only_stale:
        threshold = datetime.now() - timedelta(hours=stale_hours)
        rows = [
            r for r in rows
            if not r['last_price_date']
            or _parse_date_safe(r['last_price_date']) < threshold
        ]

    today = datetime.now().strftime('%Y-%m-%d')
    for idx, row in enumerate(rows):
        isin = row['isin']
        ticker = row['ticker']

        # Resolution lazy du ticker si absent
        if not ticker:
            ticker = provider.resolve_ticker(isin)
            if ticker:
                conn.execute(
                    'UPDATE securities SET ticker=?, updated_at=CURRENT_TIMESTAMP WHERE isin=?',
                    (ticker, isin)
                )
                stats['resolved_tickers'] += 1
            else:
                stats['skipped'] += 1
                continue

        result = provider.fetch_last_price(ticker)
        if not result:
            stats['errors'] += 1
            continue
        price, price_date = result

        try:
            conn.execute(
                '''UPDATE securities SET last_price=?, last_price_date=?,
                   data_source=?, updated_at=CURRENT_TIMESTAMP WHERE isin=?''',
                (price, price_date, provider.name, isin)
            )
            conn.execute(
                'INSERT OR REPLACE INTO price_history (isin, date, price) VALUES (?,?,?)',
                (isin, price_date, price)
            )
            stats['refreshed'] += 1
        except Exception as e:
            logger.warning('DB update failed for %s: %s', isin, e)
            stats['errors'] += 1

        # Batching : pause entre batches pour eviter rate limits
        if (idx + 1) % BATCH_SIZE == 0 and idx + 1 < len(rows):
            time.sleep(BATCH_DELAY)

    logger.info('refresh_securities done: %s', stats)
    return stats


def refresh_history(conn, isin, period='30d', provider=None):
    """Rafraichit price_history pour un ISIN sur la periode demandee.

    Insere/remplace les lignes dans price_history. Retourne la liste
    (date, price) inseree.
    """
    if provider is None:
        provider = get_provider()

    row = conn.execute(
        'SELECT isin, ticker, is_priceable FROM securities WHERE isin=?', (isin,)
    ).fetchone()
    if not row or not row['is_priceable']:
        return []
    ticker = row['ticker']
    if not ticker:
        ticker = provider.resolve_ticker(isin)
        if ticker:
            conn.execute(
                'UPDATE securities SET ticker=?, updated_at=CURRENT_TIMESTAMP WHERE isin=?',
                (ticker, isin)
            )
        else:
            return []

    points = provider.fetch_history(ticker, period)
    for d, p in points:
        conn.execute(
            'INSERT OR REPLACE INTO price_history (isin, date, price) VALUES (?,?,?)',
            (isin, d, p)
        )
    # Met aussi a jour last_price si on a recupere des points recents
    if points:
        last_date, last_price = points[-1]
        conn.execute(
            '''UPDATE securities SET last_price=?, last_price_date=?,
               data_source=?, updated_at=CURRENT_TIMESTAMP WHERE isin=?''',
            (last_price, last_date, provider.name, isin)
        )
    return points


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_date_safe(s):
    if not s:
        return datetime.min
    try:
        return datetime.strptime(s[:10], '%Y-%m-%d')
    except ValueError:
        return datetime.min


def freshness_status(last_price_date, now=None):
    """Retourne 'fresh' | 'stale' | 'expired' | 'unknown' selon l'age du cours."""
    if not last_price_date:
        return 'unknown'
    now = now or datetime.now()
    age = now - _parse_date_safe(last_price_date)
    if age < timedelta(days=1):
        return 'fresh'
    if age < timedelta(days=7):
        return 'stale'
    return 'expired'
