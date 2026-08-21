"""Tests de /api/performance et du garde-fou d'annualisation."""
import os
import sys
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

from routes.performance import annualise, _flux_signed, _chain, MIN_DAYS_ANNUALISE  # noqa: E402


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


def _seed(dates_values, flux=(), owner='Alice', envelope='PEA'):
    """Cree des positions (date -> valeur) et des flux (date, type, montant)."""
    with get_db() as conn:
        for d, v in dates_values:
            conn.execute(
                """INSERT INTO positions (date, owner, category, envelope,
                   establishment, value, debt, ownership_pct, debt_pct)
                   VALUES (?,?,'Actions',?,'Test',?,0,1.0,1.0)""", (d, owner, envelope, v))
        for d, t, a in flux:
            conn.execute(
                'INSERT INTO flux (date, owner, envelope, type, amount) VALUES (?,?,?,?,?)',
                (d, owner, envelope, t, a))
        conn.commit()



class TestAnnualise:
    def test_periode_longue_annualise(self):
        # +21 % sur 2 ans -> ~+10 %/an
        r = annualise(0.21, 730)
        assert r is not None and 0.09 < r < 0.11

    def test_periode_courte_refusee(self):
        # +12,7 % en 49 jours annualiserait a +145 % : on refuse
        assert annualise(0.127, 49) is None

    def test_seuil_exact(self):
        assert annualise(0.10, MIN_DAYS_ANNUALISE) is not None
        assert annualise(0.10, MIN_DAYS_ANNUALISE - 1) is None

    def test_cumul_absent(self):
        assert annualise(None, 500) is None


class TestFluxSigned:
    def test_versement_positif(self):
        assert _flux_signed({'type': 'Versement', 'amount': 100}) == 100

    def test_retrait_negatif(self):
        assert _flux_signed({'type': 'Retrait', 'amount': 100}) == -100

    def test_frais_negatif(self):
        assert _flux_signed({'type': 'Frais', 'amount': 30}) == -30

    def test_dividende_non_externe(self):
        # Un dividende est produit par les actifs detenus : il fait partie du
        # rendement, pas des apports. L'inclure le retirerait de la performance.
        assert _flux_signed({'type': 'Dividende/Intérêt', 'amount': 50}) == 0

    def test_type_inconnu_ignore(self):
        assert _flux_signed({'type': 'Bizarre', 'amount': 50}) == 0


class TestChain:
    def test_sans_flux(self):
        dates = ['2024-01-01', '2025-01-01']
        serie, cumul, days, gaps, suspects = _chain(dates, {dates[0]: 100.0, dates[1]: 110.0}, [])
        assert cumul == pytest.approx(0.10)
        assert days == 366 and gaps == 0
        assert serie[0]['index'] == 100.0 and serie[-1]['index'] == pytest.approx(110.0)

    def test_versement_milieu_de_periode_pondere(self):
        # 100 au depart, +100 a mi-parcours, 220 a l'arrivee.
        # Base Dietz = 100 + 100*0.5 = 150 -> (220-100-100)/150 = 13,3 %
        dates = ['2024-01-01', '2024-12-31']
        serie, cumul, days, gaps, suspects = _chain(
            dates, {dates[0]: 100.0, dates[1]: 220.0}, [('2024-07-01', 100.0)])
        assert cumul == pytest.approx(0.1333, abs=1e-3)

    def test_demarrage_a_zero_saute(self):
        # L'enveloppe n'existe pas au premier arrete : pas de rendement mesurable
        # sur l'intervalle de financement.
        dates = ['2024-01-01', '2024-06-01', '2024-12-01']
        vals = {dates[0]: 0.0, dates[1]: 1000.0, dates[2]: 1100.0}
        serie, cumul, days, gaps, suspects = _chain(dates, vals, [('2024-05-01', 1000.0)])
        assert cumul == pytest.approx(0.10)
        assert serie[0]['date'] == '2024-06-01'

    def test_trou_de_valorisation_ignore(self):
        # Un arrete sans valorisation pour l'enveloppe ne vaut pas zero : le
        # compter donnerait -100 % puis un rebond symetrique.
        dates = ['2024-01-01', '2024-06-01', '2024-12-01']
        vals = {dates[0]: 1000.0, dates[1]: 0.0, dates[2]: 1100.0}
        serie, cumul, days, gaps, suspects = _chain(dates, vals, [])
        assert gaps == 2
        assert cumul is None or cumul > -0.5

    def test_serie_vide_si_jamais_de_capital(self):
        dates = ['2024-01-01', '2024-06-01']
        serie, cumul, days, gaps, suspects = _chain(dates, {d: 0.0 for d in dates}, [])
        assert serie == [] and cumul is None


