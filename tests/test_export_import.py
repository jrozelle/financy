"""Export / import JSON : une sauvegarde qui revient a l'identique.

Releve le 23/09/2026 sur la base de prod : reimporter un export doublait les
montants et les flux ; restaurer apres un reset perdait des positions et
rattachait les titres de deux contrats au premier.
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

from models import init_db, get_db  # noqa: E402
from app import app  # noqa: E402

H = {'X-CSRF-Token': 'test'}
D = '2026-06-30'


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


def _base():
    with get_db() as c:
        # Deux assurances-vie du meme titulaire chez deux assureurs, chacune ses titres.
        for etab, isin, mv in (('Bourso', 'FR0000120271', 1000), ('CA31', 'US0378331005', 2000)):
            pid = c.execute("INSERT INTO positions (date, owner, category, envelope, establishment, value, label) "
                            "VALUES (?, 'Paul', 'Actions', 'Assurance-vie', ?, 0, ?)", (D, etab, f'AV {etab}')).lastrowid
            c.execute("INSERT OR IGNORE INTO securities (isin, name, is_priceable) VALUES (?, 'T', 0)", (isin,))
            c.execute("INSERT INTO holdings (position_id, isin, quantity, market_value) VALUES (?, ?, 1, ?)", (pid, isin, mv))
        # Deux livrets identiques : deux lignes, pas un doublon.
        for v in (23000, 23000):
            c.execute("INSERT INTO positions (date, owner, category, envelope, establishment, value) "
                      "VALUES (?, 'Claire', 'Cash & dépôts', 'Livret A', 'CEMP', ?)", (D, v))
        for _ in range(2):   # deux versements egaux le meme jour
            c.execute("INSERT INTO flux (date, owner, envelope, establishment, type, amount) "
                      "VALUES ('2026-06-01', 'Paul', 'Assurance-vie', 'CA31', 'Versement', 500)")
        c.execute("INSERT INTO transactions (date, owner, envelope, isin, side, quantity, net_eur) "
                  "VALUES ('2026-06-02', 'Paul', 'PEA', 'FR0000120271', 'ACHAT', 1, 100)")
        c.commit()


def _etat(client):
    with get_db() as c:
        comptes = c.execute("SELECT p.establishment, h.isin, h.market_value FROM holdings h "
                            "JOIN positions p ON p.id = h.position_id ORDER BY 1").fetchall()
        return (client.get(f'/api/synthese?date={D}').get_json()['family']['net'],
                c.execute('SELECT COUNT(*) FROM positions').fetchone()[0],
                c.execute('SELECT COUNT(*), SUM(amount) FROM flux').fetchone()[:],
                c.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],
                [tuple(r) for r in comptes])


def test_reimporter_un_export_ne_double_rien(client):
    _base()
    avant = _etat(client)
    r = client.post('/api/import-json', json=client.get('/api/export').get_json(), headers=H)
    assert r.status_code == 200 and r.get_json()['backup']
    assert _etat(client) == avant


def test_export_reset_import_restaure_a_l_identique(client):
    _base()
    avant = _etat(client)
    exp = client.get('/api/export').get_json()
    client.post('/api/reset', json={'confirm': 'VIDER'}, headers=H)
    assert _etat(client)[1] == 0
    client.post('/api/import-json', json=exp, headers=H)
    assert _etat(client) == avant


def test_l_export_ne_contient_pas_la_cle_api(client):
    with get_db() as c:
        c.execute("INSERT INTO config (key, value) VALUES ('settings', '{\"anthropic_api_key\": \"sk-ant-secret\"}')")
        c.commit()
    assert 'sk-ant-secret' not in client.get('/api/export').get_data(as_text=True)


def test_un_export_au_format_1_reste_lisible(client):
    ancien = {'positions': [{'date': D, 'owner': 'Paul', 'category': 'Actions', 'envelope': 'PEA', 'value': 0}],
              'securities': [{'isin': 'FR0000120271', 'name': 'T', 'is_priceable': 0}],
              'holdings': [{'isin': 'FR0000120271', 'quantity': 2, 'market_value': 300, 'pos_date': D,
                            'pos_owner': 'Paul', 'pos_category': 'Actions', 'pos_envelope': 'PEA', 'pos_entity': ''}],
              'flux': []}
    r = client.post('/api/import-json', json=ancien, headers=H).get_json()
    assert r['positions'] == 1 and r['holdings'] == 1
