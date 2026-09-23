"""Revue B2 : saisies invalides refusees en 400 (et non 500), simulation,
frise des flux signes, jeton CSRF, signaux de cours, job planifie hors demo."""
import os
from datetime import datetime

import pytest

os.environ['PRICE_PROVIDER'] = 'mock'

from tests.test_api import client, anon_client, fresh_db, CSRF_HEADERS, _make_position  # noqa: E402,F401

import models  # noqa: E402
from models import get_db  # noqa: E402
from services.montants import centimes  # noqa: E402

H = CSRF_HEADERS


def _pos(**kw):
    p = {'date': '2026-06-30', 'owner': 'Paul', 'category': 'Actions', 'envelope': 'PEA',
         'value': 1000, 'debt': 0}
    p.update(kw)
    return p


class TestPositions:
    @pytest.mark.parametrize('champs', [
        {'owner': ''}, {'owner': None}, {'category': ''}, {'owner': 'x' * 101},
        {'label': 'x' * 201}, {'establishment': 5}, {'value': 'abc'},
        {'mobilizable_pct_override': 1.5}, {'mobilizable_pct_override': 'beaucoup'},
        {'liquidity_override': 'Demain'},
    ])
    def test_post_et_put_refusent(self, client, champs):
        assert client.post('/api/positions', json=_pos(**champs), headers=H).status_code == 400
        pid = client.post('/api/positions', json=_pos(), headers=H).get_json()['id']
        assert client.put(f'/api/positions/{pid}', json=_pos(**champs), headers=H).status_code == 400

    def test_surcharges_valides_enregistrees(self, client):
        r = client.post('/api/positions', json=_pos(mobilizable_pct_override='0,5', liquidity_override='J2–J7'),
                        headers=H)
        assert r.status_code == 201
        assert r.get_json()['mobilizable_pct_override'] == 0.5

    def test_put_position_absente(self, client):
        assert client.put('/api/positions/999', json=_pos(), headers=H).status_code == 404

    def test_corps_absent(self, client):
        assert client.put('/api/positions/1', data='x', content_type='application/json',
                          headers=H).status_code == 400
        assert client.post('/api/positions/1/snapshot-update', data='x', content_type='application/json',
                           headers=H).status_code == 400
        assert client.post('/api/positions/1/snapshot-update', json={
            'source_date': '2026-06-30', 'target_date': '2026-07-01', 'position': 'x'}, headers=H).status_code == 400

    def test_snapshot_update_valide_la_position(self, client):
        pid = client.post('/api/positions', json=_pos(), headers=H).get_json()['id']
        r = client.post(f'/api/positions/{pid}/snapshot-update', headers=H, json={
            'source_date': '2026-06-30', 'target_date': '2026-07-01',
            'position': _pos(liquidity_override='Demain')})
        assert r.status_code == 400


class TestSynthese:
    def test_note_validee(self, client):
        put = lambda d: client.put('/api/snapshot-notes', json=d, headers=H).status_code
        assert put({'date': 'hier', 'notes': 'x'}) == 400
        assert put({'date': '2026-06-30', 'notes': 'x' * 2001}) == 400
        assert put({'date': '2026-06-30', 'notes': ['x']}) == 400
        assert put({'date': '2026-06-30', 'notes': 'Arrêté de fin juin'}) == 200
        assert client.put('/api/snapshot-notes', data='x', content_type='application/json',
                          headers=H).status_code == 400

    @pytest.mark.parametrize('corps', [{'target': -5}, {'target': 'abc'}, {'target': True},
                                       {'target': 1000, 'deadline': 'bientot'}])
    def test_objectif_invalide(self, client, corps):
        assert client.put('/api/wealth-target', json=corps, headers=H).status_code == 400

    def test_objectif_ne_garde_que_ses_champs(self, client):
        assert client.put('/api/wealth-target', json={'target': '1 000 000', 'autre': 'x'},
                          headers=H).status_code == 200
        assert client.get('/api/wealth-target').get_json() == {'target': 1000000}
        assert client.put('/api/wealth-target', json={'target': None}, headers=H).status_code == 200


class TestReferentiel:
    @pytest.mark.parametrize('corps', [{'Actions': 150}, {'Actions': 'abc'}, {'Actions': -1}])
    def test_cibles_invalides(self, client, corps):
        assert client.put('/api/targets', json=corps, headers=H).status_code == 400

    def test_cibles_valides(self, client):
        assert client.put('/api/targets', json={'Actions': '60', 'Obligations': 40}, headers=H).status_code == 200
        assert client.get('/api/targets').get_json() == {'Actions': 60, 'Obligations': 40}

    @pytest.mark.parametrize('corps', [['x'], [{'op': '=='}], [{'threshold': 'beaucoup'}],
                                       [{'label': 'x' * 201}], [{}] * 101])
    def test_alertes_invalides(self, client, corps):
        assert client.put('/api/alerts', json=corps, headers=H).status_code == 400

    def test_alertes_valides(self, client):
        a = [{'label': 'Trop de cash', 'metric': 'cat_pct', 'category': 'Cash & dépôts', 'op': '>', 'threshold': 20}]
        assert client.put('/api/alerts', json=a, headers=H).status_code == 200

    @pytest.mark.parametrize('corps', [
        None, ['x'],
        {'owners': 'Paul', 'categories': [], 'category_mobilizable': {}, 'envelope_meta': {}},
        {'owners': ['Paul', 3], 'categories': [], 'category_mobilizable': {}, 'envelope_meta': {}},
        {'owners': ['Paul'], 'categories': [], 'category_mobilizable': [], 'envelope_meta': {}},
    ])
    def test_referentiel_invalide(self, client, corps):
        kw = {'json': corps} if corps is not None else {'data': 'x', 'content_type': 'application/json'}
        assert client.put('/api/referential', headers=H, **kw).status_code == 400


