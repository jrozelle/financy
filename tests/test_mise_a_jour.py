"""Mise a jour d'un arrete : « Mettre a jour » dans la barre du haut.

Remplace « dupliquer l'arrete, puis ouvrir une modale par compte ». L'enjeu :
un seul appel, tout ou rien, et aucune ecriture qui passerait pour effective
sans l'etre.
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
os.environ['PRICE_PROVIDER'] = 'mock'

from models import init_db, get_db  # noqa: E402
from app import app  # noqa: E402
from services.montants import centimes  # noqa: E402
from services.snapshot import duplicate_snapshot  # noqa: E402

SRC, CIBLE = '2026-08-31', '2026-09-22'
CSRF = {'X-CSRF-Token': 'test'}


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


def _pos(conn, envelope, value, debt=0, entity=None, date=SRC, debt_pct=1.0, category='Cash & dépôts'):
    return conn.execute(
        'INSERT INTO positions (date, owner, category, envelope, value, debt, entity, debt_pct) '
        "VALUES (?,'Paul',?,?,?,?,?,?)", (date, category, envelope, centimes(value), centimes(debt), entity, debt_pct)).lastrowid


@pytest.fixture
def arrete():
    """Un livret saisi a la main, un PEA a lignes de titres, un bien d'entite."""
    with get_db() as c:
        livret = _pos(c, 'Livret A', 20000)
        pea = _pos(c, 'PEA', 0, category='Actions')
        c.execute("INSERT INTO holdings (position_id, isin, quantity, cost_basis, market_value) "
                  "VALUES (?, 'FR0000000001', 10, 900, 1000)", (pea,))
        c.execute("INSERT INTO entities (name, type, gross_assets, debt) VALUES ('SCI A', 'SCI', 30000000, 20000000)")  # centimes
        c.execute("INSERT INTO entity_snapshots (entity_name, date, gross_assets, debt) "
                  "VALUES ('SCI A', ?, 30000000, 20000000)", (SRC,))  # centimes
        sci = _pos(c, 'SCI', 0, entity='SCI A', category='Immobilier')
        c.commit()
    return {'livret': livret, 'pea': pea, 'sci': sci}


class TestPreparation:
    def test_modes_de_valorisation(self, client, arrete):
        d = client.get(f'/api/snapshots/update?source={SRC}&cible={CIBLE}').get_json()
        modes = {p['envelope']: p['mode'] for p in d['positions']}
        assert modes == {'Livret A': 'saisie', 'PEA': 'titres', 'SCI': 'entite'}

    def test_entites_a_la_date_source(self, client, arrete):
        d = client.get(f'/api/snapshots/update?source={SRC}&cible={CIBLE}').get_json()
        assert d['entites'] == [{'name': 'SCI A', 'gross_assets': 300000, 'debt': 200000}]

    def test_source_par_defaut_le_dernier_arrete(self, client, arrete):
        assert client.get('/api/snapshots/update').get_json()['source_date'] == SRC

    def test_en_place_si_meme_date(self, client, arrete):
        assert client.get(f'/api/snapshots/update?source={SRC}&cible={SRC}').get_json()['en_place']


class TestApplication:
    def _post(self, client, **corps):
        return client.post('/api/snapshots/update', json={'source_date': SRC, 'target_date': CIBLE, **corps},
                           headers=CSRF)

    def test_cree_l_arrete_et_applique_les_soldes(self, client, arrete):
        r = self._post(client, soldes={str(arrete['livret']): {'value': 21500}})
        assert r.status_code == 200 and r.get_json()['positions_maj'] == 1
        with get_db() as c:
            v = c.execute("SELECT value FROM positions WHERE date=? AND envelope='Livret A'", (CIBLE,)).fetchone()
            s = c.execute("SELECT value FROM positions WHERE date=? AND envelope='Livret A'", (SRC,)).fetchone()
        assert v['value'] == 2150000                      # centimes
        assert s['value'] == 2000000                      # la source est intacte (centimes)

    def test_toutes_les_positions_sont_recopiees(self, client, arrete):
        self._post(client, soldes={})
        with get_db() as c:
            n = c.execute('SELECT COUNT(*) n FROM positions WHERE date=?', (CIBLE,)).fetchone()['n']
            h = c.execute('SELECT COUNT(*) n FROM holdings h JOIN positions p ON p.id=h.position_id '
                          'WHERE p.date=?', (CIBLE,)).fetchone()['n']
        assert n == 3 and h == 1                          # les lignes de titres suivent

    def test_une_position_a_titres_est_refusee_et_dite(self, client, arrete):
        # Ecrire sa valeur n'aurait aucun effet : les cours la recalculent.
        # Le taire laisserait croire qu'elle a change.
        r = self._post(client, soldes={str(arrete['pea']): {'value': 99999}}).get_json()
        assert r['positions_maj'] == 0
        assert 'cours' in r['refusees'][0]['motif']

    def test_entite_datee_a_la_cible(self, client, arrete):
        self._post(client, entites={'SCI A': {'gross_assets': 305000, 'debt': 198500}})
        with get_db() as c:
            rows = c.execute("SELECT date, debt FROM entity_snapshots WHERE entity_name='SCI A' ORDER BY date").fetchall()
        assert [(r['date'], r['debt']) for r in rows] == [(SRC, 20000000), (CIBLE, 19850000)]  # centimes

    def test_entite_inconnue_refusee(self, client, arrete):
        r = self._post(client, entites={'Fantome': {'gross_assets': 1, 'debt': 0}}).get_json()
        assert r['entites_maj'] == 0 and r['refusees'][0]['entite'] == 'Fantome'

    def test_cible_existante_refusee_sans_rien_ecrire(self, client, arrete):
        with get_db() as c:
            _pos(c, 'Livret A', 1, date=CIBLE); c.commit()
        r = self._post(client, soldes={str(arrete['livret']): {'value': 5}})
        assert r.status_code == 409
        with get_db() as c:
            n = c.execute('SELECT COUNT(*) n FROM positions WHERE date=?', (CIBLE,)).fetchone()['n']
        assert n == 1                                      # rien n'a ete recopie par-dessus

    def test_en_place(self, client, arrete):
        r = client.post('/api/snapshots/update', headers=CSRF, json={
            'source_date': SRC, 'target_date': SRC, 'soldes': {str(arrete['livret']): {'value': 20100}}})
        assert r.get_json()['cree'] is False
        with get_db() as c:
            assert c.execute('SELECT COUNT(DISTINCT date) n FROM positions').fetchone()['n'] == 1
            assert c.execute("SELECT value FROM positions WHERE envelope='Livret A'").fetchone()['value'] == 2010000  # centimes

    def test_montant_negatif_refuse(self, client, arrete):
        assert self._post(client, soldes={str(arrete['livret']): {'value': -5}}).status_code == 400

    def test_exige_csrf(self, client, arrete):
        r = client.post('/api/snapshots/update', json={'source_date': SRC, 'target_date': CIBLE})
        assert r.status_code in (400, 403)


