"""Integration tests for advisor phase 7 : macro, proposals, usage."""

import os
import pytest

# Mock LLM provider et price provider — aucun appel reseau dans les tests
os.environ['PRICE_PROVIDER'] = 'mock'
os.environ['ADVISOR_LLM_PROVIDER'] = 'mock'

from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa


def _setup_owner_with_positions(client):
    client.put('/api/advisor/profiles/Personne 1', json={
        'horizon_years': 20, 'risk_tolerance': 5,
        'employment_type': 'TNS', 'has_lbo': True,
    }, headers=CSRF_HEADERS)
    _make_position(client, owner='Personne 1', category='Actions', envelope='PEA', value=30000)
    _make_position(client, owner='Personne 1', category='Cash', envelope='Livret A', value=10000)
    _make_position(client, owner='Personne 1', category='Immobilier', envelope='Immobilier', value=60000)


# ─── LLM wrapper ─────────────────────────────────────────────────────────────

class TestLLMWrapper:
    def test_mock_mode_active_in_tests(self):
        from services.advisor.llm import is_mock_mode, is_available
        assert is_mock_mode() is True
        assert is_available() is True

    def test_compute_cost(self):
        from services.advisor.llm import compute_cost
        # 10K input + 5K output sur sonnet-4-6
        cost = compute_cost('claude-sonnet-4-6', input_tokens=10000, output_tokens=5000)
        # 10000 * 3 / 1M + 5000 * 15 / 1M = 0.03 + 0.075 = 0.105
        assert cost == 0.105

    def test_messages_create_mock(self, client):
        from models import get_db
        from services.advisor.llm import messages_create
        with get_db() as conn:
            res = messages_create(
                conn, endpoint='test.mock',
                system_blocks=[{'type': 'text', 'text': 'system'}],
                user_message='hello',
                json_response=True,
            )
        assert res['model'].endswith('(mock)')
        assert res['cost_usd'] == 0
        assert res['json'] is not None


# ─── Macro snapshot ──────────────────────────────────────────────────────────

class TestMacro:
    def test_latest_empty_initially(self, client):
        r = client.get('/api/advisor/macro/latest')
        assert r.status_code == 200
        assert r.get_json()['snapshot'] is None
        assert r.get_json()['llm_available'] is True
        assert r.get_json()['llm_mock'] is True

    def test_refresh_creates_snapshot(self, client):
        r = client.post('/api/advisor/macro/refresh', headers=CSRF_HEADERS)
        assert r.status_code == 201
        snap = r.get_json()['snapshot']
        assert snap['source'] == 'llm'
        assert snap['regime_rates'] in {'bas', 'neutre', 'haut'}

    def test_patch_marks_as_manual(self, client):
        r = client.post('/api/advisor/macro/refresh', headers=CSRF_HEADERS)
        snap_id = r.get_json()['snapshot']['id']
        r = client.patch(f'/api/advisor/macro/{snap_id}',
                         json={'regime_rates': 'haut'}, headers=CSRF_HEADERS)
        assert r.status_code == 200
        assert r.get_json()['regime_rates'] == 'haut'
        assert r.get_json()['source'] == 'manual'

    def test_patch_rejects_invalid_value(self, client):
        r = client.post('/api/advisor/macro/refresh', headers=CSRF_HEADERS)
        snap_id = r.get_json()['snapshot']['id']
        r = client.patch(f'/api/advisor/macro/{snap_id}',
                         json={'regime_rates': 'extreme'}, headers=CSRF_HEADERS)
        assert r.status_code == 400


# ─── Rebalance engine ────────────────────────────────────────────────────────

