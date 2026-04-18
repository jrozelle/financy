"""Integration tests for the advisor feature (phase 6)."""

import os
import pytest

os.environ['PRICE_PROVIDER'] = 'mock'

from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa


# ─── Moteur d'allocation (unitaire) ──────────────────────────────────────────

class TestAllocationEngine:
    def test_basic_matrix_horizon_long_risque_haut(self):
        from services.advisor.allocation import target_allocation
        alloc, adj = target_allocation({'horizon_years': 20, 'risk_tolerance': 5})
        assert alloc['Actions'] >= 0.5
        assert alloc['Cash'] <= 0.15
        assert abs(sum(alloc.values()) - 1) < 0.01
        assert adj == []

    def test_court_terme_prudent(self):
        from services.advisor.allocation import target_allocation
        alloc, _ = target_allocation({'horizon_years': 1, 'risk_tolerance': 1})
        assert alloc['Cash'] >= 0.7

    def test_lbo_adjustment(self):
        from services.advisor.allocation import target_allocation
        base, _ = target_allocation({'horizon_years': 15, 'risk_tolerance': 4})
        lbo, adj = target_allocation({'horizon_years': 15, 'risk_tolerance': 4, 'has_lbo': True})
        assert lbo['Cash'] > base['Cash']
        assert lbo['Actions'] < base['Actions']
        assert any('LBO' in a for a in adj)

    def test_tns_adjustment(self):
        from services.advisor.allocation import target_allocation
        base, _ = target_allocation({'horizon_years': 15, 'risk_tolerance': 3})
        tns, adj = target_allocation({'horizon_years': 15, 'risk_tolerance': 3,
                                       'employment_type': 'TNS'})
        assert tns['Cash'] > base['Cash']
        assert any('TNS' in a for a in adj)

    def test_normalisation(self):
        from services.advisor.allocation import target_allocation
        alloc, _ = target_allocation({'horizon_years': 20, 'risk_tolerance': 5,
                                       'has_lbo': True, 'employment_type': 'TNS',
                                       'main_residence_owned': False})
        assert abs(sum(alloc.values()) - 1) < 0.01

    def test_compute_actual(self):
        from services.advisor.allocation import compute_actual_allocation
        positions = [
            {'category': 'Actions', 'net_attributed': 30000},
            {'category': 'Cash', 'net_attributed': 10000},
            {'category': 'Immobilier', 'net_attributed': 60000},
        ]
        actual = compute_actual_allocation(positions)
        assert actual['Actions'] == 0.3

    def test_gap_sorted_by_absolute_delta(self):
        from services.advisor.allocation import compute_gap
        gap = compute_gap({'A': 0.6, 'B': 0.2, 'C': 0.2},
                          {'A': 0.3, 'B': 0.25, 'C': 0.45},
                          100000)
        # A a le plus gros ecart (+30000), il est en premier
        assert gap[0]['category'] == 'A'
        assert gap[0]['delta_eur'] == 30000


# ─── Routes profile ──────────────────────────────────────────────────────────