class TestEndpoint:
    def test_un_seul_arrete_insuffisant(self, client):
        _seed([('2024-01-01', 1000)])
        d = client.get('/api/performance').get_json()
        assert d['insufficient'] is True

    def test_twr_sans_flux(self, client):
        _seed([('2024-01-01', 1000), ('2025-01-01', 1200)])
        d = client.get('/api/performance').get_json()
        env = d['groups'][0]
        assert env['envelope'] == 'PEA'
        assert env['twr'] == pytest.approx(0.20)
        assert env['annualisable'] is True
        assert env['twr_annualise'] == pytest.approx(0.1995, abs=1e-3)

    def test_versement_neutralise(self, client):
        # 1000 -> 2100 dont 1000 verses le jour meme du 2e arrete : le rendement
        # ne doit pas confondre l'apport avec de la performance.
        _seed([('2024-01-01', 1000), ('2025-01-01', 2100)],
              [('2025-01-01', 'Versement', 1000)])
        d = client.get('/api/performance').get_json()
        assert d['groups'][0]['twr'] == pytest.approx(0.10)

    def test_dividende_compte_dans_le_rendement(self, client):
        _seed([('2024-01-01', 1000), ('2025-01-01', 1100)],
              [('2024-06-01', 'Dividende/Intérêt', 50)])
        d = client.get('/api/performance').get_json()
        # Le dividende reste dans la performance : +10 %, pas +5 %.
        assert d['groups'][0]['twr'] == pytest.approx(0.10)

    def test_periode_courte_non_annualisee(self, client):
        _seed([('2026-01-01', 1000), ('2026-02-15', 1130)])
        d = client.get('/api/performance').get_json()
        env = d['groups'][0]
        assert env['annualisable'] is False
        assert env['twr_annualise'] is None
        assert env['twr'] == pytest.approx(0.13)

    def test_filtre_par_personne(self, client):
        _seed([('2024-01-01', 1000), ('2025-01-01', 1200)], owner='Alice')
        _seed([('2024-01-01', 500), ('2025-01-01', 400)], owner='Bob', envelope='CTO')
        d = client.get('/api/performance?owner=Alice').get_json()
        assert [e['envelope'] for e in d['groups']] == ['PEA']
        assert d['groups'][0]['twr'] == pytest.approx(0.20)

    def test_structure_reponse(self, client):
        _seed([('2024-01-01', 1000), ('2025-01-01', 1200)])
        d = client.get('/api/performance').get_json()
        assert d['min_days_annualise'] == MIN_DAYS_ANNUALISE
        for e in d['groups']:
            assert {'label', 'key', 'envelope', 'twr', 'days', 'annualisable',
                'serie', 'gaps', 'measurable'} <= set(e)


