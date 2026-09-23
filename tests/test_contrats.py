"""Anciennete des contrats : date d'effet, maturite fiscale, effet sur l'impot
latent et constat."""
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
from services.contrats import contrats, enregistrer  # noqa: E402

H = {'X-CSRF-Token': 'test'}
D = '2026-09-01'


@pytest.fixture(autouse=True)
def fresh_db():
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)
    init_db()
    with get_db() as conn:
        for owner, etab, v in (('Paul', 'Bourso', 50000), ('Paul', 'Generali', 30000)):
            conn.execute("INSERT INTO positions (date, owner, category, envelope, establishment, value) "
                         "VALUES (?, ?, 'Fond Euro', 'Assurance-vie', ?, ?)", (D, owner, etab, v))
        conn.execute("INSERT INTO flux (date, owner, envelope, type, amount) VALUES ('2025-01-01', 'Paul', 'Assurance-vie', 'Versement', 7000000)")  # centimes
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


def test_maturite_a_huit_ans():
    with get_db() as conn:
        enregistrer(conn, [{'owner': 'Paul', 'envelope': 'Assurance-vie', 'establishment': 'Bourso', 'date_effet': '2017-02-03'}])
        cs = {c['establishment']: c for c in contrats(conn, D)}
    assert cs['Bourso']['maturite'] == '2025-02-03' and cs['Bourso']['mature'] is True
    assert cs['Generali']['date_effet'] is None and cs['Generali']['mature'] is None


def test_contrats_jeunes_au_prelevement_forfaitaire():
    from services.fiscalite import impot_latent
    with get_db() as conn:
        enregistrer(conn, [{'owner': 'Paul', 'envelope': 'Assurance-vie', 'establishment': e, 'date_effet': '2024-10-27'}
                           for e in ('Bourso', 'Generali')])
        av = next(l for l in impot_latent(conn, D)['enveloppes'] if l['enveloppe'] == 'Assurance-vie')
    assert av['regime'] == 'pfu' and av['impot'] == pytest.approx(10000 * 0.30)
    assert '27/10/2032' in av['motif']


def test_sans_date_l_hypothese_le_dit():
    from services.fiscalite import impot_latent
    with get_db() as conn:
        enregistrer(conn, [{'owner': 'Paul', 'envelope': 'Assurance-vie', 'establishment': 'Bourso', 'date_effet': '2024-10-27'}])
        av = next(l for l in impot_latent(conn, D)['enveloppes'] if l['enveloppe'] == 'Assurance-vie')
    assert av['regime'] == 'av' and 'sous-estime' in av['motif']


def test_constat_et_routes(client):
    r = client.put('/api/contrats', headers=H, json={'contrats': [
        {'owner': 'Paul', 'envelope': 'Assurance-vie', 'establishment': 'Bourso', 'date_effet': '2024-05-25'}]})
    assert r.status_code == 200
    assert client.put('/api/contrats', headers=H, json={'contrats': [
        {'owner': 'Paul', 'envelope': 'Livret A', 'date_effet': '2024-05-25'}]}).status_code == 400
    from services.advisor.constats import constats
    with get_db() as conn:
        (k,) = [k for k in constats(conn, D)['constats'] if 'assurance' in k['titre'].lower()]
    assert '25/05/2032 (Paul · Bourso)' in k['detail'] and 'Paul · Generali' in k['detail']
