"""Tests du rapprochement entre la photo (`holdings`) et le journal (`transactions`).

Scenario de reference : celui rencontre en prod. Une photo au 12/08 portant
2 640 parts, deux avis d'achat posterieurs (120 le 17/08, 215 le 31/08) jamais
repercutes, et un arrete du 02/09 qui recopie la photo perimee.
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

from models import init_db, get_db  # noqa: E402
from app import app  # noqa: E402
from services.reconcile import reconcile_snapshot, apply_ecart  # noqa: E402
from services.montants import centimes  # noqa: E402

ISIN = 'IE0002XZSHO1'
CSRF = {'X-CSRF-Token': 'test'}


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


def _seed(holding=None, txs=(), price=7.12, price_date='2026-08-21',
          date='2026-09-02', owner='Paul', envelope='PEA',
          establishment='BoursoBank', isin=ISIN):
    """Cree un arrete avec une position a holdings et un journal d'operations."""
    with get_db() as conn:
        conn.execute('INSERT OR IGNORE INTO securities '
                     '(isin, name, last_price, last_price_date, is_priceable) '
                     'VALUES (?,?,?,?,1)', (isin, 'ETF Test', price, price_date))
        cur = conn.execute(
            'INSERT INTO positions (date, owner, category, envelope, establishment, value) '
            "VALUES (?,?,'Financier',?,?,0)", (date, owner, envelope, establishment))
        pid = cur.lastrowid
        hid = None
        if holding:
            cur = conn.execute(
                'INSERT INTO holdings (position_id, isin, quantity, cost_basis, '
                'market_value, as_of_date) VALUES (?,?,?,?,?,?)',
                (pid, isin, holding['quantity'], holding.get('cost_basis'),
                 holding.get('market_value'), holding.get('as_of_date')))
            hid = cur.lastrowid
        for t in txs:
            conn.execute(
                '''INSERT INTO transactions (date, owner, envelope, establishment,
                   isin, side, quantity, net_eur, source_doc)
                   VALUES (?,?,?,?,?,?,?,?,?)''',
                (t['date'], t.get('owner', owner), t.get('envelope', envelope),
                 t.get('establishment', establishment), t.get('isin', isin),
                 t['side'], t['quantity'], centimes(t['net_eur']),
                 t.get('source_doc') or f"doc:{t['date']}:{t['quantity']}"))
        conn.commit()
    return pid, hid


PHOTO = {'quantity': 2640, 'cost_basis': 15470.40,
         'market_value': 19140.0, 'as_of_date': '2026-08-12'}
AVIS = [
    {'date': '2026-08-17', 'side': 'ACHAT', 'quantity': 120, 'net_eur': 851.64},
    {'date': '2026-08-31', 'side': 'ACHAT', 'quantity': 215, 'net_eur': 1535.19},
]


class TestDetection:
    def test_ecart_detecte_et_chiffre(self):
        _seed(PHOTO, AVIS)
        with get_db() as conn:
            r = reconcile_snapshot(conn, '2026-09-02')
        assert len(r['ecarts']) == 1
        e = r['ecarts'][0]
        assert e['quantity'] == 2640
        assert e['delta_quantity'] == 335
        assert e['expected'] == 2975
        assert e['cost_delta'] == 2386.83
        assert [o['date'] for o in e['operations']] == ['2026-08-17', '2026-08-31']

    def test_photo_a_jour_aucun_ecart(self):
        # date de valeur posterieure aux deux avis : rien a signaler
        _seed({**PHOTO, 'quantity': 2975, 'as_of_date': '2026-09-01'}, AVIS)
        with get_db() as conn:
            r = reconcile_snapshot(conn, '2026-09-02')
        assert r['ecarts'] == []
        assert r['verifiees'] == 1

    def test_vente_donne_un_delta_negatif(self):
        _seed(PHOTO, [{'date': '2026-08-20', 'side': 'VENTE',
                       'quantity': 40, 'net_eur': 284.80}])
        with get_db() as conn:
            r = reconcile_snapshot(conn, '2026-09-02')
        e = r['ecarts'][0]
        assert e['delta_quantity'] == -40
        assert e['expected'] == 2600
        assert e['cost_delta'] == -284.8

    def test_operation_posterieure_a_l_arrete_ignoree(self):
        # un avis du 15/09 ne saurait figurer dans l'arrete du 02/09
        _seed(PHOTO, [{'date': '2026-09-15', 'side': 'ACHAT',
                       'quantity': 100, 'net_eur': 700.0}])
        with get_db() as conn:
            r = reconcile_snapshot(conn, '2026-09-02')
        assert r['ecarts'] == []

    def test_sans_date_de_valeur_non_verifiable(self):
        _seed({**PHOTO, 'as_of_date': None}, AVIS)
        with get_db() as conn:
            r = reconcile_snapshot(conn, '2026-09-02')
        assert r['ecarts'] == []
        assert r['ignores']['sans_date_valeur'] == 1
        assert r['verifiees'] == 0


