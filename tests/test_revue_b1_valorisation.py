"""Revue B1 : valorisation des lignes de titres (devise, quote-part, PRU).

Donnees fictives : Paul et Claire, montants ronds, ISIN inventes.
"""
import os
import tempfile

import pytest

import models

_tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_tmp.close()
models.DB_PATH = _tmp.name
models._BASE_DIR = os.path.dirname(_tmp.name)
os.environ['FINANCY_PASSWORD'] = 'testpass'
os.environ['PRICE_PROVIDER'] = 'mock'

from models import init_db, get_db, get_holdings_map  # noqa: E402
from app import app  # noqa: E402
from services.fiscalite import _pru_par_enveloppe  # noqa: E402
from services.holdings_split import (find_or_create_position,  # noqa: E402
                                     split_holdings_by_category)
from services.realized import compute_realized  # noqa: E402
from services.reconcile import apply_ecart, reconcile_snapshot  # noqa: E402
from services.montants import centimes  # noqa: E402

CSRF = {'X-CSRF-Token': 'test'}
USD = 'US00TEST0008'
EUR = 'FR00TEST0008'


@pytest.fixture(autouse=True)
def fresh_db():
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)
    init_db()
    yield
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['authenticated'] = True
            s['csrf_token'] = 'test'
        yield c


def _security(conn, isin, currency='EUR', price=None, price_date=None,
              name='Titre test', asset_class=None):
    conn.execute('INSERT OR REPLACE INTO securities (isin, name, currency, '
                 'asset_class, is_priceable, last_price, last_price_date) '
                 'VALUES (?,?,?,?,1,?,?)',
                 (isin, name, currency, asset_class, price, price_date))


def _position(conn, date='2026-09-01', owner='Paul', envelope='CTO',
              establishment='Banque Test', category='Actions', ownership=1.0,
              **extra):
    cols = ['date', 'owner', 'category', 'envelope', 'establishment',
            'value', 'ownership_pct'] + list(extra)
    vals = [date, owner, category, envelope, establishment, 0, ownership] + list(extra.values())
    return conn.execute(
        f'INSERT INTO positions ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})',
        vals).lastrowid


def _holding(conn, pid, isin, qty, cost=None, mv=None, as_of=None):
    return conn.execute(
        'INSERT INTO holdings (position_id, isin, quantity, cost_basis, '
        'market_value, as_of_date) VALUES (?,?,?,?,?,?)',
        (pid, isin, qty, centimes(cost), centimes(mv), as_of)).lastrowid


def _fx(conn, devise='USD', rate=1.25, date='2026-09-01'):
    conn.execute('INSERT INTO fx_rates (pair, date, rate) VALUES (?,?,?)',
                 (f'EUR{devise}', date, rate))


# ─── get_holdings_map ────────────────────────────────────────────────────────

def test_holdings_map_liste_vide_ne_rend_rien():
    with get_db() as conn:
        _security(conn, EUR)
        _holding(conn, _position(conn), EUR, 10, mv=1000)
        assert get_holdings_map(conn, []) == {}
        assert len(get_holdings_map(conn)) == 1        # None : toute la base


# ─── /api/holdings/consolidated ──────────────────────────────────────────────

class TestConsolide:
    def test_cours_en_dollars_converti(self, client):
        with get_db() as conn:
            _security(conn, USD, 'USD', price=125.0, price_date='2026-09-01')
            _fx(conn, 'USD', 1.25)
            _holding(conn, _position(conn), USD, 10, cost=800)
            conn.commit()
        d = client.get('/api/holdings/consolidated').get_json()
        assert d['totals']['market_value'] == 1000.0       # 10 x 125 / 1,25
        assert d['lines'][0]['pnl'] == 200.0
        assert d['price_warnings'] == []

    def test_dollars_sans_taux_ne_valorisent_rien_et_le_disent(self, client):
        with get_db() as conn:
            _security(conn, USD, 'USD', price=125.0, price_date='2026-09-01')
            _holding(conn, _position(conn), USD, 10, cost=800)
            conn.commit()
        d = client.get('/api/holdings/consolidated').get_json()
        assert d['totals']['market_value'] == 0
        assert d['lines'][0]['pnl'] is None               # ni gain ni perte connus
        assert d['price_warnings'][0]['kind'] == 'devise'
        assert d['price_warnings'][0]['owner'] == 'Paul'

    def test_quote_part_detenue(self, client):
        with get_db() as conn:
            _security(conn, EUR)
            _holding(conn, _position(conn, ownership=0.5), EUR, 10,
                     cost=1000, mv=2000, as_of='2026-09-01')
            conn.commit()
        d = client.get('/api/holdings/consolidated').get_json()
        line = d['lines'][0]
        assert line['quantity'] == 5
        assert line['market_value'] == 1000
        assert line['cost_basis'] == 500
        assert d['breakdowns']['envelope'][0]['market_value'] == 1000

    def test_arrete_passe_garde_sa_valeur(self, client):
        with get_db() as conn:
            _security(conn, EUR, price=20.0, price_date='2026-09-01')
            _holding(conn, _position(conn, date='2026-06-01'), EUR, 100,
                     mv=1000, as_of='2026-06-01')
            _holding(conn, _position(conn, date='2026-09-01'), EUR, 100,
                     mv=1000, as_of='2026-06-01')
            conn.commit()
        passe = client.get('/api/holdings/consolidated?date=2026-06-01').get_json()
        courant = client.get('/api/holdings/consolidated').get_json()
        assert passe['totals']['market_value'] == 1000     # cours fige
        assert courant['totals']['market_value'] == 2000   # cours du jour

    def test_date_invalide_refusee(self, client):
        assert client.get('/api/holdings/consolidated?date=hier').status_code == 400