class TestSuspectJumps:
    def test_saut_sans_flux_signale(self, client):
        # 100 000 -> 200 000 sans flux declare : c'est un versement non
        # enregistre, pas un doublement de la valeur des actifs.
        _seed([('2026-01-01', 100000), ('2026-02-01', 200000)])
        d = client.get('/api/performance').get_json()
        s = d['groups'][0]['suspect_periods']
        assert len(s) == 1
        assert s[0]['delta'] == pytest.approx(100000.0)

    def test_saut_explique_par_un_flux_non_signale(self, client):
        _seed([('2026-01-01', 100000), ('2026-02-01', 200000)],
              [('2026-01-15', 'Versement', 98000)])
        d = client.get('/api/performance').get_json()
        assert d['groups'][0]['suspect_periods'] == []

    def test_flux_minuscule_n_explique_pas_un_gros_ecart(self, client):
        """Un versement de 100 EUR ne justifie pas une chute de 60 000."""
        _seed([('2026-01-01', 100000), ('2026-02-01', 40000)],
              [('2026-01-15', 'Versement', 100)])
        d = client.get('/api/performance').get_json()
        assert len(d['groups'][0]['suspect_periods']) == 1
        assert d['groups'][0]['suspect_periods'][0]['flux'] == pytest.approx(100.0)

    def test_variation_normale_non_signalee(self, client):
        _seed([('2026-01-01', 100000), ('2026-02-01', 105000)])
        d = client.get('/api/performance').get_json()
        assert d['groups'][0]['suspect_periods'] == []


class TestMeasurable:
    def test_cash_non_mesurable(self, client):
        with get_db() as conn:
            for d, v in (('2026-01-01', 10000), ('2026-02-01', 40000)):
                conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                    establishment, value, debt, ownership_pct, debt_pct)
                    VALUES (?,?,'Cash & dépôts','Compte courant','T',?,0,1.0,1.0)""",
                    (d, 'Alice', v))
            conn.commit()
        d = client.get('/api/performance').get_json()
        env = d['groups'][0]
        assert env['measurable'] is False
        # Un compte courant est exclu de l'ensemble : ses mouvements de
        # tresorerie ne sont pas du rendement.
        assert d['global'] is None or env['envelope'] not in (d['global'].get('envelopes') or [])

    def test_actions_mesurable(self, client):
        _seed([('2026-01-01', 10000), ('2026-02-01', 11000)])
        d = client.get('/api/performance').get_json()
        assert d['groups'][0]['measurable'] is True


class TestGrouping:
    """La maille compte separe ce que la maille enveloppe melange.

    Une assurance-vie regroupant quatre contrats chez quatre etablissements n'a
    pas de rendement commun ; pire, l'ouverture d'un contrat entre deux arretes
    est comptee comme une performance de l'ensemble.
    """

    def _two_contracts(self):
        with get_db() as conn:
            rows = [
                # contrat A present des le debut, +10 %
                ('2026-01-01', 'Boursorama', 10000), ('2026-07-01', 'Boursorama', 11000),
                # contrat B ouvert plus tard : ce n'est pas un gain
                ('2026-07-01', 'CA31', 100000),
            ]
            for d, etab, v in rows:
                conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                    establishment, value, debt, ownership_pct, debt_pct)
                    VALUES (?,'Alice','Actions','Assurance-vie',?,?,0,1.0,1.0)""", (d, etab, v))
            conn.commit()

    def test_maille_compte_isole_les_contrats(self, client):
        self._two_contracts()
        d = client.get('/api/performance?group=account').get_json()
        assert d['grouping'] == 'account'
        by = {g['establishment']: g for g in d['groups']}
        assert by['Boursorama']['twr'] == pytest.approx(0.10)
        # Le contrat ouvert au dernier arrete n'a pas de rendement mesurable
        assert 'CA31' not in by or by['CA31']['twr'] is None

    def test_maille_enveloppe_neutralise_l_ouverture(self, client):
        """L'arrivee d'un contrat dans un agregat n'est pas un rendement.

        10 000 -> 111 000 sans flux declare : sans traitement, l'enveloppe
        afficherait +1000 %. L'ouverture du second contrat est un apport de
        capital dans le perimetre, pas une performance.
        """
        self._two_contracts()
        d = client.get('/api/performance?group=envelope').get_json()
        g = d['groups'][0]
        # Seul le contrat A a produit du rendement : +10 %
        assert g['twr'] == pytest.approx(0.10, abs=0.01)
        assert g['accounts'] == 2

    def test_maille_inconnue_refusee(self, client):
        assert client.get('/api/performance?group=nawak').status_code == 400

    def test_label_lisible(self, client):
        self._two_contracts()
        d = client.get('/api/performance?group=account').get_json()
        assert any(g['label'] == 'Assurance-vie · Boursorama · Alice' for g in d['groups'])


