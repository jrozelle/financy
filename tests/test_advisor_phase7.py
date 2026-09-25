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

    def _gap_liquidites(self):
        # 40 000 € de liquidites pour une cible de 20 000 € : 20 000 d'excedent.
        return {
            'gap': [
                {'category': 'Actions',       'delta_eur':  20000, 'target_pct': 0.7, 'actual_pct': 0.5},
                {'category': 'Cash & dépôts', 'delta_eur': -20000, 'target_pct': 0.2, 'actual_pct': 0.4},
            ],
            'target': {}, 'actual': {}, 'total_eur': 100000,
        }

    def test_la_reserve_libre_n_est_plus_lue(self):
        """La cible de precaution (charges x mois) a remplace la reserve libre :
        une valeur restee en base ne garde plus rien."""
        from services.advisor.rebalance import generate_proposals
        props = generate_proposals({'reserve_eur': 35000}, [], self._gap_liquidites())
        bucket = [p for p in props if p['kind'] == 'bucket']
        assert bucket and bucket[0]['amount'] == pytest.approx(20000)
        assert 'Réserve déclarée' not in bucket[0]['rationale']

    def test_sans_reserve_la_proposition_le_dit(self):
        from services.advisor.rebalance import generate_proposals
        props = generate_proposals({}, [], self._gap_liquidites())
        bucket = [p for p in props if p['kind'] == 'bucket']
        assert bucket[0]['amount'] == pytest.approx(20000)
        assert 'Aucune réserve' in bucket[0]['rationale']

    def test_plafond_pea_sur_les_versements(self):
        """80 000 € verses devenus 120 000 € : la marge est de 70 000, pas 30 000."""
        from services.advisor.rebalance import generate_proposals
        positions = [{'category': 'Actions', 'envelope': 'PEA', 'value': 120000, 'net_attributed': 120000}]
        props = generate_proposals({}, positions, {'gap': [], 'total_eur': 120000}, versements_pea=80000)
        pea = [p for p in props if p['to_ref'] == 'PEA']
        assert pea[0]['amount'] == pytest.approx(70000)
        assert 'versements enregistrés' in pea[0]['rationale']

    def test_plafond_pea_estime_sur_la_valeur_le_dit(self):
        from services.advisor.rebalance import generate_proposals
        positions = [{'category': 'Actions', 'envelope': 'PEA', 'value': 120000, 'net_attributed': 120000}]
        props = generate_proposals({}, positions, {'gap': [], 'total_eur': 120000})
        pea = [p for p in props if p['to_ref'] == 'PEA']
        assert 'estimation' in pea[0]['rationale']

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

    def test_pas_de_conseil_generique(self):
        """Un « verifiez » sans chiffre n'est pas une proposition : ni le PER
        du TNS, ni l'anciennete des AV, ni un CTO sans moins-value."""
        from services.advisor.rebalance import generate_proposals
        positions = [{'category': 'Actions', 'envelope': 'CTO', 'value': 5000, 'net_attributed': 5000,
                      'holdings_detail': [{'isin': 'X', 'name': 'Gagnant', 'market_value': 5000,
                                           'cost_basis': 4000}]},
                     {'category': 'Fond Euro', 'envelope': 'Assurance-vie', 'value': 9000, 'net_attributed': 9000}]
        allocation = {'gap': [], 'total_eur': 14000}
        assert generate_proposals({'employment_type': 'TNS'}, positions, allocation) == []

    def test_moins_values_du_cto_chiffrees(self):
        from services.advisor.rebalance import generate_proposals
        positions = [{'category': 'Actions', 'envelope': 'CTO', 'value': 1700, 'net_attributed': 1700,
                      'holdings_detail': [
                          {'isin': 'A', 'name': 'Perdant', 'market_value': 700, 'cost_basis': 1000},
                          {'isin': 'B', 'name': 'Gagnant', 'market_value': 1000, 'cost_basis': 500}]}]
        props = generate_proposals({}, positions, {'gap': [], 'total_eur': 1700})
        assert len(props) == 1 and props[0]['amount'] == pytest.approx(300)
        assert 'Perdant' in props[0]['rationale'] and 'Gagnant' not in props[0]['rationale']


