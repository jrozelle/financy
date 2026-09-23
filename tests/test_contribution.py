"""Tests de la décomposition : épargne, capital remboursé, comptes hors suivi, performance."""
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
from services.contribution import decompose  # noqa: E402
from services.montants import centimes  # noqa: E402


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


def _flux(conn, date, type_, montant, owner='Paul'):
    conn.execute('INSERT INTO flux (date, owner, envelope, type, amount) '
                 "VALUES (?,?,'PEA',?,?)", (date, owner, type_, centimes(montant)))


def _arretes(*couples):
    """(date, net) -> la forme attendue par decompose()."""
    return [{'date': d, 'family_net': n, 'by_owner': {'Paul': n}} for d, n in couples]


class TestDecomposition:
    def test_identite_apports_plus_performance(self):
        with get_db() as conn:
            _flux(conn, '2026-02-10', 'Versement', 1000)
            conn.commit()
            r = decompose(conn, _arretes(('2026-01-31', 100000), ('2026-03-31', 105000)))
        p = r['periodes'][0]
        assert p['variation'] == 5000
        assert p['epargne'] == 1000
        assert p['performance'] == 4000
        assert p['epargne'] + p['performance'] == p['variation']

    def test_hausse_entierement_due_a_l_epargne(self):
        # Le patrimoine monte de 2 000 et 2 000 ont ete verses : le marche n'y
        # est pour rien. C'est exactement ce que la carte doit rendre lisible.
        with get_db() as conn:
            _flux(conn, '2026-02-10', 'Versement', 2000)
            conn.commit()
            r = decompose(conn, _arretes(('2026-01-31', 50000), ('2026-03-31', 52000)))
        assert r['periodes'][0]['performance'] == 0
        assert r['periodes'][0]['epargne'] == 2000

    def test_retrait_compte_en_negatif(self):
        with get_db() as conn:
            _flux(conn, '2026-02-10', 'Retrait', 3000)
            conn.commit()
            r = decompose(conn, _arretes(('2026-01-31', 50000), ('2026-03-31', 48000)))
        p = r['periodes'][0]
        assert p['epargne'] == -3000
        assert p['performance'] == 1000        # −2 000 de variation, −3 000 sortis

    def test_dividendes_et_frais_ne_sont_pas_des_apports(self):
        # Regle de l'application : un dividende est produit par les actifs
        # detenus, des frais sont preleves dans le contrat. Les deux
        # appartiennent au rendement, pas aux apports.
        with get_db() as conn:
            _flux(conn, '2026-02-10', 'Dividende/Intérêt', 800)
            _flux(conn, '2026-02-11', 'Frais', 200)
            conn.commit()
            r = decompose(conn, _arretes(('2026-01-31', 50000), ('2026-03-31', 50600)))
        p = r['periodes'][0]
        assert p['epargne'] == 0
        assert p['performance'] == 600

    def test_borne_basse_exclue(self):
        # Un flux tombant le jour d'un arrete est deja dans sa valeur : le
        # compter de nouveau le ferait apparaitre deux fois.
        with get_db() as conn:
            _flux(conn, '2026-01-31', 'Versement', 5000)
            conn.commit()
            r = decompose(conn, _arretes(('2026-01-31', 50000), ('2026-03-31', 51000)))
        assert r['periodes'][0]['epargne'] == 0

    def test_borne_haute_incluse(self):
        with get_db() as conn:
            _flux(conn, '2026-03-31', 'Versement', 5000)
            conn.commit()
            r = decompose(conn, _arretes(('2026-01-31', 50000), ('2026-03-31', 55000)))
        assert r['periodes'][0]['epargne'] == 5000

    def test_filtrage_par_titulaire(self):
        with get_db() as conn:
            _flux(conn, '2026-02-10', 'Versement', 1000, owner='Paul')
            _flux(conn, '2026-02-10', 'Versement', 4000, owner='Claire')
            conn.commit()
            arretes = [
                {'date': '2026-01-31', 'family_net': 100000,
                 'by_owner': {'Paul': 60000, 'Claire': 40000}},
                {'date': '2026-03-31', 'family_net': 106000,
                 'by_owner': {'Paul': 61500, 'Claire': 44500}},
            ]
            r = decompose(conn, arretes, owner='Paul')
        p = r['periodes'][0]
        assert p['variation'] == 1500          # la part de Paul seulement
        assert p['epargne'] == 1000            # ses versements seulement
        assert p['performance'] == 500

    def test_limite_garde_les_periodes_recentes(self):
        with get_db() as conn:
            conn.commit()
            arretes = _arretes(*[(f'2026-{m:02d}-01', 1000 * m) for m in range(1, 9)])
            r = decompose(conn, arretes, limite=3)
        assert len(r['periodes']) == 3
        assert r['periodes'][-1]['fin'] == '2026-08-01'

    def test_totaux_coherents(self):
        with get_db() as conn:
            _flux(conn, '2026-02-10', 'Versement', 1000)
            _flux(conn, '2026-04-10', 'Versement', 2000)
            conn.commit()
            r = decompose(conn, _arretes(
                ('2026-01-31', 100000), ('2026-03-31', 104000), ('2026-05-31', 108000)))
        assert r['total_epargne'] == 3000
        assert r['total_variation'] == 8000
        assert r['total_performance'] == 5000
        assert r['total_epargne'] + r['total_performance'] == r['total_variation']