class TestStatuts:
    """Un compte non mesurable ne doit pas disparaitre sans explication.

    Un compte ouvert au dernier arrete etait retire de la reponse : le total de
    cet onglet divergeait de celui de la synthese sans qu'aucun ecran ne
    mentionne l'ecart.
    """

    def test_un_seul_arrete_rendu_avec_son_statut(self, client):
        _seed([('2026-01-01', 1000), ('2026-08-01', 1200)], envelope='PEA')
        with get_db() as conn:
            conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                establishment, value, debt, ownership_pct, debt_pct)
                VALUES ('2026-08-01','Alice','Actions','CTO','T',500,0,1.0,1.0)""")
            conn.commit()
        d = client.get('/api/performance').get_json()
        par = {g['envelope']: g for g in d['groups']}
        assert par['CTO']['status'] == 'insufficient'
        assert par['CTO']['twr'] is None
        assert par['CTO']['value'] == pytest.approx(500.0)
        # et il est nomme dans les exclusions
        assert any(e['label'].startswith('CTO') for e in d['excluded'])

    def test_exclu_hors_du_total(self, client):
        _seed([('2026-01-01', 1000), ('2026-08-01', 1200)], envelope='PEA')
        with get_db() as conn:
            conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                establishment, value, debt, ownership_pct, debt_pct)
                VALUES ('2026-08-01','Alice','Actions','CTO','T',500,0,1.0,1.0)""")
            conn.commit()
        d = client.get('/api/performance').get_json()
        # Le total ne peut pas integrer un compte dont le rendement est inconnu.
        assert d['global']['value'] == pytest.approx(1200.0)

    def test_statut_ok_pour_un_compte_mesure(self, client):
        _seed([('2026-01-01', 1000), ('2026-08-01', 1200)])
        assert client.get('/api/performance').get_json()['groups'][0]['status'] == 'ok'

    def test_valeur_negative_distinguee(self, client):
        """Une dette nette n'est pas un historique manquant.

        Un compte courant d'associe negatif garde cinq arretes : le dire
        "historique insuffisant" serait faux. Aucun rendement n'existe sur une
        base negative, quelle que soit la profondeur d'historique.
        """
        _seed([('2026-01-01', -5000), ('2026-04-01', -4000), ('2026-08-01', -3000)],
              envelope='Holding')
        d = client.get('/api/performance').get_json()
        g = d['groups'][0]
        assert g['status'] == 'negative'
        assert g['dates_count'] == 3          # l'historique est bien la
        assert g['twr'] is None


