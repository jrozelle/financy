"""Comprehensive API integration tests for the Financy Flask app."""

import pytest
import os
import json
import tempfile

# Patch DB_PATH before importing anything from models/app
import models

_tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_tmp.close()
models.DB_PATH = _tmp.name
models._BASE_DIR = os.path.dirname(_tmp.name)

os.environ['FINANCY_PASSWORD'] = 'testpass'

from models import init_db, get_db
from app import app


# ─── Fixtures ────────────────────────────────────────────────────────────────

CSRF_HEADERS = {'X-CSRF-Token': 'test'}


@pytest.fixture(autouse=True)
def fresh_db():
    """Create a clean DB before each test."""
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)
    init_db()
    yield
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)


@pytest.fixture
def client():
    """Authenticated Flask test client."""
    app.config['TESTING'] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['authenticated'] = True
            s['csrf_token'] = 'test'
        yield c


@pytest.fixture
def anon_client():
    """Unauthenticated Flask test client."""
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def _make_position(client, date='2024-06-01', owner='Alice', category='Actions',
                   envelope='PEA', value=10000, debt=0, **kwargs):
    """Helper to create a position and return JSON response."""
    payload = {
        'date': date, 'owner': owner, 'category': category,
        'envelope': envelope, 'value': value, 'debt': debt,
        'ownership_pct': kwargs.get('ownership_pct', 1.0),
        'debt_pct': kwargs.get('debt_pct', 1.0),
    }
    payload.update(kwargs)
    resp = client.post('/api/positions', json=payload, headers=CSRF_HEADERS)
    return resp


def _make_flux(client, date='2024-06-01', owner='Alice', amount=1000, **kwargs):
    """Helper to create a flux and return response."""
    payload = {
        'date': date, 'owner': owner, 'amount': amount,
        'envelope': kwargs.get('envelope', 'PEA'),
        'type': kwargs.get('type', 'Versement'),
    }
    payload.update(kwargs)
    resp = client.post('/api/flux', json=payload, headers=CSRF_HEADERS)
    return resp


def _make_entity(client, name='SCI Test', gross_assets=300000, debt=100000, **kwargs):
    """Helper to create an entity and return response."""
    payload = {'name': name, 'gross_assets': gross_assets, 'debt': debt}
    payload.update(kwargs)
    resp = client.post('/api/entities', json=payload, headers=CSRF_HEADERS)
    return resp


# ─── TestAuth ────────────────────────────────────────────────────────────────

class TestAuth:
    def test_login_page_get(self, anon_client):
        resp = anon_client.get('/login')
        assert resp.status_code == 200

    def test_login_post_wrong_password(self, anon_client):
        # First GET to generate csrf_token in session
        anon_client.get('/login')
        with anon_client.session_transaction() as s:
            token = s.get('csrf_token', '')
        resp = anon_client.post('/login', data={'password': 'wrong', 'csrf_token': token})
        assert resp.status_code == 200
        assert 'incorrect' in resp.data.decode().lower() or 'Mot de passe' in resp.data.decode()

    def test_login_post_no_csrf(self, anon_client):
        anon_client.get('/login')
        resp = anon_client.post('/login', data={'password': 'testpass', 'csrf_token': ''})
        assert resp.status_code == 200
        # Should fail because CSRF token is empty/wrong
        assert 'expir' in resp.data.decode().lower() or 'Session' in resp.data.decode()

    def test_login_post_success(self, anon_client):
        anon_client.get('/login')
        with anon_client.session_transaction() as s:
            token = s.get('csrf_token', '')
        resp = anon_client.post('/login', data={'password': 'testpass', 'csrf_token': token},
                                follow_redirects=False)
        assert resp.status_code == 302

    def test_logout(self, client):
        resp = client.get('/logout', follow_redirects=False)
        assert resp.status_code == 302

    def test_unauthenticated_api_returns_401(self, anon_client):
        resp = anon_client.get('/api/positions')
        assert resp.status_code == 401
        data = resp.get_json()
        assert 'error' in data

    def test_unauthenticated_api_multiple_endpoints(self, anon_client):
        for path in ['/api/positions', '/api/flux', '/api/entities', '/api/synthese',
                     '/api/timeline', '/api/export']:
            resp = anon_client.get(path)
            assert resp.status_code == 401, f'{path} should require auth'

    def test_csrf_required_for_post(self, client):
        # POST without CSRF header should return 403
        resp = client.post('/api/positions', json={
            'date': '2024-06-01', 'owner': 'Alice', 'category': 'Actions',
            'value': 1000,
        })
        assert resp.status_code == 403

    def test_csrf_token_endpoint(self, client):
        resp = client.get('/api/csrf-token')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'token' in data


