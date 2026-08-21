"""Tests du registre des transactions et des plus-values realisees."""
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

from models import init_db, get_db  # noqa: E402
from app import app  # noqa: E402
from services.realized import compute_realized  # noqa: E402


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


def _tx(date, isin, side, qty, net, **kw):
    return dict(date=date, isin=isin, side=side, quantity=qty, net_eur=net,
                envelope=kw.get('envelope', 'PEA'), source_doc=kw.get('source_doc'))


def _seed_tx(rows):
    with get_db() as conn:
        for r in rows:
            conn.execute('INSERT OR IGNORE INTO securities (isin, name) VALUES (?,?)',
                         (r['isin'], r['isin']))
            conn.execute('''INSERT INTO transactions
                (date, owner, envelope, isin, side, quantity, net_eur, fees, source_doc)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (r['date'], 'Alice', r['envelope'], r['isin'], r['side'],
                 r['quantity'], r['net_eur'], r.get('fees', 0), r.get('source_doc')))
        conn.commit()


class TestSchema:
    def test_table_creee(self):
        with get_db() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'"
            ).fetchone()
        assert row is not None

    def test_sens_contraint(self):
        with get_db() as conn:
            conn.execute("INSERT OR IGNORE INTO securities (isin, name) VALUES ('X','X')")
            with pytest.raises(Exception):
                conn.execute('''INSERT INTO transactions
                    (date, owner, isin, side, quantity, net_eur)
                    VALUES ('2024-01-01','J','X','DON',1,1)''')

    def test_quantite_positive(self):
        with get_db() as conn:
            conn.execute("INSERT OR IGNORE INTO securities (isin, name) VALUES ('X','X')")
            with pytest.raises(Exception):
                conn.execute('''INSERT INTO transactions
                    (date, owner, isin, side, quantity, net_eur)
                    VALUES ('2024-01-01','J','X','ACHAT',-1,1)''')

    def test_piece_unique(self):
        """L'index unique sur source_doc rend l'import idempotent."""
        with get_db() as conn:
            conn.execute("INSERT OR IGNORE INTO securities (isin, name) VALUES ('X','X')")
            conn.execute('''INSERT INTO transactions
                (date, owner, isin, side, quantity, net_eur, source_doc)
                VALUES ('2024-01-01','J','X','ACHAT',1,100,'avis.pdf')''')
            with pytest.raises(Exception):
                conn.execute('''INSERT INTO transactions
                    (date, owner, isin, side, quantity, net_eur, source_doc)
                    VALUES ('2024-01-01','J','X','ACHAT',1,100,'avis.pdf')''')

    def test_plusieurs_saisies_sans_piece(self):
        """Plusieurs NULL restent autorises : saisie manuelle possible."""
        with get_db() as conn:
            conn.execute("INSERT OR IGNORE INTO securities (isin, name) VALUES ('X','X')")
            for _ in range(2):
                conn.execute('''INSERT INTO transactions
                    (date, owner, isin, side, quantity, net_eur)
                    VALUES ('2024-01-01','J','X','ACHAT',1,100)''')
            assert conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 2


class TestRealized:
    def test_pru_moyen_pondere(self):
        # 10 a 100 puis 10 a 120 -> PRU 110
        state, _ = compute_realized([
            _tx('2024-01-01', 'A', 'ACHAT', 10, 1000),
            _tx('2024-02-01', 'A', 'ACHAT', 10, 1200),
        ])
        assert state['A']['pru'] == pytest.approx(110.0)

    def test_vente_ne_change_pas_le_pru(self):
        state, _ = compute_realized([
            _tx('2024-01-01', 'A', 'ACHAT', 10, 1000),
            _tx('2024-02-01', 'A', 'ACHAT', 10, 1200),
            _tx('2024-03-01', 'A', 'VENTE', 5, 700),
        ])
        assert state['A']['pru'] == pytest.approx(110.0)
        assert state['A']['quantity'] == pytest.approx(15.0)
        # 700 encaisses - 5*110 = 150
        assert state['A']['realized'] == pytest.approx(150.0)

    def test_frais_inclus_des_deux_cotes(self):
        # net_eur porte deja les frais : achat 1005 pour 1000 de titres,
        # vente 995 pour 1000 -> perte de 10 alors que le cours n'a pas bouge.
        state, _ = compute_realized([
            _tx('2024-01-01', 'A', 'ACHAT', 10, 1005),
            _tx('2024-02-01', 'A', 'VENTE', 10, 995),
        ])
        assert state['A']['realized'] == pytest.approx(-10.0)

    def test_ligne_soldee_puis_rouverte(self):
        state, events = compute_realized([
            _tx('2024-01-01', 'A', 'ACHAT', 10, 1000),
            _tx('2024-02-01', 'A', 'VENTE', 10, 1100),
            _tx('2024-03-01', 'A', 'ACHAT', 5, 400),
        ])
        assert state['A']['realized'] == pytest.approx(100.0)
        assert state['A']['pru'] == pytest.approx(80.0)
        assert len(events) == 1

    def test_vente_sans_achat_trace_isolee(self):
        """Une cession excedentaire ne doit pas fabriquer de PRU."""
        state, events = compute_realized([
            _tx('2024-01-01', 'A', 'ACHAT', 2, 200),
            _tx('2024-02-01', 'A', 'VENTE', 5, 600),
        ])
        assert state['A']['untracked_qty'] == pytest.approx(3.0)
        assert state['A']['untracked_proceeds'] == pytest.approx(360.0)
        # Seuls les 2 titres traces produisent une plus-value : 240 - 200
        assert state['A']['realized'] == pytest.approx(40.0)

    def test_registre_vide(self):
        state, events = compute_realized([])
        assert state == {} and events == []


class TestEndpoints:
    def test_journal(self, client):
        _seed_tx([_tx('2024-01-01', 'A', 'ACHAT', 10, 1000, source_doc='a.pdf'),
                  _tx('2024-02-01', 'A', 'VENTE', 4, 500, source_doc='b.pdf')])
        d = client.get('/api/transactions').get_json()
        assert d['count'] == 2
        assert d['total_buy'] == 1000 and d['total_sell'] == 500

    def test_filtre_isin(self, client):
        _seed_tx([_tx('2024-01-01', 'A', 'ACHAT', 1, 100, source_doc='a.pdf'),
                  _tx('2024-01-01', 'B', 'ACHAT', 1, 200, source_doc='b.pdf')])
        d = client.get('/api/transactions?isin=B').get_json()
        assert d['count'] == 1 and d['transactions'][0]['isin'] == 'B'

    def test_realized_endpoint(self, client):
        _seed_tx([_tx('2024-01-01', 'A', 'ACHAT', 10, 1000, source_doc='a.pdf'),
                  _tx('2024-02-01', 'A', 'VENTE', 10, 1150, source_doc='b.pdf')])
        d = client.get('/api/transactions/realized').get_json()
        assert d['total_realized'] == pytest.approx(150.0)
        assert len(d['events']) == 1
        assert d['untracked_lines'] == 0

    def test_realized_signale_achat_manquant(self, client):
        _seed_tx([_tx('2024-02-01', 'A', 'VENTE', 5, 600, source_doc='b.pdf')])
        d = client.get('/api/transactions/realized').get_json()
        assert d['untracked_lines'] == 1