class TestComposition:
    """Un agregat ne doit pas compter l'arrivee d'un compte comme du rendement.

    Constate en prod : l'ensemble affichait +37,24 % quand la moyenne ponderee
    des comptes donnait +6,68 %. Tout l'ecart venait d'une assurance-vie de
    100 000 EUR entrant dans le perimetre entre deux arretes.
    """

    def _deux_comptes(self):
        """A present aux trois arretes, B a partir du deuxieme.

        B doit avoir deux valorisations pour etre mesurable : sinon il est ecarte
        et l'agregat ne teste rien.
        """
        with get_db() as conn:
            lignes = [
                ('2026-01-01', 'PEA', 10000), ('2026-04-01', 'PEA', 10500),
                ('2026-08-01', 'PEA', 11000),
                ('2026-04-01', 'CTO', 100000), ('2026-08-01', 'CTO', 100000),
            ]
            for d, env, v in lignes:
                conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                    establishment, value, debt, ownership_pct, debt_pct)
                    VALUES (?,'Alice','Actions',?,'X',?,0,1.0,1.0)""", (d, env, v))
            conn.commit()

    def test_ensemble_ignore_l_arrivee_d_un_compte(self, client):
        self._deux_comptes()
        d = client.get('/api/performance').get_json()
        g = d['global']
        assert g['accounts'] == 2
        # Sans neutralisation : le total passe de 10 000 a 110 500 entre les deux
        # premiers arretes, soit +1005 % attribues au rendement.
        # Avec : seul le PEA progresse (+5 % puis +4,76 %), le CTO stagne.
        assert g['twr'] == pytest.approx(0.0476, abs=0.01)
        assert 0 < g['twr'] < 0.10

    def test_ensemble_ignore_la_disparition_d_un_compte(self, client):
        with get_db() as conn:
            for d, env, v in (('2026-01-01', 'PEA', 10000), ('2026-08-01', 'PEA', 11000),
                              ('2026-01-01', 'CTO', 50000)):
                conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                    establishment, value, debt, ownership_pct, debt_pct)
                    VALUES (?,'Alice','Actions',?,'X',?,0,1.0,1.0)""", (d, env, v))
            conn.commit()
        g = client.get('/api/performance').get_json()['global']
        # Le CTO sort du perimetre : ce n'est pas une perte de 83 %
        assert g['twr'] == pytest.approx(0.10, abs=0.01)

    def test_compte_seul_inchange(self, client):
        """A la maille compte, un groupe n'a qu'un membre : rien a neutraliser."""
        _seed([('2026-01-01', 10000), ('2026-08-01', 11000)])
        g = client.get('/api/performance').get_json()['groups'][0]
        assert g['twr'] == pytest.approx(0.10)
        assert g['accounts'] == 1

    def test_apports_limites_a_la_periode(self, client):
        """Un versement anterieur au premier arrete n'est pas un apport de la periode.

        Le calcul l'ignore ; l'afficher dans le KPI donnerait un capital apporte
        que le rendement ne reflete pas.
        """
        _seed([('2026-03-01', 10000), ('2026-09-01', 12000)],
              [('2025-06-01', 'Versement', 5000), ('2026-05-01', 'Versement', 1000)])
        g = client.get('/api/performance').get_json()['groups'][0]
        assert g['flux_net'] == pytest.approx(1000.0)
        assert g['flux_count'] == 1


