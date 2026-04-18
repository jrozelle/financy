"""Integration tests for the prices feature (phase 2)."""

import os
import pytest

# Force le provider mock pour tous les tests — aucun appel reseau.
os.environ['PRICE_PROVIDER'] = 'mock'

from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa


def _seed_pea_with_holdings(client):
    r = _make_position(client, category='Actions', envelope='PEA', value=0, debt=0)
    pid = r.get_json()['id']
    client.put(f'/api/positions/{pid}/holdings', json={'holdings': [
        {'isin': 'FR0010315770', 'name': 'CW8', 'quantity': 20,
         'cost_basis': 8000, 'market_value': 9800},
        {'isin': 'IE00B4L5Y983', 'name': 'IWDA', 'quantity': 50,
         'cost_basis': 4500, 'market_value': 5200},
        {'isin': 'FONDS_EUROS_LINXEA', 'quantity': 1,
         'cost_basis': 10000, 'market_value': 10250, 'is_priceable': False},
    ]}, headers=CSRF_HEADERS)
    return pid


# ─── MockProvider (isolation unit) ───────────────────────────────────────────

class TestMockProvider:
    def test_deterministic_ticker_and_price(self):
        from services.prices import MockProvider
        p = MockProvider()
        t1 = p.resolve_ticker('FR0010315770')
        t2 = p.resolve_ticker('FR0010315770')
        assert t1 == t2  # deterministe
        price1 = p.fetch_last_price(t1)
        price2 = p.fetch_last_price(t1)
        assert price1[0] == price2[0]

    def test_history_has_correct_length(self):
        from services.prices import MockProvider
        p = MockProvider()
        hist = p.fetch_history('MOCK_X', '30d')
        assert len(hist) == 31

    def test_different_tickers_give_different_prices(self):
        from services.prices import MockProvider
        p = MockProvider()
        assert p.fetch_last_price('MOCK_A')[0] != p.fetch_last_price('MOCK_Z')[0]


# ─── Freshness ───────────────────────────────────────────────────────────────

class TestFreshness:
    def test_fresh_stale_expired_unknown(self):
        from services.prices import freshness_status
        from datetime import datetime, timedelta
        now = datetime(2026, 4, 18)
        assert freshness_status('2026-04-18', now=now) == 'fresh'
        assert freshness_status('2026-04-14', now=now) == 'stale'   # 4 jours
        assert freshness_status('2026-04-01', now=now) == 'expired'  # 17 jours
        assert freshness_status(None) == 'unknown'


# ─── /api/prices/refresh ─────────────────────────────────────────────────────

class TestRefresh:
    def test_refresh_priceable_only(self, client):
        _seed_pea_with_holdings(client)
        r = client.post('/api/prices/refresh', headers=CSRF_HEADERS)
        data = r.get_json()
        assert r.status_code == 200
        assert data['provider'] == 'mock'
        assert data['refreshed'] == 2       # le fonds euros est ignore
        assert data['resolved_tickers'] == 2
        assert data['errors'] == 0

    def test_refresh_updates_position_value(self, client):
        pid = _seed_pea_with_holdings(client)
        r = client.get('/api/positions?date=2024-06-01')
        before = next(p for p in r.get_json() if p['id'] == pid)['value']
        client.post('/api/prices/refresh', headers=CSRF_HEADERS)
        r = client.get('/api/positions?date=2024-06-01')
        after = next(p for p in r.get_json() if p['id'] == pid)['value']
        # La valeur change car qty * mock_price != market_value saisi
        assert after != before
        assert after > 0

    def test_refresh_stale_filter(self, client):
        _seed_pea_with_holdings(client)
        # Premier refresh : tout est traite
        r1 = client.post('/api/prices/refresh', headers=CSRF_HEADERS).get_json()
        assert r1['refreshed'] == 2
        # Second refresh avec only_stale : tout est deja frais donc 0
        r2 = client.post('/api/prices/refresh?only_stale=1', headers=CSRF_HEADERS).get_json()
        assert r2['refreshed'] == 0


# ─── /api/prices/history/<isin> ──────────────────────────────────────────────

class TestHistory:
    def test_history_backfills_on_first_call(self, client):
        _seed_pea_with_holdings(client)
        r = client.get('/api/prices/history/FR0010315770?period=30d')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data['points']) >= 30
        assert data['freshness'] == 'fresh'
        assert data['is_priceable'] is True

    def test_history_includes_holding_pnl(self, client):
        _seed_pea_with_holdings(client)
        r = client.get('/api/prices/history/FR0010315770?period=30d')
        data = r.get_json()
        h = data['holding']
        assert h is not None
        assert h['quantity'] == 20
        assert h['cost_basis'] == 8000
        assert h['pnl'] is not None

    def test_history_fonds_euros_no_chart_but_pnl(self, client):
        _seed_pea_with_holdings(client)
        r = client.get('/api/prices/history/FONDS_EUROS_LINXEA?period=30d')
        data = r.get_json()
        assert data['is_priceable'] is False
        assert data['points'] == []
        # Le P&L latent reste calculable via market_value saisi
        assert data['holding']['current_value'] == 10250
        assert data['holding']['pnl'] == 250

    def test_history_unknown_isin(self, client):
        # ISIN au format valide mais pas en DB
        r = client.get('/api/prices/history/FR0010315770')
        assert r.status_code == 404

    def test_history_invalid_isin(self, client):
        r = client.get('/api/prices/history/NOTANISIN')
        assert r.status_code == 400


# ─── /api/securities/<isin>/resolve-ticker ──────────────────────────────────

class TestResolveTicker:
    def test_resolve_success(self, client):
        _seed_pea_with_holdings(client)
        # Clear le ticker d'abord
        client.patch('/api/securities/FR0010315770', json={'ticker': ''},
                     headers=CSRF_HEADERS)
        r = client.post('/api/securities/FR0010315770/resolve-ticker',
                        headers=CSRF_HEADERS)
        assert r.status_code == 200
        data = r.get_json()
        assert data['ticker'].startswith('MOCK_')
        assert data['provider'] == 'mock'

    def test_resolve_unknown_security(self, client):
        r = client.post('/api/securities/FR0010315770/resolve-ticker',
                        headers=CSRF_HEADERS)
        assert r.status_code == 404
