"""Renommer une categorie ou une enveloppe se propage aux positions et aux flux.

Sur la base de prod (revue du 23/09/2026), renommer « Actions » faisait
disparaitre 110 000 € de la repartition : seule la cle du referentiel changeait.
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

from models import init_db, get_db, load_referential  # noqa: E402
from app import app  # noqa: E402

H = {'X-CSRF-Token': 'test'}


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


def _ref(client, renommer):
    ref = client.get('/api/referential').get_json()
    renommer(ref)
    return ref


def test_renommer_une_categorie_propage_positions_flux_et_cibles(client):
    with get_db() as c:
        c.execute("INSERT INTO positions (date, owner, category, envelope, value) VALUES ('2026-01-01','Paul','Actions','PEA',1000)")
        c.execute("INSERT INTO positions (date, owner, category, envelope, value) VALUES ('2025-01-01','Paul','Actions','PEA',900)")
        c.execute("INSERT INTO flux (date, owner, envelope, type, amount, category) VALUES ('2026-01-02','Paul','PEA','Versement',1000,'Actions')")  # centimes
        c.execute("INSERT INTO config (key, value) VALUES ('allocation_targets', '{\"Actions\": 60}')")
        c.commit()
    def f(ref):
        ref['categories'] = ['Actions cotées' if x == 'Actions' else x for x in ref['categories']]
        ref['category_mobilizable']['Actions cotées'] = ref['category_mobilizable'].pop('Actions')
        ref['renommages'] = [{'champ': 'category', 'ancien': 'Actions', 'nouveau': 'Actions cotées'}]
    r = client.put('/api/referential', json=_ref(client, f), headers=H)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['renommages'][0]['positions'] == 2
    with get_db() as c:
        assert c.execute("SELECT COUNT(*) FROM positions WHERE category='Actions'").fetchone()[0] == 0
        assert c.execute("SELECT category FROM flux").fetchone()[0] == 'Actions cotées'
        import json
        assert json.loads(c.execute("SELECT value FROM config WHERE key='allocation_targets'").fetchone()[0]) == {'Actions cotées': 60}


def test_renommer_une_enveloppe_propage(client):
    with get_db() as c:
        c.execute("INSERT INTO positions (date, owner, category, envelope, value) VALUES ('2026-01-01','Paul','Actions','PEA',1000)")
        c.execute("INSERT INTO flux (date, owner, envelope, type, amount) VALUES ('2026-01-02','Paul','PEA','Versement',1000)")  # centimes
        c.commit()
    def f(ref):
        ref['envelope_meta']['PEA Bourso'] = ref['envelope_meta'].pop('PEA')
        ref['renommages'] = [{'champ': 'envelope', 'ancien': 'PEA', 'nouveau': 'PEA Bourso'}]
    assert client.put('/api/referential', json=_ref(client, f), headers=H).status_code == 200
    with get_db() as c:
        assert c.execute("SELECT envelope FROM positions").fetchone()[0] == 'PEA Bourso'
        assert c.execute("SELECT envelope FROM flux").fetchone()[0] == 'PEA Bourso'


def test_renommer_vers_un_nom_existant_est_refuse(client):
    def f(ref):
        ref['categories'] = [x for x in ref['categories']] + ['Crypto']
        ref['renommages'] = [{'champ': 'category', 'ancien': 'Actions', 'nouveau': 'Crypto'}]
    r = client.put('/api/referential', json=_ref(client, f), headers=H)
    assert r.status_code == 400


def test_le_decompte_couvre_toutes_les_dates(client):
    with get_db() as c:
        for d in ('2025-01-01', '2026-01-01'):
            c.execute("INSERT INTO positions (date, owner, category, envelope, value) VALUES (?, 'Paul','Actions','PEA',1)", (d,))
        c.commit()
    assert client.get('/api/referential/usage?champ=category&valeur=Actions').get_json()['positions'] == 2