class TestEpargne:
    """Un livret a un rendement faible mais reel ; un compte courant n'en a pas.

    Les deux partagent la categorie "Cash & depots" : c'est l'enveloppe qui
    tranche, pas la categorie comptable.
    """

    def _cash(self, envelope, valeurs):
        with get_db() as conn:
            for d, v in valeurs:
                conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                    establishment, value, debt, ownership_pct, debt_pct)
                    VALUES (?,'Alice','Cash & dépôts',?,'X',?,0,1.0,1.0)""", (d, envelope, v))
            conn.commit()

    def test_livret_mesurable(self, client):
        self._cash('Livret A', [('2026-01-01', 20000), ('2026-08-01', 20400)])
        g = client.get('/api/performance').get_json()['groups'][0]
        assert g['status'] == 'ok'
        assert g['twr'] == pytest.approx(0.02)

    def test_compte_courant_non_mesurable(self, client):
        self._cash('Compte courant', [('2026-01-01', 3000), ('2026-08-01', 9000)])
        g = client.get('/api/performance').get_json()['groups'][0]
        assert g['status'] == 'non_measurable'

    def test_immobilier_non_mesurable(self, client):
        """Un bien d'usage n'est pas un placement.

        Sa valeur est une estimation saisie a la main : entre deux
        reevaluations elle ne bouge pas, et le seul mouvement du capital net
        est l'amortissement du pret — un remboursement de dette qui se lisait
        comme un rendement.
        """
        with get_db() as conn:
            for d, dette in (('2026-01-01', 184000), ('2026-08-01', 183000)):
                conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                    establishment, value, debt, ownership_pct, debt_pct)
                    VALUES (?,'Alice','Immobilier','Immobilier',NULL,610000,?,0.5,0.5)""",
                    (d, dette))
            conn.commit()
        g = client.get('/api/performance').get_json()['groups'][0]
        assert g['status'] == 'non_measurable'

    def test_sci_reste_mesurable(self, client):
        """Des parts de SCPI sont un placement : leur valeur suit un marche."""
        with get_db() as conn:
            for d, v in (('2026-01-01', 100000), ('2026-08-01', 104000)):
                conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                    establishment, value, debt, ownership_pct, debt_pct)
                    VALUES (?,'Alice','SCPI','SCI',NULL,?,0,1.0,1.0)""", (d, v))
            conn.commit()
        g = client.get('/api/performance').get_json()['groups'][0]
        assert g['status'] == 'ok'
        assert g['twr'] == pytest.approx(0.04)

    def test_objet_de_valeur_non_mesurable(self, client):
        with get_db() as conn:
            for d, v in (('2026-01-01', 22000), ('2026-08-01', 47000)):
                conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                    establishment, value, debt, ownership_pct, debt_pct)
                    VALUES (?,'Alice','Objets de valeur','Autre',NULL,?,0,1.0,1.0)""", (d, v))
            conn.commit()
        g = client.get('/api/performance').get_json()['groups'][0]
        assert g['status'] == 'non_measurable'


class TestComptesHomonymes:
    """Deux comptes de meme nature chez le meme etablissement.

    Constate en prod : un compte-titres ferme et son remplacant, tous deux chez
    la meme banque. Sous une cle commune, la cloture du premier se lisait comme
    une chute de 82 % du second, puis sa reprise comme un bond de 114 %. Le champ
    `label` les distingue.
    """

    def _deux_cto(self):
        with get_db() as conn:
            lignes = [
                ('2026-01-01', 'Ancien CTO', 11000), ('2026-03-01', 'Ancien CTO', 11500),
                ('2026-06-01', None, 2000), ('2026-08-01', None, 2100),
            ]
            for d, label, v in lignes:
                conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                    establishment, label, value, debt, ownership_pct, debt_pct)
                    VALUES (?,'Alice','Actions','CTO','Ma Banque',?,?,0,1.0,1.0)""",
                    (d, label, v))
            conn.commit()

    def test_comptes_separes_par_leur_libelle(self, client):
        self._deux_cto()
        d = client.get('/api/performance').get_json()
        par = {g['account_label']: g for g in d['groups']}
        assert set(par) == {'Ancien CTO', None}
        assert par['Ancien CTO']['twr'] == pytest.approx(0.0455, abs=0.01)
        assert par[None]['twr'] == pytest.approx(0.05, abs=0.01)

    def test_libelle_visible_dans_le_nom(self, client):
        self._deux_cto()
        d = client.get('/api/performance').get_json()
        assert any(g['label'] == 'CTO — Ancien CTO · Ma Banque · Alice' for g in d['groups'])

    def test_maille_enveloppe_les_regroupe(self, client):
        """A la maille enveloppe, les deux comptes se retrouvent — et la
        disparition de l'un est neutralisee comme un retrait."""
        self._deux_cto()
        d = client.get('/api/performance?group=envelope').get_json()
        assert len(d['groups']) == 1
        g = d['groups'][0]
        assert g['accounts'] == 2
        # Sans neutralisation : 11 500 -> 2 000 se lirait comme -83 %
        assert g['twr'] > -0.2