class TestBruitEcarte:
    def test_ligne_soldee_ne_crie_pas_au_loup(self):
        # tout achete puis tout vendu : absent de la photo, et c'est normal
        _seed(None, [
            {'date': '2025-01-10', 'side': 'ACHAT', 'quantity': 100, 'net_eur': 500.0},
            {'date': '2025-06-10', 'side': 'VENTE', 'quantity': 100, 'net_eur': 600.0},
        ])
        with get_db() as conn:
            r = reconcile_snapshot(conn, '2026-09-02')
        assert r['absents'] == []
        assert r['ignores']['soldees'] == 1

    def test_titre_encore_detenu_mais_absent_de_la_photo(self):
        _seed(None, [{'date': '2026-08-17', 'side': 'ACHAT',
                      'quantity': 120, 'net_eur': 851.64}])
        with get_db() as conn:
            r = reconcile_snapshot(conn, '2026-09-02')
        assert len(r['absents']) == 1
        assert r['absents'][0]['expected'] == 120
        assert r['ignores']['soldees'] == 0

    def test_titulaires_distincts_ne_se_confondent_pas(self):
        # meme ISIN, meme enveloppe, meme etablissement, deux personnes :
        # l'avis de Paul ne doit pas etre imputé a la ligne de Claire
        pid, hid = _seed(PHOTO, AVIS)
        _seed({'quantity': 80, 'cost_basis': 420.0, 'market_value': 569.6,
               'as_of_date': '2026-08-12'}, (), owner='Claire')
        with get_db() as conn:
            r = reconcile_snapshot(conn, '2026-09-02')
        assert len(r['ecarts']) == 1
        assert r['ecarts'][0]['owner'] == 'Paul'

    def test_ambiguite_signalee_jamais_devinee(self):
        # deux contrats de la meme personne chez le meme etablissement portent
        # le meme support : on ne choisit pas a qui imputer l'operation
        _seed(PHOTO, AVIS)
        with get_db() as conn:
            pid = conn.execute(
                'INSERT INTO positions (date, owner, category, envelope, '
                "establishment, value) VALUES ('2026-09-02','Paul','Financier',"
                "'PEA','BoursoBank',0)").lastrowid
            conn.execute('INSERT INTO holdings (position_id, isin, quantity, '
                         "as_of_date) VALUES (?,?,10,'2026-08-12')", (pid, ISIN))
            conn.commit()
            r = reconcile_snapshot(conn, '2026-09-02')
        assert r['ecarts'] == []
        assert r['ignores']['ambigues'] == 2