class TestDetteDupliquee:
    """La duplication recopiait `debt_attributed` — la dette deja multipliee
    par `debt_pct`, que la lecture multiplie encore. Une dette detenue a 50 %
    etait divisee par deux a chaque arrete."""

    def test_la_dette_ne_fond_pas_d_arrete_en_arrete(self):
        with get_db() as c:
            _pos(c, 'Immobilier', 200000, debt=100000, debt_pct=0.5, category='Immobilier', date='2026-01-31')
            c.commit()
            d = '2026-01-31'
            for cible in ('2026-02-28', '2026-03-31', '2026-04-30'):
                duplicate_snapshot(c, d, cible); c.commit(); d = cible
            dettes = [r['debt'] for r in c.execute('SELECT debt FROM positions ORDER BY date')]
        assert dettes == [10000000] * 4  # centimes


class TestTresorerieDeLEntite:
    """La valeur proposee d'une entite a releves comprend sa tresorerie a la
    date de l'arrete, sans recompter celle de l'arrete precedent."""

    def _ops(self, c, *ops):
        for d, m in ops:
            c.execute("INSERT INTO entite_operations (entity, date, libelle, montant, nature) "
                      "VALUES ('SCI A', ?, ?, ?, 'revenu')", (d, f'op {d} {m}', round(m * 100)))  # centimes
        c.commit()

    def _entite(self, client):
        d = client.get(f'/api/snapshots/update?source={SRC}&cible={CIBLE}').get_json()
        return next(e for e in d['entites'] if e['name'] == 'SCI A')

    def test_sans_releve_rien_ne_change(self, client, arrete):
        e = self._entite(client)
        assert 'tresorerie' not in e and 'valeur_proposee' not in e

    def test_premiere_inclusion(self, client, arrete):
        with get_db() as c:
            self._ops(c, ('2026-08-01', 1500.0), ('2026-09-20', 500.0), ('2026-09-30', 999.0))
        e = self._entite(client)
        # L'operation posterieure a l'arrete n'est pas comptee.
        assert e['tresorerie'] == {'montant': 2000.0, 'au': '2026-09-20', 'incluse_avant': 0.0}
        assert e['valeur_proposee'] == 302000.0

    def test_la_tresorerie_incluse_n_est_pas_recomptee(self, client, arrete):
        with get_db() as c:
            c.execute("UPDATE entity_snapshots SET gross_assets=30150000, tresorerie=150000 WHERE entity_name='SCI A'")  # centimes
            self._ops(c, ('2026-08-01', 1500.0), ('2026-09-20', 500.0))
        assert self._entite(client)['valeur_proposee'] == 302000.0

    def test_l_arrete_memorise_sa_tresorerie(self, client, arrete):
        client.post('/api/snapshots/update', headers=CSRF, json={
            'source_date': SRC, 'target_date': CIBLE,
            'entites': {'SCI A': {'gross_assets': 302000, 'debt': 200000, 'tresorerie': 2000}}})
        with get_db() as c:
            r = c.execute("SELECT tresorerie FROM entity_snapshots WHERE entity_name='SCI A' AND date=?",
                          (CIBLE,)).fetchone()
        assert r['tresorerie'] == 200000  # centimes