class TestOutils:
    @pytest.mark.parametrize('champ', ['initial', 'monthly', 'annual_rate', 'years'])
    def test_simulation_refuse_nan_et_inf(self, client, champ):
        for v in ('nan', 'inf', '-inf', 'abc'):
            assert client.post('/api/simulate', json={champ: v}, headers=H).status_code == 400

    def test_simulation_au_format_francais(self, client):
        r = client.post('/api/simulate', json={'initial': '1 000,50', 'years': '2'}, headers=H)
        assert r.status_code == 200

    def test_frise_des_flux_signes(self, client):
        with get_db() as conn:
            for t, a in (('Versement', 1000), ('Retrait', 300), ('Dividende/Intérêt', 50), ('Frais', 20)):
                conn.execute("INSERT INTO flux (date, owner, envelope, type, amount) VALUES ('2026-03-10', 'Paul', 'PEA', ?, ?)",
                             (t, centimes(a)))
        (f,) = [e for e in client.get('/api/timeline').get_json() if e['type'] == 'flux']
        assert f['value'] == 700 and f['label'] == '4 flux'


class TestCsrf:
    def test_jeton_faux_ou_absent(self, client):
        assert client.post('/api/simulate', json={}, headers={'X-CSRF-Token': 'tesT'}).status_code == 403
        assert client.post('/api/simulate', json={}).status_code == 403
        assert client.post('/api/simulate', json={}, headers=H).status_code == 200

    def test_session_sans_jeton(self, anon_client):
        with anon_client.session_transaction() as s:
            s['authenticated'] = True
        assert anon_client.post('/api/simulate', json={}, headers={'X-CSRF-Token': 'x'}).status_code == 403


class TestCoursPerimes:
    def test_seuls_les_titres_du_dernier_arrete(self):
        from services.todo import collect
        with get_db() as conn:
            conn.execute("INSERT INTO securities (isin, name, last_price, last_price_date, is_priceable) "
                         "VALUES ('FR0010315770', 'Vendu', 10, '2026-01-02', 1)")
            ancien = conn.execute("INSERT INTO positions (date, owner, category, value) "
                                  "VALUES ('2026-01-31', 'Paul', 'Actions', 0)").lastrowid
            conn.execute("INSERT INTO positions (date, owner, category, value) VALUES ('2026-06-30', 'Paul', 'Actions', 0)")
            conn.execute("INSERT INTO holdings (position_id, isin, quantity) VALUES (?, 'FR0010315770', 1)", (ancien,))
            r = collect(conn, '2026-06-30', datetime(2026, 7, 1))
        assert not [s for s in r['signaux'] if s['cle'] == 'cours']


class TestJobPlanifie:
    def test_le_job_ignore_le_drapeau_demo(self, monkeypatch, tmp_path):
        """Le drapeau global de demo, laisse par la derniere requete, ne doit
        rediriger le job ni vers demo.db ni vers le provider simule."""
        import services.scheduler as sched
        from services import prices

        vus = {}

        def _refresh(conn, provider=None):
            vus['base'] = conn.execute('PRAGMA database_list').fetchone()['file']
            vus['provider'] = provider
            return {}
        monkeypatch.setattr(prices, 'refresh_securities', _refresh)
        monkeypatch.setattr(prices, 'refresh_fx_rates', lambda conn, provider=None: None)
        monkeypatch.delenv('PRICE_PROVIDER', raising=False)
        monkeypatch.setattr(models, 'DEMO_DB_PATH', str(tmp_path / 'demo.db'))
        models.set_demo_mode(True)
        try:
            sched.run_job_now()
        finally:
            models.set_demo_mode(False)
        assert os.path.realpath(vus['base']) == os.path.realpath(models.DB_PATH)
        assert isinstance(vus['provider'], prices.YahooProvider)


class TestDispositionSynthese:
    def test_aller_retour_et_validation(self, client):
        H = {'X-CSRF-Token': 'test'}
        d = {'ordre': ['evolution', 'chiffres'], 'largeurs': {'evolution': 6}, 'masquees': ['fiscalite']}
        assert client.put('/api/synthese/disposition', headers=H, json=d).status_code == 200
        assert client.get('/api/synthese/disposition').get_json()['largeurs'] == {'evolution': 6}
        assert client.put('/api/synthese/disposition', headers=H, json={'ordre': ['inconnue']}).status_code == 400
        assert client.put('/api/synthese/disposition', headers=H, json={'largeurs': {'evolution': 2}}).status_code == 400
        assert client.put('/api/synthese/disposition', headers=H, json={}).get_json() == {}
        assert client.get('/api/synthese/disposition').get_json() == {}


class TestBarreMobile:
    def test_aller_retour_et_limites(self, client):
        H = {'X-CSRF-Token': 'test'}
        d = {'ordre': ['credits', 'synthese', 'positions', 'conseil'], 'visibles': ['synthese', 'credits']}
        r = client.put('/api/preferences/barre-mobile', headers=H, json=d)
        assert r.status_code == 200 and r.get_json()['visibles'] == ['credits', 'synthese']
        trop = {'ordre': [], 'visibles': ['synthese', 'positions', 'actifs', 'entites', 'credits']}
        assert client.put('/api/preferences/barre-mobile', headers=H, json=trop).status_code == 400
        assert client.put('/api/preferences/barre-mobile', headers=H, json={'visibles': ['inconnu']}).status_code == 400
        assert client.put('/api/preferences/barre-mobile', headers=H, json={}).get_json() == {}
