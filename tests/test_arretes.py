"""Gestion des arretes : ce qu'une operation sur un arrete ne doit pas casser
ailleurs. Defauts releves a la revue du 23/09/2026, chacun reproduit avant
correction."""
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


def _sci(c, dates_valeurs):
    c.execute("INSERT INTO entities (name, type, gross_assets, debt) VALUES ('SCI', 'SCI', 300000, 0)")
    for d, v in dates_valeurs:
        c.execute("INSERT INTO entity_snapshots (entity_name, date, gross_assets, debt) VALUES ('SCI', ?, ?, 0)", (d, v))


def _pos_sci(c, date):
    c.execute("INSERT INTO positions (date, owner, category, envelope, value, entity, ownership_pct) "
              "VALUES (?, 'Paul', 'Immobilier', 'Direct', 0, 'SCI', 1.0)", (date,))


def _net(client, date):
    return client.get(f'/api/synthese?date={date}').get_json()['family']['net']


def test_supprimer_un_arrete_ne_revalorise_pas_les_suivants(client):
    with get_db() as c:
        _sci(c, [('2026-01-01', 100000)])
        _pos_sci(c, '2026-01-01'); _pos_sci(c, '2026-02-01'); c.commit()
    assert _net(client, '2026-02-01') == pytest.approx(100000)
    client.post('/api/snapshots/delete', json={'date': '2026-01-01'}, headers=H)
    assert _net(client, '2026-02-01') == pytest.approx(100000)     # et non 300 000


def test_renommer_un_arrete_garde_la_valorisation_des_suivants(client):
    with get_db() as c:
        _sci(c, [('2026-01-01', 100000)])
        _pos_sci(c, '2026-01-01'); _pos_sci(c, '2026-02-01'); c.commit()
    client.post('/api/snapshots/rename', json={'from_date': '2026-01-01', 'to_date': '2026-03-01'}, headers=H)
    assert _net(client, '2026-02-01') == pytest.approx(100000)


def test_avant_la_premiere_valorisation_la_plus_ancienne_sert(client):
    with get_db() as c:
        _sci(c, [('2026-04-01', 100000)])
        _pos_sci(c, '2026-02-01'); c.commit()
    assert _net(client, '2026-02-01') == pytest.approx(100000)     # et non la valeur courante


def test_renommer_vers_une_date_qui_a_une_note_repond_409(client):
    with get_db() as c:
        _pos_sci(c, '2026-01-01')
        c.execute("INSERT INTO snapshot_notes (date, notes) VALUES ('2026-03-01', 'x')"); c.commit()
    r = client.post('/api/snapshots/rename', json={'from_date': '2026-01-01', 'to_date': '2026-03-01'}, headers=H)
    assert r.status_code == 409


def test_auto_snapshot_refuse_une_date_invalide(client):
    with get_db() as c:
        _pos_sci(c, '2026-01-01'); c.commit()
    assert client.post('/api/auto-snapshot', json={'date': 'n-importe-quoi'}, headers=H).status_code == 400


def test_mise_a_jour_sans_dette_garde_la_dette_connue(client):
    with get_db() as c:
        c.execute("INSERT INTO entities (name, type, gross_assets, debt) VALUES ('SCI', 'SCI', 300000, 80000)")
        _pos_sci(c, '2026-01-01'); c.commit()
    r = client.post('/api/snapshots/update', json={'source_date': '2026-01-01', 'target_date': '2026-02-01',
                                                   'entites': {'SCI': {'gross_assets': 310000}}}, headers=H)
    assert r.status_code == 200, r.get_json()
    with get_db() as c:
        dette = c.execute("SELECT debt FROM entity_snapshots WHERE entity_name='SCI' AND date='2026-02-01'").fetchone()[0]
    assert dette == 80000


def test_snapshot_update_ne_laisse_pas_de_lignes_orphelines(client):
    with get_db() as c:
        c.execute("INSERT INTO positions (date, owner, category, envelope, value) VALUES ('2026-01-01','Paul','Actions','PEA',100)")
        pid = c.execute("SELECT id FROM positions").fetchone()[0]
        c.execute("INSERT INTO positions (date, owner, category, envelope, value) VALUES ('2026-02-01','Paul','Actions','PEA',100)")
        cible = c.execute("SELECT id FROM positions WHERE date='2026-02-01'").fetchone()[0]
        c.execute("INSERT INTO securities (isin, name) VALUES ('FR0000120271','T')")
        c.execute("INSERT INTO holdings (position_id, isin, quantity) VALUES (?, 'FR0000120271', 1)", (cible,))
        c.commit()
    r = client.post(f'/api/positions/{pid}/snapshot-update', json={'source_date': '2026-01-01', 'target_date': '2026-02-01',
          'position': {'owner': 'Paul', 'category': 'Actions', 'envelope': 'PEA', 'value': 120}},
          headers=H)
    assert r.status_code in (200, 201), r.get_json()
    with get_db() as c:
        orph = c.execute("SELECT COUNT(*) FROM holdings WHERE position_id NOT IN (SELECT id FROM positions)").fetchone()[0]
    assert orph == 0