class TestGroupementTrimestriel:
    """Les arretes sont irreguliers — deux en aout, aucun en septembre. Les
    regrouper en trimestres calendaires rend les colonnes comparables."""

    def test_deux_arretes_du_meme_trimestre_fusionnent(self):
        with get_db() as conn:
            _flux(conn, '2026-07-10', 'Versement', 1000)
            _flux(conn, '2026-08-20', 'Versement', 500)
            conn.commit()
            r = decompose(conn, _arretes(
                ('2026-06-30', 100000), ('2026-07-31', 102000), ('2026-08-31', 103000)))
        assert len(r['periodes']) == 1               # juillet et aout, un seul T3
        p = r['periodes'][0]
        assert p['libelle'] == 'T3 26'
        assert p['epargne'] == 1500                  # les deux versements
        assert p['variation'] == 3000                # 100 000 -> 103 000

    def test_bornes_couvrent_tout_le_trimestre(self):
        with get_db() as conn:
            conn.commit()
            r = decompose(conn, _arretes(
                ('2026-06-30', 100000), ('2026-07-31', 101000), ('2026-08-31', 102000)))
        p = r['periodes'][0]
        assert p['debut'] == '2026-06-30'            # depart de la 1re periode
        assert p['fin'] == '2026-08-31'              # arrivee de la derniere

    def test_trimestres_distincts_restent_separes(self):
        with get_db() as conn:
            conn.commit()
            r = decompose(conn, _arretes(
                ('2026-02-28', 100000), ('2026-05-31', 103000), ('2026-08-31', 107000)))
        assert [p['libelle'] for p in r['periodes']] == ['T2 26', 'T3 26']

    def test_ordre_chronologique(self):
        with get_db() as conn:
            conn.commit()
            r = decompose(conn, _arretes(
                ('2025-11-30', 50000), ('2026-02-28', 52000), ('2026-05-31', 55000)))
        libelles = [p['libelle'] for p in r['periodes']]
        assert libelles == ['T1 26', 'T2 26']        # 2026 apres 2025, T1 avant T2


class TestEndpoint:
    def _snapshot(self, conn, date, valeur, owner='Paul'):
        conn.execute('INSERT INTO positions (date, owner, category, envelope, value) '
                     "VALUES (?,?,'Financier','PEA',?)", (date, owner, valeur))

    def test_deux_arretes_minimum(self, client):
        with get_db() as conn:
            self._snapshot(conn, '2026-01-31', 50000)
            conn.commit()
        r = client.get('/api/contribution')
        assert r.status_code == 200
        assert r.json['periodes'] == []        # une photo ne fait pas une variation

    def test_decomposition_via_l_api(self, client):
        with get_db() as conn:
            self._snapshot(conn, '2026-01-31', 50000)
            self._snapshot(conn, '2026-03-31', 53000)
            _flux(conn, '2026-02-10', 'Versement', 1000)
            conn.commit()
        r = client.get('/api/contribution')
        assert r.status_code == 200
        p = r.json['periodes'][0]
        assert p['variation'] == 3000
        assert p['epargne'] == 1000
        assert p['performance'] == 2000

    def test_limite_bornee(self, client):
        with get_db() as conn:
            self._snapshot(conn, '2026-01-31', 50000)
            self._snapshot(conn, '2026-03-31', 53000)
            conn.commit()
        assert client.get('/api/contribution?limit=999').status_code == 200
        assert client.get('/api/contribution?limit=0').status_code == 200

    def test_exige_la_session(self):
        app.config['TESTING'] = True
        with app.test_client() as anon:
            assert anon.get('/api/contribution').status_code in (302, 401)