class TestRebalanceEngine:
    def test_bucket_proposals_from_gap(self):
        from services.advisor.rebalance import generate_proposals
        profile = {'horizon_years': 20, 'risk_tolerance': 5}
        positions = [
            {'category': 'Actions', 'envelope': 'PEA', 'net_attributed': 30000, 'value': 30000},
            {'category': 'Cash & dépôts', 'envelope': '', 'net_attributed': 60000, 'value': 60000},
        ]
        # Forcer un gap : Actions sous-ponderee, Cash surponderee (arbitrable)
        allocation = {
            'gap': [
                {'category': 'Actions',        'delta_eur':  20000, 'delta_pct': 0.2, 'target_pct': 0.7, 'actual_pct': 0.5},
                {'category': 'Cash & dépôts',  'delta_eur': -20000, 'delta_pct': -0.2, 'target_pct': 0.2, 'actual_pct': 0.4},
            ],
            'target': {}, 'actual': {}, 'total_eur': 100000,
        }
        props = generate_proposals(profile, positions, allocation)
        bucket = [p for p in props if p['kind'] == 'bucket']
        assert any('Cash' in p['from_ref'] for p in bucket)
        assert any('Actions' in p['to_ref'] for p in bucket)

    def test_non_arbitrable_excluded(self):
        """Immobilier, Objets de valeur, etc. ne genere pas de bucket proposals."""
        from services.advisor.rebalance import generate_proposals
        profile = {'horizon_years': 20, 'risk_tolerance': 5}
        positions = []
        allocation = {
            'gap': [
                {'category': 'Immobilier',        'delta_eur': -50000},
                {'category': 'Objets de valeur',  'delta_eur': -30000},
                {'category': 'Actions',            'delta_eur':  80000},
            ],
            'target': {}, 'actual': {}, 'total_eur': 200000,
        }
        props = generate_proposals(profile, positions, allocation)
        bucket = [p for p in props if p['kind'] == 'bucket']
        assert not bucket  # rien a arbitrer (pas de source arbitrable)

    def test_fiscal_pea_room(self):
        from services.advisor.rebalance import generate_proposals
        positions = [
            {'category': 'Actions', 'envelope': 'PEA', 'net_attributed': 30000, 'value': 30000},
        ]
        allocation = {'gap': [], 'target': {}, 'actual': {}, 'total_eur': 30000}
        props = generate_proposals({'horizon_years': 10}, positions, allocation)
        assert any(p['kind'] == 'fiscal' and 'PEA' in p['label'] for p in props)

    def test_tns_proposal(self):
        from services.advisor.rebalance import generate_proposals
        positions = [{'category': 'Actions', 'envelope': 'PEA', 'net_attributed': 30000, 'value': 30000}]
        allocation = {'gap': [], 'target': {}, 'actual': {}, 'total_eur': 30000}
        props_salarie = generate_proposals({'employment_type': 'salarie'}, positions, allocation)
        props_tns     = generate_proposals({'employment_type': 'TNS'}, positions, allocation)
        assert not any('PER' in p['label'] for p in props_salarie)
        assert any('PER' in p['label'] for p in props_tns)


# ─── Proposals route ─────────────────────────────────────────────────────────

class TestProposalsRoute:
    def test_refresh_and_list(self, client):
        _setup_owner_with_positions(client)
        r = client.post('/api/advisor/profiles/Personne 1/proposals/refresh',
                        headers=CSRF_HEADERS)
        assert r.status_code == 200
        assert r.get_json()['count'] >= 1

        r = client.get('/api/advisor/profiles/Personne 1/proposals?status=pending')
        proposals = r.get_json()
        assert len(proposals) >= 1
        assert all(p['status'] == 'pending' for p in proposals)

    def test_apply_and_dismiss(self, client):
        _setup_owner_with_positions(client)
        client.post('/api/advisor/profiles/Personne 1/proposals/refresh',
                    headers=CSRF_HEADERS)
        r = client.get('/api/advisor/profiles/Personne 1/proposals?status=pending')
        proposals = r.get_json()
        assert len(proposals) >= 1
        first = proposals[0]['id']
        second = proposals[1]['id'] if len(proposals) > 1 else None

        r = client.patch(f'/api/advisor/proposals/{first}',
                         json={'status': 'applied'}, headers=CSRF_HEADERS)
        assert r.get_json()['status'] == 'applied'

        if second:
            r = client.patch(f'/api/advisor/proposals/{second}',
                             json={'status': 'dismissed'}, headers=CSRF_HEADERS)
            assert r.get_json()['status'] == 'dismissed'

    def test_refresh_requires_profile(self, client):
        r = client.post('/api/advisor/profiles/Personne 1/proposals/refresh',
                        headers=CSRF_HEADERS)
        assert r.status_code == 404

    def test_refresh_requires_positions(self, client):
        client.put('/api/advisor/profiles/Personne 1', json={'risk_tolerance': 3},
                   headers=CSRF_HEADERS)
        r = client.post('/api/advisor/profiles/Personne 1/proposals/refresh',
                        headers=CSRF_HEADERS)
        assert r.status_code == 400

    def test_patch_rejects_invalid_status(self, client):
        _setup_owner_with_positions(client)
        client.post('/api/advisor/profiles/Personne 1/proposals/refresh',
                    headers=CSRF_HEADERS)
        r = client.get('/api/advisor/profiles/Personne 1/proposals?status=pending')
        pid = r.get_json()[0]['id']
        r = client.patch(f'/api/advisor/proposals/{pid}',
                         json={'status': 'unknown'}, headers=CSRF_HEADERS)
        assert r.status_code == 400


# ─── Usage endpoint ──────────────────────────────────────────────────────────

class TestUsage:
    def test_usage_initially_empty(self, client):
        r = client.get('/api/advisor/usage')
        assert r.status_code == 200
        data = r.get_json()
        assert data['month_total_usd'] == 0
        assert data['mock_mode'] is True

    def test_usage_includes_budget(self, client):
        os.environ['ADVISOR_BUDGET_USD'] = '5'
        try:
            r = client.get('/api/advisor/usage')
            assert r.get_json()['budget_usd'] == 5.0
        finally:
            os.environ.pop('ADVISOR_BUDGET_USD', None)
