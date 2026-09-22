"""ETF de comparaison de l'onglet Performance.

Le choix de l'ETF se fait sans le dire a l'utilisateur : il doit donc etre
sur. Un ETF cote hors euro comparerait une performance en devise a un TWR en
euros, et l'ecart affiche contiendrait le change.
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


def _titre(c, isin, nom, devise, cours):
    c.execute('INSERT INTO securities (isin, name, currency) VALUES (?,?,?)', (isin, nom, devise))
    for d, p in cours:
        c.execute('INSERT INTO price_history (isin, date, price) VALUES (?,?,?)', (isin, d, p))


def _get(client, debut='2026-02-01', fin='2026-04-30'):
    return client.get(f'/api/benchmark?debut={debut}&fin={fin}').get_json()


def test_un_etf_en_dollars_n_est_pas_retenu_d_office(client):
    with get_db() as c:
        # Le dollar a la plus longue serie : il serait choisi sans le filtre.
        _titre(c, 'IE00USD', 'iShares MSCI World', 'USD',
               [('2026-01-15', 90), ('2026-02-15', 92), ('2026-03-15', 95), ('2026-04-15', 97)])
        _titre(c, 'LU00EUR', 'Amundi MSCI World', 'EUR', [('2026-01-15', 100), ('2026-03-15', 104)])
        c.commit()
    r = _get(client)
    assert r['isin'] == 'LU00EUR'
    assert r['devise'] == 'EUR'


def test_sans_etf_en_euros_pas_de_comparaison(client):
    with get_db() as c:
        _titre(c, 'IE00USD', 'iShares MSCI World', 'USD', [('2026-01-15', 90), ('2026-03-15', 95)])
        c.commit()
    assert _get(client)['isin'] is None


def test_un_etf_impose_hors_euro_est_garde_et_sa_devise_dite(client):
    with get_db() as c:
        _titre(c, 'IE00USD', 'iShares MSCI World', 'USD', [('2026-01-15', 90), ('2026-03-15', 95)])
        c.execute("INSERT INTO config (key, value) VALUES ('benchmark_isin', 'IE00USD')")
        c.commit()
    r = _get(client)
    assert r['isin'] == 'IE00USD' and r['devise'] == 'USD'


def test_un_cours_nul_ne_sert_pas_d_ancre(client):
    with get_db() as c:
        _titre(c, 'LU00EUR', 'Amundi MSCI World', 'EUR',
               [('2026-01-10', 100), ('2026-01-20', 0), ('2026-03-15', 104)])
        c.commit()
    r = _get(client)
    assert r['points'][0] == {'date': '2026-01-10', 'price': 100}
    assert all(p['price'] > 0 for p in r['points'])


def test_une_declinaison_thematique_n_est_pas_le_marche(client):
    with get_db() as c:
        _titre(c, 'LU00TEC', 'Amundi MSCI World Information Technology', 'EUR',
               [('2026-01-15', 100), ('2026-02-15', 101), ('2026-03-15', 110)])
        _titre(c, 'LU00EUR', 'Amundi MSCI World', 'EUR', [('2026-01-15', 100), ('2026-03-15', 104)])
        c.commit()
    assert _get(client)['isin'] == 'LU00EUR'