class TestComptesHorsSuivi:
    """Un compte qui apparait n'a pas rapporte sa valeur (cas reel du 03/03/2026 :
    une assurance-vie de 100 000 €, alimentee par un retrait du livret dont seule
    la jambe de sortie etait enregistree, passait pour 100 000 € de performance)."""

    def _arretes(self, a, b):
        def arr(d, comptes):
            return {'date': d, 'family_net': sum(comptes.values()), 'by_owner': {'Paul': sum(comptes.values())},
                    'comptes': {k: {'net': v, 'liq': k[1].startswith('Livret')} for k, v in comptes.items()}}
        return [arr('2026-02-16', a), arr('2026-03-03', b)]

    LIVRET = ('Paul', 'Livret', 'Bourso', '', '')
    AV = ('Paul', 'Assurance-vie', 'CA31', '', '')

    def test_un_compte_apparu_sans_versement_n_est_pas_de_la_performance(self):
        with get_db() as conn:
            conn.execute("INSERT INTO flux (date, owner, envelope, establishment, type, amount) "
                         "VALUES ('2026-02-27','Paul','Livret','Bourso','Retrait',10000000)")  # centimes
            conn.commit()
            r = decompose(conn, self._arretes({self.LIVRET: 150000}, {self.LIVRET: 50000, self.AV: 100000}))
        p = r['periodes'][0]
        assert p['epargne'] == -100000
        assert p['hors_suivi'] == 100000
        assert p['performance'] == 0
        assert p['comptes_hors_suivi'][0]['compte'].startswith('Assurance-vie')
        assert p['comptes_hors_suivi'][0]['sens'] == 'entree'

    def test_le_flux_enregistre_fait_disparaitre_l_ecart(self):
        with get_db() as conn:
            conn.execute("INSERT INTO flux (date, owner, envelope, establishment, type, amount) "
                         "VALUES ('2026-02-27','Paul','Assurance-vie','CA31','Versement',10000000)")  # centimes
            conn.commit()
            r = decompose(conn, self._arretes({self.LIVRET: 150000}, {self.LIVRET: 150000, self.AV: 100000}))
        p = r['periodes'][0]
        assert p['hors_suivi'] == 0 and p['epargne'] == 100000 and not p['comptes_hors_suivi']

    def test_un_changement_d_enveloppe_s_annule(self):
        a = {('Paul', 'Biens', '', '', 'Montres'): 22000}
        b = {('Paul', 'Autre', '', '', 'Montres'): 22000}
        with get_db() as conn:
            r = decompose(conn, self._arretes(a, b))
        assert r['periodes'][0]['hors_suivi'] == 0
        assert not r['periodes'][0]['comptes_hors_suivi']


class TestEpargneEtCapital:
    """L'argent qui entre, et lui seul : un DCA ne compte pas, le salaire qui
    arrive sans flux compte, le capital rembourse est de l'epargne."""

    LIVRET = ('Paul', 'Livret A', 'Bourso', '', '')
    PEA = ('Paul', 'PEA', 'Bourso', '', '')
    RP = ('Paul', 'Immobilier', '', 'Maison', '')

    def _arretes(self, a, b):
        def arr(d, comptes):
            return {'date': d, 'family_net': sum(c['net'] for c in comptes.values()),
                    'by_owner': {'Paul': sum(c['net'] for c in comptes.values())}, 'comptes': comptes}
        return [arr('2026-06-30', a), arr('2026-09-30', b)]

    def test_dca_salaire_et_capital(self):
        with get_db() as conn:
            _flux(conn, '2026-07-15', 'Versement', 3000)          # DCA du livret vers le PEA
            conn.commit()
            avant = {self.LIVRET: {'net': 20000, 'liq': True}, self.PEA: {'net': 10000},
                     self.RP: {'net': 100000, 'dette': 200000}}
            # Le livret a perdu 3 000 de DCA mais recu 2 000 de salaire ; le PEA
            # a gagne 300 ; 1 500 de capital ont ete rembourses.
            apres = {self.LIVRET: {'net': 19000, 'liq': True}, self.PEA: {'net': 13300},
                     self.RP: {'net': 101500, 'dette': 198500}}
            r = decompose(conn, self._arretes(avant, apres))
        p = r['periodes'][0]
        assert p['epargne'] == 2000 and p['versements'] == 3000
        assert p['capital'] == 1500
        assert p['performance'] == 300
        assert p['epargne'] + p['capital'] + p['hors_suivi'] + p['performance'] == p['variation']