# ─── TestPositions ───────────────────────────────────────────────────────────

class TestPositions:
    def test_create_position(self, client):
        resp = _make_position(client)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['owner'] == 'Alice'
        assert data['category'] == 'Actions'
        assert data['value'] == 10000
        assert 'net_attributed' in data
        assert data['net_attributed'] == 10000

    def test_get_positions_empty(self, client):
        resp = client.get('/api/positions')
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_get_positions_with_data(self, client):
        _make_position(client)
        resp = client.get('/api/positions')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['owner'] == 'Alice'

    def test_get_positions_by_date(self, client):
        _make_position(client, date='2024-01-01')
        _make_position(client, date='2024-06-01')
        resp = client.get('/api/positions?date=2024-01-01')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['date'] == '2024-01-01'

    def test_get_dates(self, client):
        _make_position(client, date='2024-01-01')
        _make_position(client, date='2024-06-01')
        resp = client.get('/api/dates')
        assert resp.status_code == 200
        dates = resp.get_json()
        assert '2024-01-01' in dates
        assert '2024-06-01' in dates

    def test_update_position(self, client):
        resp = _make_position(client)
        pid = resp.get_json()['id']
        resp = client.put(f'/api/positions/{pid}', json={
            'date': '2024-06-01', 'owner': 'Alice', 'category': 'Obligations',
            'envelope': 'CTO', 'value': 20000, 'debt': 0,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['category'] == 'Obligations'
        assert data['value'] == 20000

    def test_delete_position(self, client):
        resp = _make_position(client)
        pid = resp.get_json()['id']
        resp = client.delete(f'/api/positions/{pid}', headers=CSRF_HEADERS)
        assert resp.status_code == 204
        # Verify deleted
        resp = client.get('/api/positions')
        assert resp.get_json() == []

    def test_create_position_bad_date(self, client):
        resp = _make_position(client, date='not-a-date')
        assert resp.status_code == 400
        assert 'Date' in resp.get_json()['error'] or 'date' in resp.get_json()['error'].lower()

    def test_create_position_missing_owner(self, client):
        resp = client.post('/api/positions', json={
            'date': '2024-06-01', 'owner': '', 'category': 'Actions', 'value': 100,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_create_position_missing_category(self, client):
        resp = client.post('/api/positions', json={
            'date': '2024-06-01', 'owner': 'Alice', 'category': '', 'value': 100,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_create_position_bad_value(self, client):
        resp = _make_position(client, value=-5)
        assert resp.status_code == 400

    def test_create_position_bad_pct(self, client):
        resp = _make_position(client, ownership_pct=1.5)
        assert resp.status_code == 400

    def test_create_position_notes_too_long(self, client):
        resp = _make_position(client, notes='x' * 2001)
        assert resp.status_code == 400

    def test_create_position_with_entity(self, client):
        _make_entity(client, name='SCI Alpha', gross_assets=500000, debt=200000)
        resp = _make_position(client, entity='SCI Alpha', value=0, debt=0,
                              ownership_pct=0.5, debt_pct=0.5)
        assert resp.status_code == 201
        data = resp.get_json()
        # Value stored as 0 since entity is used; computed values come from entity
        assert data['gross_attributed'] == 250000  # 500000 * 0.5
        assert data['debt_attributed'] == 100000   # 200000 * 0.5

    def test_snapshot_update(self, client):
        r1 = _make_position(client, date='2024-01-01', owner='Alice', category='Actions',
                            value=10000)
        pid = r1.get_json()['id']
        _make_position(client, date='2024-01-01', owner='Bob', category='Obligations',
                       value=5000)
        resp = client.post(f'/api/positions/{pid}/snapshot-update', json={
            'source_date': '2024-01-01',
            'target_date': '2024-06-01',
            'position': {
                'owner': 'Alice', 'category': 'Actions',
                'envelope': 'PEA', 'value': 15000, 'debt': 0,
            },
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['target_date'] == '2024-06-01'
        assert data['count'] == 2  # both positions copied

    def test_snapshot_update_missing_fields(self, client):
        resp = client.post('/api/positions/1/snapshot-update', json={
            'source_date': '2024-01-01',
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_snapshot_update_no_source(self, client):
        resp = client.post('/api/positions/1/snapshot-update', json={
            'source_date': '2024-01-01',
            'target_date': '2024-06-01',
            'position': {'owner': 'A', 'category': 'B', 'value': 0},
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 404


# ─── TestFlux ────────────────────────────────────────────────────────────────

class TestFlux:
    def test_create_flux(self, client):
        resp = _make_flux(client)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['owner'] == 'Alice'
        assert data['amount'] == 1000

    def test_list_flux(self, client):
        _make_flux(client, date='2024-01-15')
        _make_flux(client, date='2024-06-15')
        resp = client.get('/api/flux')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2

    def test_list_flux_date_range(self, client):
        _make_flux(client, date='2024-01-15')
        _make_flux(client, date='2024-06-15')
        _make_flux(client, date='2024-12-15')
        resp = client.get('/api/flux?date_from=2024-03-01&date_to=2024-09-01')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['date'] == '2024-06-15'

    def test_update_flux(self, client):
        resp = _make_flux(client)
        fid = resp.get_json()['id']
        resp = client.put(f'/api/flux/{fid}', json={
            'date': '2024-06-01', 'owner': 'Alice',
            'envelope': 'CTO', 'type': 'Retrait', 'amount': 2000,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['amount'] == 2000
        assert data['type'] == 'Retrait'

    def test_delete_flux(self, client):
        resp = _make_flux(client)
        fid = resp.get_json()['id']
        resp = client.delete(f'/api/flux/{fid}', headers=CSRF_HEADERS)
        assert resp.status_code == 204
        resp = client.get('/api/flux')
        assert resp.get_json() == []

    def test_create_flux_bad_date(self, client):
        resp = _make_flux(client, date='invalid')
        assert resp.status_code == 400

    def test_create_flux_missing_owner(self, client):
        resp = client.post('/api/flux', json={
            'date': '2024-06-01', 'owner': '', 'amount': 100,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_create_flux_missing_amount(self, client):
        resp = client.post('/api/flux', json={
            'date': '2024-06-01', 'owner': 'Alice',
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_create_flux_notes_too_long(self, client):
        resp = _make_flux(client, notes='x' * 2001)
        assert resp.status_code == 400

    def test_create_flux_negative_amount(self, client):
        resp = _make_flux(client, amount=-500)
        assert resp.status_code == 201  # negative amounts are allowed


# ─── TestEntities ────────────────────────────────────────────────────────────

class TestEntities:
    def test_create_entity(self, client):
        resp = _make_entity(client)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['name'] == 'SCI Test'
        assert data['gross_assets'] == 300000
        assert data['debt'] == 100000
        assert data['net_assets'] == 200000

    def test_list_entities(self, client):
        _make_entity(client, name='SCI A')
        _make_entity(client, name='SCI B')
        resp = client.get('/api/entities')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2

    def test_update_entity(self, client):
        resp = _make_entity(client)
        eid = resp.get_json()['id']
        resp = client.put(f'/api/entities/{eid}', json={
            'name': 'SCI Updated', 'gross_assets': 400000, 'debt': 50000,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['name'] == 'SCI Updated'
        assert data['net_assets'] == 350000

    def test_delete_entity(self, client):
        resp = _make_entity(client)
        eid = resp.get_json()['id']
        resp = client.delete(f'/api/entities/{eid}', headers=CSRF_HEADERS)
        assert resp.status_code == 204
        resp = client.get('/api/entities')
        assert resp.get_json() == []

    def test_delete_entity_removes_snapshots(self, client):
        resp = _make_entity(client)
        eid = resp.get_json()['id']
        # Entity creation auto-creates a snapshot
        resp = client.get('/api/entity-snapshots?entity=SCI Test')
        assert len(resp.get_json()) > 0
        # Delete entity
        client.delete(f'/api/entities/{eid}', headers=CSRF_HEADERS)
        resp = client.get('/api/entity-snapshots?entity=SCI Test')
        assert resp.get_json() == []

    def test_create_entity_missing_name(self, client):
        resp = client.post('/api/entities', json={
            'gross_assets': 100,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_create_entity_bad_numbers(self, client):
        resp = _make_entity(client, gross_assets='not_a_number')
        assert resp.status_code == 400

    def test_create_entity_comment_too_long(self, client):
        resp = _make_entity(client, comment='x' * 2001)
        assert resp.status_code == 400

    def test_entity_snapshots_endpoint(self, client):
        _make_entity(client, name='SCI Snap')
        resp = client.get('/api/entity-snapshots?entity=SCI Snap')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1
        assert data[0]['entity_name'] == 'SCI Snap'

    def test_entity_snapshots_all(self, client):
        _make_entity(client, name='SCI A')
        _make_entity(client, name='SCI B')
        resp = client.get('/api/entity-snapshots')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 2

    def test_delete_entity_snapshot(self, client):
        _make_entity(client, name='SCI Del')
        resp = client.get('/api/entity-snapshots?entity=SCI Del')
        sid = resp.get_json()[0]['id']
        resp = client.delete(f'/api/entity-snapshots/{sid}', headers=CSRF_HEADERS)
        assert resp.status_code == 204


# ─── TestSynthese ────────────────────────────────────────────────────────────

class TestSynthese:
    def test_synthese_empty_db(self, client):
        resp = client.get('/api/synthese')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['date'] is None

    def test_synthese_with_data(self, client):
        _make_position(client, date='2024-06-01', owner='Alice', value=10000)
        _make_position(client, date='2024-06-01', owner='Bob', value=5000,
                       category='Obligations', envelope='CTO')
        resp = client.get('/api/synthese?date=2024-06-01')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['date'] == '2024-06-01'
        assert data['family']['net'] == 15000
        assert 'Alice' in data['totals_by_owner']
        assert 'Bob' in data['totals_by_owner']
        assert data['totals_by_owner']['Alice']['net'] == 10000

    def test_synthese_variation(self, client):
        _make_position(client, date='2024-01-01', owner='Alice', value=10000)
        _make_position(client, date='2024-06-01', owner='Alice', value=15000)
        resp = client.get('/api/synthese?date=2024-06-01')
        data = resp.get_json()
        assert data['variation'] is not None
        assert data['variation']['net_delta'] == 5000

    def test_synthese_default_date(self, client):
        _make_position(client, date='2024-01-01', owner='Alice', value=10000)
        _make_position(client, date='2024-06-01', owner='Alice', value=15000)
        resp = client.get('/api/synthese')
        data = resp.get_json()
        assert data['date'] == '2024-06-01'  # latest date

    def test_historique_empty(self, client):
        resp = client.get('/api/historique')
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_historique_with_data(self, client):
        _make_position(client, date='2024-01-01', owner='Alice', value=10000)
        _make_position(client, date='2024-06-01', owner='Alice', value=15000)
        resp = client.get('/api/historique')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        assert data[0]['date'] == '2024-01-01'
        assert data[0]['family_net'] == 10000

    def test_historique_group_by_category(self, client):
        _make_position(client, date='2024-06-01', owner='Alice', category='Actions', value=10000)
        resp = client.get('/api/historique?group_by=category')
        data = resp.get_json()
        assert len(data) == 1
        assert 'by_group' in data[0]
        assert 'Actions' in data[0]['by_group']

    def test_historique_group_by_envelope(self, client):
        _make_position(client, date='2024-06-01', owner='Alice', envelope='PEA', value=10000)
        resp = client.get('/api/historique?group_by=envelope')
        data = resp.get_json()
        assert 'PEA' in data[0]['by_group']

    def test_historique_filter_by_owner(self, client):
        _make_position(client, date='2024-06-01', owner='Alice', value=10000)
        _make_position(client, date='2024-06-01', owner='Bob', value=5000,
                       category='Obligations', envelope='CTO')
        resp = client.get('/api/historique?owner=Alice')
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['family_net'] == 10000

    def test_tri_insufficient_data(self, client):
        _make_position(client, date='2024-06-01', owner='Alice', value=10000)
        resp = client.get('/api/tri')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {}  # less than 2 dates

    def test_tri_with_data(self, client):
        _make_position(client, date='2024-01-01', owner='Alice', envelope='PEA', value=10000)
        _make_position(client, date='2025-01-01', owner='Alice', envelope='PEA', value=11000)
        _make_flux(client, date='2024-06-01', owner='Alice', amount=500,
                   envelope='PEA', type='Versement')
        resp = client.get('/api/tri')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'tri' in data
        assert 'first_date' in data
        assert 'date' in data

    def test_snapshot_notes_get_empty(self, client):
        resp = client.get('/api/snapshot-notes?date=2024-06-01')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['notes'] is None

    def test_snapshot_notes_put_and_get(self, client):
        resp = client.put('/api/snapshot-notes', json={
            'date': '2024-06-01', 'notes': 'Bilan semestriel',
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 200
        resp = client.get('/api/snapshot-notes?date=2024-06-01')
        data = resp.get_json()
        assert data['notes'] == 'Bilan semestriel'

    def test_snapshot_notes_delete_by_empty(self, client):
        client.put('/api/snapshot-notes', json={
            'date': '2024-06-01', 'notes': 'To remove',
        }, headers=CSRF_HEADERS)
        client.put('/api/snapshot-notes', json={
            'date': '2024-06-01', 'notes': '',
        }, headers=CSRF_HEADERS)
        resp = client.get('/api/snapshot-notes?date=2024-06-01')
        assert resp.get_json()['notes'] is None

    def test_snapshot_notes_list_all(self, client):
        client.put('/api/snapshot-notes', json={
            'date': '2024-01-01', 'notes': 'Note 1',
        }, headers=CSRF_HEADERS)
        client.put('/api/snapshot-notes', json={
            'date': '2024-06-01', 'notes': 'Note 2',
        }, headers=CSRF_HEADERS)
        resp = client.get('/api/snapshot-notes')
        data = resp.get_json()
        assert data['2024-01-01'] == 'Note 1'
        assert data['2024-06-01'] == 'Note 2'

    def test_snapshot_notes_missing_date(self, client):
        resp = client.put('/api/snapshot-notes', json={
            'notes': 'No date',
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_wealth_target_get_default(self, client):
        resp = client.get('/api/wealth-target')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['target'] is None

    def test_wealth_target_put_and_get(self, client):
        resp = client.put('/api/wealth-target', json={
            'target': 1000000, 'deadline': '2030-01-01',
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 200
        resp = client.get('/api/wealth-target')
        data = resp.get_json()
        assert data['target'] == 1000000
        assert data['deadline'] == '2030-01-01'

    def test_wealth_target_bad_body(self, client):
        resp = client.put('/api/wealth-target',
                          data='not json',
                          content_type='application/json',
                          headers=CSRF_HEADERS)
        assert resp.status_code == 400


# ─── TestTools ───────────────────────────────────────────────────────────────

class TestTools:
    def test_timeline_empty(self, client):
        resp = client.get('/api/timeline')
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_timeline_with_data(self, client):
        _make_position(client, date='2024-06-01')
        _make_flux(client, date='2024-06-15')
        resp = client.get('/api/timeline')
        assert resp.status_code == 200
        events = resp.get_json()
        types = [e['type'] for e in events]
        assert 'snapshot' in types
        assert 'flux' in types

    def test_timeline_includes_notes(self, client):
        _make_position(client, date='2024-06-01')
        client.put('/api/snapshot-notes', json={
            'date': '2024-06-01', 'notes': 'Important note',
        }, headers=CSRF_HEADERS)
        resp = client.get('/api/timeline')
        events = resp.get_json()
        note_events = [e for e in events if e['type'] == 'note']
        assert len(note_events) == 1
        assert note_events[0]['label'] == 'Important note'

    def test_position_history_by_owner(self, client):
        _make_position(client, date='2024-01-01', owner='Alice', value=10000)
        _make_position(client, date='2024-06-01', owner='Alice', value=15000)
        _make_position(client, date='2024-06-01', owner='Bob', value=5000,
                       category='Obligations', envelope='CTO')
        resp = client.get('/api/position-history?owner=Alice')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2

    def test_position_history_no_filter(self, client):
        _make_position(client, date='2024-06-01')
        resp = client.get('/api/position-history')
        assert resp.status_code == 200
        # No filter specified, should return empty
        assert resp.get_json() == []

    def test_simulate_basic(self, client):
        resp = client.post('/api/simulate', json={
            'initial': 10000, 'monthly': 500,
            'annual_rate': 5, 'years': 10,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'points' in data
        assert len(data['points']) == 121  # 10*12 + 1
        assert data['points'][0]['balance'] == 10000
        assert data['final_balance'] > 10000
        assert data['total_invested'] == 10000 + 500 * 120
        assert data['gains'] > 0

    def test_simulate_validation_years(self, client):
        resp = client.post('/api/simulate', json={
            'initial': 10000, 'years': 0,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

        resp = client.post('/api/simulate', json={
            'initial': 10000, 'years': 51,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_simulate_validation_rate(self, client):
        resp = client.post('/api/simulate', json={
            'initial': 10000, 'annual_rate': 101,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

        resp = client.post('/api/simulate', json={
            'initial': 10000, 'annual_rate': -51,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_simulate_validation_initial(self, client):
        resp = client.post('/api/simulate', json={
            'initial': -1,
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_simulate_bad_params(self, client):
        resp = client.post('/api/simulate', json={
            'initial': 'abc',
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_auto_snapshot(self, client):
        _make_position(client, date='2024-01-01', owner='Alice', value=10000)
        _make_position(client, date='2024-01-01', owner='Bob', value=5000,
                       category='Obligations', envelope='CTO')
        resp = client.post('/api/auto-snapshot', json={
            'date': '2024-06-01',
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['positions_copied'] == 2
        assert data['from_date'] == '2024-01-01'
        assert data['to_date'] == '2024-06-01'
        # Verify new positions exist
        resp = client.get('/api/positions?date=2024-06-01')
        assert len(resp.get_json()) == 2

    def test_auto_snapshot_no_existing(self, client):
        resp = client.post('/api/auto-snapshot', json={
            'date': '2024-06-01',
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_auto_snapshot_same_date(self, client):
        _make_position(client, date='2024-06-01')
        resp = client.post('/api/auto-snapshot', json={
            'date': '2024-06-01',
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('skipped') is True

    def test_auto_snapshot_target_exists(self, client):
        _make_position(client, date='2024-01-01')
        _make_position(client, date='2024-06-01')
        resp = client.post('/api/auto-snapshot', json={
            'date': '2024-06-01',
        }, headers=CSRF_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('skipped') is True


# ─── TestImportExport ────────────────────────────────────────────────────────

class TestImportExport:
    def test_export_empty(self, client):
        resp = client.get('/api/export')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['positions'] == []
        assert data['flux'] == []
        assert data['entities'] == []
        assert data['entity_snapshots'] == []
        assert data['snapshot_notes'] == {}

    def test_export_with_data(self, client):
        _make_position(client, date='2024-06-01')
        _make_flux(client, date='2024-06-01')
        _make_entity(client)
        resp = client.get('/api/export')
        data = resp.get_json()
        assert len(data['positions']) == 1
        assert len(data['flux']) == 1
        assert len(data['entities']) == 1
        assert len(data['entity_snapshots']) >= 1

    def test_import_json_valid(self, client):
        payload = {
            'positions': [{
                'date': '2024-06-01', 'owner': 'Alice', 'category': 'Actions',
                'envelope': 'PEA', 'value': 10000, 'debt': 0,
            }],
            'flux': [{
                'date': '2024-06-01', 'owner': 'Alice', 'amount': 1000,
                'type': 'Versement',
            }],
            'entities': [{
                'name': 'SCI Import', 'gross_assets': 200000, 'debt': 50000,
            }],
            'entity_snapshots': [{
                'entity_name': 'SCI Import', 'date': '2024-06-01',
                'gross_assets': 200000, 'debt': 50000,
            }],
            'snapshot_notes': {
                '2024-06-01': 'Imported note',
            },
        }
        resp = client.post('/api/import-json', json=payload, headers=CSRF_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['positions'] == 1
        assert data['flux'] == 1
        assert data['entities'] == 1
        assert data['entity_snapshots'] == 1

    def test_import_json_bad_data(self, client):
        payload = {
            'positions': [{
                'date': 'bad-date', 'owner': 'Alice',
            }],
        }
        resp = client.post('/api/import-json', json=payload, headers=CSRF_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['skipped'] == 1
        assert data['positions'] == 0

    def test_import_json_empty_body(self, client):
        resp = client.post('/api/import-json',
                           data='',
                           content_type='application/json',
                           headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_import_json_not_object(self, client):
        resp = client.post('/api/import-json', json=[1, 2, 3], headers=CSRF_HEADERS)
        assert resp.status_code == 400

    def test_import_json_dedup(self, client):
        """Importing the same position twice should not duplicate."""
        payload = {
            'positions': [{
                'date': '2024-06-01', 'owner': 'Alice', 'category': 'Actions',
                'envelope': 'PEA', 'value': 10000, 'debt': 0,
            }],
        }
        client.post('/api/import-json', json=payload, headers=CSRF_HEADERS)
        resp = client.post('/api/import-json', json=payload, headers=CSRF_HEADERS)
        data = resp.get_json()
        assert data['positions'] == 0  # already exists

    def test_export_import_roundtrip(self, client):
        _make_position(client, date='2024-06-01', owner='Alice', value=10000)
        _make_flux(client, date='2024-06-01', owner='Alice', amount=500)
        _make_entity(client, name='SCI RT')
        # Export
        export_resp = client.get('/api/export')
        exported = export_resp.get_json()
        # Reset
        client.post('/api/reset', headers=CSRF_HEADERS)
        # Verify empty
        assert client.get('/api/export').get_json()['positions'] == []
        # Re-import
        resp = client.post('/api/import-json', json=exported, headers=CSRF_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['positions'] == 1
        assert data['entities'] == 1

    def test_reset_db(self, client):
        _make_position(client)
        _make_flux(client)
        _make_entity(client)
        resp = client.post('/api/reset', headers=CSRF_HEADERS)
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True
        # Verify everything is gone
        assert client.get('/api/positions').get_json() == []
        assert client.get('/api/flux').get_json() == []
        assert client.get('/api/entities').get_json() == []


# ─── TestMigrations ──────────────────────────────────────────────────────────

class TestMigrations:
    def test_init_db_idempotent(self, client):
        """Calling init_db twice should not crash."""
        init_db()
        init_db()
        # DB should still work
        resp = client.get('/api/positions')
        assert resp.status_code == 200