class TestPerimetreFinancier:
    """La cible s'applique au patrimoine financier, et seule sa part libre
    peut bouger."""

    def _p(self, cat, env, net, liquidity='J0–J1', mob=None, **kw):
        return {'category': cat, 'envelope': env, 'net_attributed': net, 'value': net,
                'liquidity': liquidity, 'mobilizable_value': net if mob is None else mob, **kw}

    def _profil(self):
        return {'horizon_years': 20, 'risk_tolerance': 4}

    def test_immobilier_et_objets_hors_calcul_mais_decomptes(self):
        from services.advisor.allocation import allocation_financiere
        a = allocation_financiere(self._profil(), [
            self._p('Actions', 'PEA', 60000), self._p('Immobilier', 'Immobilier', 300000, 'Bloqué', 0),
            self._p('Objets de valeur', 'Biens', 20000, 'Bloqué', 0)])
        assert a['total_eur'] == 60000
        assert {e['category'] for e in a['exclus']} == {'Immobilier', 'Objets de valeur'}
        assert 'Immobilier' not in a['target']
        assert sum(a['target'].values()) == pytest.approx(1, abs=1e-3)

    def test_les_categories_rangees_dans_les_classes(self):
        from services.advisor.allocation import allocation_financiere
        a = allocation_financiere(self._profil(), [
            self._p('Fond Euro', 'Assurance-vie', 10000), self._p('Cash & dépôts', 'Livret A', 10000),
            self._p('Produits Structurés', 'Assurance-vie', 10000), self._p('Crypto', 'Crypto', 10000)])
        classes = {g['category']: g['actual_eur'] for g in a['gap']}
        # Le Livret A est garde en precaution, hors du calcul, et decompte.
        assert classes == {'Fonds euros et obligations': 10000, 'Actions': 20000}
        assert {'category': 'Épargne de précaution', 'montant': 10000} in a['exclus']

    def test_le_bloque_compte_mais_ne_bouge_pas(self):
        """Un fonds euros nanti pese dans l'exposition ; seul le libre est propose."""
        from services.advisor.allocation import allocation_financiere
        from services.advisor.rebalance import generate_proposals
        positions = [self._p('Fond Euro', 'Assurance-vie', 80000, 'Bloqué', 0, label='AV nantie'),
                     self._p('Fond Euro', 'Assurance-vie', 10000, mob=9500, label='AV libre'),
                     self._p('Actions', 'PEA', 10000)]
        a = allocation_financiere(self._profil(), positions)
        oblig = next(g for g in a['gap'] if g['category'] == 'Fonds euros et obligations')
        assert oblig['composition'] == {'Fonds euros': 90000}
        assert oblig['bloque_eur'] == pytest.approx(80000) and oblig['libre_eur'] == pytest.approx(9500)
        bucket = [p for p in generate_proposals(self._profil(), positions, a) if p['kind'] == 'bucket']
        assert bucket and bucket[0]['amount'] == pytest.approx(9500)
        assert 'AV nantie' in bucket[0]['rationale'] and 'AV libre' in bucket[0]['rationale']

    def test_sans_reserve_les_livrets_reglementes_sont_gardes(self):
        from services.advisor.allocation import allocation_financiere
        from services.advisor.rebalance import generate_proposals
        positions = [self._p('Cash & dépôts', 'Livret A', 22950), self._p('Cash & dépôts', 'Livret Bourso+', 50000),
                     self._p('Actions', 'PEA', 10000)]
        a = allocation_financiere(self._profil(), positions)
        # Le Livret A reste entier en precaution, hors du calcul : seul le
        # livret bancaire est arbitrable, et la note dit ce qui est garde.
        cash = next(g for g in a['gap'] if g['category'] == 'Cash')
        assert cash['actual_eur'] == 50000
        assert {'category': 'Épargne de précaution', 'montant': 22950} in a['exclus']
        bucket = [p for p in generate_proposals(self._profil(), positions, a) if p['kind'] == 'bucket']
        assert bucket and 'Épargne de précaution gardée à part' in bucket[0]['rationale']
        assert 'Livret A' in bucket[0]['rationale']


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


class TestPropositionsPerimees:
    def test_la_generation_purge_les_attentes_des_arretes_anterieurs(self, client):
        from models import get_db
        from services.advisor.rebalance import replace_proposals, list_proposals
        p = {'kind': 'bucket', 'label': 'x', 'from_ref': None, 'to_ref': None, 'amount': 1,
             'rationale': '', 'status': 'pending'}
        with get_db() as conn:
            replace_proposals(conn, 'Personne 1', '2026-01-01', [p, p])
            garde = conn.execute("SELECT id FROM rebalance_proposals LIMIT 1").fetchone()['id']
            conn.execute("UPDATE rebalance_proposals SET status='applied' WHERE id=?", (garde,))
            replace_proposals(conn, 'Personne 1', '2026-02-01', [p])
            rows = list_proposals(conn, 'Personne 1')
        assert sorted((r['snapshot_date'], r['status']) for r in rows) == [
            ('2026-01-01', 'applied'), ('2026-02-01', 'pending')]