class TestApplication:
    def test_applique_quantite_cout_et_date(self):
        _seed(PHOTO, AVIS)
        with get_db() as conn:
            r = reconcile_snapshot(conn, '2026-09-02')
            hid = r['ecarts'][0]['holding_id']
            detail = apply_ecart(conn, '2026-09-02', hid)
            conn.commit()
            row = conn.execute('SELECT * FROM holdings WHERE id=?', (hid,)).fetchone()
        assert row['quantity'] == 2975
        assert row['cost_basis'] == 17857.23
        assert row['as_of_date'] == '2026-08-31'      # date du dernier avis integre
        assert row['market_value'] == 21182.00        # 2975 x cours 7,12
        assert detail['quantity'] == {'avant': 2640.0, 'apres': 2975.0}

    def test_rejouer_ne_double_pas(self):
        _seed(PHOTO, AVIS)
        with get_db() as conn:
            hid = reconcile_snapshot(conn, '2026-09-02')['ecarts'][0]['holding_id']
            apply_ecart(conn, '2026-09-02', hid)
            assert apply_ecart(conn, '2026-09-02', hid) is None
            conn.commit()
            row = conn.execute('SELECT quantity FROM holdings WHERE id=?', (hid,)).fetchone()
        assert row['quantity'] == 2975

    def test_sans_cours_le_prix_de_la_photo_sert(self):
        # market_value 19140 / 2640 parts = 7,2500 EUR la part
        _seed(PHOTO, AVIS, price=None, price_date=None)
        with get_db() as conn:
            hid = reconcile_snapshot(conn, '2026-09-02')['ecarts'][0]['holding_id']
            apply_ecart(conn, '2026-09-02', hid)
            conn.commit()
            row = conn.execute('SELECT market_value FROM holdings WHERE id=?', (hid,)).fetchone()
        assert row['market_value'] == 21568.75         # 2975 x 7,25


class TestEndpoints:
    def test_get_defaut_dernier_arrete(self, client):
        _seed(PHOTO, AVIS)
        r = client.get('/api/holdings/reconcile')
        assert r.status_code == 200
        assert r.json['date'] == '2026-09-02'
        assert len(r.json['ecarts']) == 1

    def test_get_date_invalide(self, client):
        _seed(PHOTO, AVIS)
        assert client.get('/api/holdings/reconcile?date=hier').status_code == 400

    def test_get_sans_donnees(self, client):
        r = client.get('/api/holdings/reconcile')
        assert r.status_code == 200
        assert r.json['ecarts'] == []

    def test_apply_recale_la_position(self, client):
        pid, hid = _seed(PHOTO, AVIS)
        r = client.post('/api/holdings/reconcile/apply',
                        json={'date': '2026-09-02', 'holding_ids': [hid]},
                        headers=CSRF)
        assert r.status_code == 200
        assert len(r.json['appliquees']) == 1
        with get_db() as conn:
            pos = conn.execute('SELECT value FROM positions WHERE id=?', (pid,)).fetchone()
        assert pos['value'] == 21182.00               # positions.value suit les holdings

    def test_apply_ligne_sans_ecart_est_ignoree(self, client):
        _, hid = _seed({**PHOTO, 'quantity': 2975, 'as_of_date': '2026-09-01'}, AVIS)
        r = client.post('/api/holdings/reconcile/apply',
                        json={'date': '2026-09-02', 'holding_ids': [hid]},
                        headers=CSRF)
        assert r.status_code == 200
        assert r.json['ignorees'] == [hid]
        assert r.json['appliquees'] == []

    def test_apply_valide_ses_entrees(self, client):
        _seed(PHOTO, AVIS)
        for payload in ({'date': 'hier', 'holding_ids': [1]},
                        {'date': '2026-09-02', 'holding_ids': []},
                        {'date': '2026-09-02', 'holding_ids': ['1']},
                        {'date': '2026-09-02'}):
            r = client.post('/api/holdings/reconcile/apply', json=payload, headers=CSRF)
            assert r.status_code == 400, payload

    def test_apply_exige_le_csrf(self, client):
        _, hid = _seed(PHOTO, AVIS)
        r = client.post('/api/holdings/reconcile/apply',
                        json={'date': '2026-09-02', 'holding_ids': [hid]})
        assert r.status_code in (400, 403)

    def test_endpoints_exigent_la_session(self):
        app.config['TESTING'] = True
        with app.test_client() as anon:
            assert anon.get('/api/holdings/reconcile').status_code in (302, 401)
            assert anon.post('/api/holdings/reconcile/apply',
                             json={'date': '2026-09-02', 'holding_ids': [1]}
                             ).status_code in (302, 401, 400, 403)