# ─── Import PDF : enrichissement des cours ───────────────────────────────────

class _FauxProvider:
    name = 'yahoo'

    def __init__(self, devise):
        self.devise = devise

    def resolve_ticker(self, isin, name=None):
        return 'TST', 'EQUITY'

    def fetch_last_price(self, ticker):
        return 125.0, '2026-09-01'

    def fetch_currency(self, ticker):
        return self.devise


def _resultat():
    from services.parsers.common import DetectedLine, ParseResult
    return ParseResult(format='test', source_label='test',
                       lines=[DetectedLine(isin=USD, quantity=10)])


class TestEnrichissement:
    def test_cours_converti_en_euros(self, monkeypatch):
        import services.prices
        from routes.pdf_import import _enrich_with_prices
        monkeypatch.setattr(services.prices, 'get_provider', lambda: _FauxProvider('USD'))
        with get_db() as conn:
            _fx(conn, 'USD', 1.25)
            conn.commit()
        r = _resultat()
        _enrich_with_prices(r)
        assert r.lines[0].market_value == 1000.0
        assert r.lines[0].unit_price == 100.0
        assert any('converti' in w for w in r.warnings)

    def test_sans_taux_pas_de_valorisation(self, monkeypatch):
        import services.prices
        from routes.pdf_import import _enrich_with_prices
        monkeypatch.setattr(services.prices, 'get_provider', lambda: _FauxProvider('USD'))
        r = _resultat()
        _enrich_with_prices(r)
        assert r.lines[0].market_value is None
        assert r.total_market_value == 0
        assert any('taux de change inconnu' in w for w in r.warnings)


# ─── Import PDF : commit ─────────────────────────────────────────────────────

def test_commit_garde_le_prix_de_revient_connu(client):
    with get_db() as conn:
        _security(conn, EUR, name='ETF Monde', asset_class='etf')
        pid = _position(conn)
        _holding(conn, pid, EUR, 10, cost=800, mv=1000, as_of='2026-08-01')
        conn.commit()
    r = client.post(f'/api/envelope/{pid}/import-pdf?step=commit', headers=CSRF,
                    json={'holdings': [{'isin': EUR, 'name': 'ETF Monde',
                                        'asset_class': 'etf', 'quantity': 10,
                                        'market_value': 1100}]})
    assert r.status_code == 200
    with get_db() as conn:
        row = conn.execute('SELECT cost_basis, market_value FROM holdings '
                           'WHERE position_id=?', (pid,)).fetchone()
    assert row['cost_basis'] == 80000                # centimes
    assert row['market_value'] == 110000


# ─── Auto-split : position compagnon ─────────────────────────────────────────

def test_compagnon_herite_de_la_position_de_base():
    with get_db() as conn:
        pid = _position(conn, envelope=None, ownership=0.5, debt_pct=0.5,
                        label='Contrat commun', liquidity_override='J+3')
        base = dict(conn.execute('SELECT * FROM positions WHERE id=?', (pid,)).fetchone())
        cid = find_or_create_position(conn, base, 'Fond Euro')
        c = conn.execute('SELECT * FROM positions WHERE id=?', (cid,)).fetchone()
        assert c['ownership_pct'] == 0.5
        assert c['debt_pct'] == 0.5
        assert c['label'] == 'Contrat commun'
        assert c['liquidity_override'] == 'J+3'
        # Enveloppe NULL : la compagnon est retrouvee, pas dupliquee
        assert find_or_create_position(conn, base, 'Fond Euro') == cid


def test_split_ne_duplique_pas_sur_enveloppe_nulle():
    items = [{'isin': EUR, 'name': 'ETF Monde', 'asset_class': 'etf',
              'quantity': 10, 'market_value': 1000},
             {'isin': 'FONDS_EUROS_TEST', 'name': 'Fonds euros',
              'quantity': 1, 'market_value': 5000}]
    with get_db() as conn:
        _security(conn, EUR)
        _security(conn, 'FONDS_EUROS_TEST')
        pid = _position(conn, envelope=None)
        split_holdings_by_category(conn, pid, items)
        split_holdings_by_category(conn, pid, items)
        n = conn.execute('SELECT COUNT(*) FROM positions').fetchone()[0]
    assert n == 2


# ─── Rapprochement : vente au PRU, cours converti ────────────────────────────