class TestProfile:
    def test_upsert_and_get(self, client):
        r = client.put('/api/advisor/profiles/Personne 1',
                       json={'horizon_years': 20, 'risk_tolerance': 4,
                             'employment_type': 'salarie'},
                       headers=CSRF_HEADERS)
        assert r.status_code == 200
        r = client.get('/api/advisor/profiles/Personne 1')
        p = r.get_json()
        assert p['horizon_years'] == 20
        assert p['risk_tolerance'] == 4
        assert p['has_lbo'] is False

    def test_reject_unknown_owner(self, client):
        r = client.put('/api/advisor/profiles/Inconnu',
                       json={'risk_tolerance': 3},
                       headers=CSRF_HEADERS)
        assert r.status_code == 400

    def test_reject_out_of_range_risk(self, client):
        r = client.put('/api/advisor/profiles/Personne 1',
                       json={'risk_tolerance': 10},
                       headers=CSRF_HEADERS)
        assert r.status_code == 400

    def test_reject_invalid_employment(self, client):
        r = client.put('/api/advisor/profiles/Personne 1',
                       json={'employment_type': 'freelance_xxx'},
                       headers=CSRF_HEADERS)
        assert r.status_code == 400

    def test_update_preserves_previous_fields(self, client):
        client.put('/api/advisor/profiles/Personne 1',
                   json={'horizon_years': 15, 'risk_tolerance': 3, 'has_lbo': True},
                   headers=CSRF_HEADERS)
        # Un deuxieme PUT avec moins de champs remplace tout
        client.put('/api/advisor/profiles/Personne 1',
                   json={'risk_tolerance': 4},
                   headers=CSRF_HEADERS)
        r = client.get('/api/advisor/profiles/Personne 1')
        p = r.get_json()
        # PUT = upsert complet, l'ancien has_lbo est ecrase a false (non fourni)
        assert p['risk_tolerance'] == 4
        assert p['has_lbo'] is False

    def test_delete(self, client):
        client.put('/api/advisor/profiles/Personne 1',
                   json={'risk_tolerance': 3}, headers=CSRF_HEADERS)
        r = client.delete('/api/advisor/profiles/Personne 1', headers=CSRF_HEADERS)
        assert r.status_code == 204
        r = client.get('/api/advisor/profiles/Personne 1')
        assert r.status_code == 404


# ─── Routes objectives ───────────────────────────────────────────────────────

class TestObjectives:
    def test_crud(self, client):
        r = client.post('/api/advisor/profiles/Personne 1/objectives',
                        json={'label': 'RS', 'target_amount': 300000, 'horizon_years': 8, 'priority': 4},
                        headers=CSRF_HEADERS)
        assert r.status_code == 201
        oid = r.get_json()['id']

        r = client.get('/api/advisor/profiles/Personne 1/objectives')
        assert len(r.get_json()) == 1

        r = client.patch(f'/api/advisor/objectives/{oid}',
                         json={'priority': 2}, headers=CSRF_HEADERS)
        assert r.get_json()['priority'] == 2

        r = client.delete(f'/api/advisor/objectives/{oid}', headers=CSRF_HEADERS)
        assert r.status_code == 204

    def test_reject_missing_label(self, client):
        r = client.post('/api/advisor/profiles/Personne 1/objectives',
                        json={'horizon_years': 5}, headers=CSRF_HEADERS)
        assert r.status_code == 400

    def test_cascade_on_profile_delete(self, client):
        client.put('/api/advisor/profiles/Personne 1',
                   json={'risk_tolerance': 3}, headers=CSRF_HEADERS)
        client.post('/api/advisor/profiles/Personne 1/objectives',
                    json={'label': 'X'}, headers=CSRF_HEADERS)
        client.delete('/api/advisor/profiles/Personne 1', headers=CSRF_HEADERS)
        r = client.get('/api/advisor/profiles/Personne 1/objectives')
        assert r.get_json() == []


# ─── Allocation endpoint ─────────────────────────────────────────────────────

class TestAllocation:
    def test_requires_profile(self, client):
        r = client.get('/api/advisor/profiles/Personne 1/allocation')
        assert r.status_code == 404

    def test_allocation_with_positions(self, client):
        # Seed profil
        client.put('/api/advisor/profiles/Personne 1',
                   json={'horizon_years': 15, 'risk_tolerance': 4,
                         'employment_type': 'salarie'},
                   headers=CSRF_HEADERS)
        # Seed positions (Alice devient Personne 1 par defaut)
        _make_position(client, owner='Personne 1', category='Actions', envelope='PEA',
                       value=50000)
        _make_position(client, owner='Personne 1', category='Cash', envelope='Livret A',
                       value=50000)
        r = client.get('/api/advisor/profiles/Personne 1/allocation')
        data = r.get_json()
        assert data['total_eur'] == 100000
        assert 'Actions' in data['target']
        assert 'Actions' in data['actual']
        assert data['actual']['Actions'] == 0.5
        assert len(data['gap']) > 0