def test_vente_retire_le_cout_au_pru_et_convertit_le_cours():
    with get_db() as conn:
        _security(conn, USD, 'USD', price=25.0, price_date='2026-08-20')
        _fx(conn, 'USD', 1.25)
        pid = _position(conn)
        hid = _holding(conn, pid, USD, 100, cost=1000, mv=2000, as_of='2026-08-01')
        conn.execute('INSERT INTO transactions (date, owner, envelope, establishment, '
                     'isin, side, quantity, net_eur, source_doc) '
                     "VALUES ('2026-08-10','Paul','CTO','Banque Test',?,'VENTE',40,60000,'v1')",  # centimes
                     (USD,))
        conn.commit()
        assert reconcile_snapshot(conn, '2026-09-01')['ecarts'][0]['holding_id'] == hid
        apply_ecart(conn, '2026-09-01', hid)
        row = conn.execute('SELECT * FROM holdings WHERE id=?', (hid,)).fetchone()
    assert row['quantity'] == 60
    assert row['cost_basis'] == 60000        # centimes : 1000 - 40 x PRU 10, pas 1000 - 600
    assert row['market_value'] == 120000     # centimes : 60 x 25 USD / 1,25


# ─── Impot latent : assiette au prix de revient ──────────────────────────────

def test_pru_ignore_les_lignes_sans_cout_et_pondere_la_quote_part():
    with get_db() as conn:
        _security(conn, EUR)
        _security(conn, 'FR00TESU0005')
        _security(conn, USD, 'USD', price=125.0, price_date='2026-09-01')
        _fx(conn, 'USD', 1.25)
        pid = _position(conn, envelope='PEA', ownership=0.5)
        _holding(conn, pid, EUR, 10, cost=1000, mv=1500, as_of='2026-09-01')
        _holding(conn, pid, 'FR00TESU0005', 10, cost=None, mv=2000, as_of='2026-09-01')
        _holding(conn, pid, USD, 10, cost=800)              # 1000 EUR au cours converti
        conn.commit()
        pru = _pru_par_enveloppe(conn, '2026-09-01')
    e = pru['PEA']
    assert e['lignes'] == 3
    assert e['sans_pru'] == 1
    assert e['cout'] == pytest.approx((1000 + 800) * 0.5)
    assert e['valeur'] == pytest.approx((1500 + 1000) * 0.5)


# ─── Plus-values realisees : cle par ligne detenue ───────────────────────────

def _tx(date, owner, side, qty, net, envelope='PEA'):
    return {'date': date, 'owner': owner, 'envelope': envelope,
            'establishment': 'Banque Test', 'isin': EUR, 'side': side,
            'quantity': qty, 'net_eur': net}


def test_realise_separe_les_titulaires():
    state, events = compute_realized([
        _tx('2026-01-05', 'Paul', 'ACHAT', 10, 1000),
        _tx('2026-01-06', 'Claire', 'ACHAT', 10, 2000),
        _tx('2026-03-01', 'Paul', 'VENTE', 10, 1500),
    ])
    paul = state[('Paul', 'PEA', 'Banque Test', EUR)]
    claire = state[('Claire', 'PEA', 'Banque Test', EUR)]
    assert paul['realized'] == 500           # PRU 100, pas 150 melange
    assert claire['quantity'] == 10 and claire['pru'] == 200
    assert events[0]['owner'] == 'Paul'


def test_realise_endpoint_rend_la_ligne_detenue(client):
    with get_db() as conn:
        _security(conn, EUR)
        for i, t in enumerate([_tx('2026-01-05', 'Paul', 'ACHAT', 10, 1000),
                               _tx('2026-01-06', 'Claire', 'ACHAT', 10, 2000),
                               _tx('2026-03-01', 'Paul', 'VENTE', 10, 1500)]):
            conn.execute('INSERT INTO transactions (date, owner, envelope, '
                         'establishment, isin, side, quantity, net_eur, source_doc) '
                         'VALUES (?,?,?,?,?,?,?,?,?)',
                         (t['date'], t['owner'], t['envelope'], t['establishment'],
                          t['isin'], t['side'], t['quantity'], centimes(t['net_eur']), f'd{i}'))
        conn.commit()
    d = client.get('/api/transactions/realized').get_json()
    assert d['total_realized'] == 500
    assert d['lines'][0]['owner'] == 'Paul'


# ─── Recherche Yahoo : parametres encodes ────────────────────────────────────

def test_recherche_yahoo_encode_la_requete(monkeypatch):
    from services.prices import YahooProvider
    vu = {}

    class _Rep:
        def raise_for_status(self):
            pass

        def json(self):
            return {'quotes': [{'symbol': 'TST.PA', 'quoteType': 'ETF'}]}

    class _Session:
        def get(self, url, params=None, timeout=None):
            vu['url'], vu['params'] = url, params
            return _Rep()

    monkeypatch.setattr(YahooProvider, '_session', _Session())
    assert YahooProvider()._yahoo_search('S&P 500 + Monde') == ('TST.PA', 'ETF')
    assert '?' not in vu['url']
    assert vu['params']['q'] == 'S&P 500 + Monde'
