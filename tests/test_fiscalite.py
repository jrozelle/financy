"""Tests de l'impot latent sur les plus-values.

L'enjeu de ce module n'est pas l'arithmetique — 17,2 % d'une somme — mais la
discipline de l'assiette : ne rien chiffrer qu'on ne sache fonder, et compter
a part ce qu'on ecarte.
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
from services.fiscalite import impot_latent, PS, PFU, IR_AV, ABATTEMENT_AV  # noqa: E402
from services.montants import centimes  # noqa: E402

DATE = '2026-06-30'


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


def _position(conn, envelope, valeur, owner='Paul', category='Actions', date=DATE):
    cur = conn.execute(
        'INSERT INTO positions (date, owner, category, envelope, value) VALUES (?,?,?,?,?)',
        (date, owner, category, envelope, valeur))
    return cur.lastrowid


def _versement(conn, envelope, montant, owner='Paul', date='2020-01-15'):
    conn.execute('INSERT INTO flux (date, owner, envelope, type, amount) VALUES (?,?,?,?,?)',
                 (date, owner, envelope, 'Versement', centimes(montant)))


def _titre(conn, position_id, cout, valeur, isin='FR0000000001'):
    conn.execute('INSERT INTO holdings (position_id, isin, quantity, cost_basis, market_value) '
                 'VALUES (?,?,?,?,?)', (position_id, isin, 1, cout, valeur))


def _ligne(r, envelope):
    return next((x for x in r['enveloppes'] if x['enveloppe'] == envelope), None)


def _ecartee(r, envelope):
    return next((x for x in r['non_calculees'] if x['enveloppe'] == envelope), None)


class TestAssiette:
    """D'ou vient la plus-value, et quand refuse-t-on de la calculer."""

    def test_apports_traces_font_l_assiette(self):
        with get_db() as conn:
            _position(conn, 'CTO', 50000)
            _versement(conn, 'CTO', 30000)
            conn.commit()
            r = impot_latent(conn, DATE)
        l = _ligne(r, 'CTO')
        assert l['plus_value'] == 20000
        assert l['source'] == 'apports'

    def test_sans_versement_ni_titre_l_enveloppe_est_ecartee(self):
        # Le Livret A pese 60 000 EUR sans un seul versement saisi : « valeur
        # moins apports » y verrait 60 000 EUR de gain. On prefere ne rien dire.
        with get_db() as conn:
            _position(conn, 'CTO', 50000)
            conn.commit()
            r = impot_latent(conn, DATE)
        assert _ligne(r, 'CTO') is None
        assert 'part de gain est inconnue' in _ecartee(r, 'CTO')['motif']
        assert r['impot'] == 0

    def test_une_enveloppe_ecartee_garde_sa_valeur_au_brut(self):
        with get_db() as conn:
            _position(conn, 'CTO', 50000)
            conn.commit()
            r = impot_latent(conn, DATE)
        assert r['brut'] == 50000                  # elle reste dans le patrimoine
        assert r['valeur_ecartee'] == 50000        # et se compte comme ecartee

    def test_prix_de_revient_en_second_recours(self):
        with get_db() as conn:
            pid = _position(conn, 'PEA', 40000)
            _titre(conn, pid, 30000, 40000)
            conn.commit()
            r = impot_latent(conn, DATE)
        l = _ligne(r, 'PEA')
        assert l['plus_value'] == 10000
        assert l['source'] == 'prix de revient'

    def test_cost_basis_egal_a_la_valeur_n_est_pas_un_prix_de_revient(self):
        # Une case remplie par defaut, pas un prix paye : rien a en tirer.
        with get_db() as conn:
            pid = _position(conn, 'PEA', 40000)
            _titre(conn, pid, 40000, 40000)
            conn.commit()
            r = impot_latent(conn, DATE)
        assert _ligne(r, 'PEA') is None
        assert _ecartee(r, 'PEA') is not None

    def test_prix_de_revient_partiel_chiffre_avec_reserve(self):
        with get_db() as conn:
            pid = _position(conn, 'PEA', 40000)
            _titre(conn, pid, 15000, 25000, isin='FR0000000001')
            _titre(conn, pid, 15000, 15000, isin='FR0000000002')
            conn.commit()
            r = impot_latent(conn, DATE)
        l = _ligne(r, 'PEA')
        assert l['plus_value'] == 10000
        assert '1 ligne sur 2' in l['reserve']

    def test_apports_superieurs_a_la_valeur_signalent_un_journal_incomplet(self):
        # Un livret ne perd pas d'argent : ce sont des retraits qui manquent.
        with get_db() as conn:
            _position(conn, 'Livret Bourso+', 88214, category='Cash & dépôts')
            _versement(conn, 'Livret Bourso+', 149000)
            conn.commit()
            r = impot_latent(conn, DATE)
        assert _ligne(r, 'Livret Bourso+') is None
        assert 'retraits manquent' in _ecartee(r, 'Livret Bourso+')['motif']

    def test_le_prix_de_revient_prime_sur_un_journal_partiel(self):
        # Cas reel du 23/09/2026 : le journal ne porte que les versements
        # recents (5 000), les titres ont coute 45 000. « Valeur moins apports »
        # prenait 45 000 de gain ; le prix de revient en dit 5 000.
        with get_db() as conn:
            pid = _position(conn, 'CTO', 50000)
            _versement(conn, 'CTO', 5000)
            _titre(conn, pid, 45000, 50000)
            conn.commit()
            r = impot_latent(conn, DATE)
        assert _ligne(r, 'CTO')['source'] == 'prix de revient'
        assert _ligne(r, 'CTO')['plus_value'] == pytest.approx(5000)

    def test_sans_prix_de_revient_les_apports_servent(self):
        with get_db() as conn:
            _position(conn, 'CTO', 50000)
            _versement(conn, 'CTO', 30000)
            conn.commit()
            r = impot_latent(conn, DATE)
        assert _ligne(r, 'CTO')['source'] == 'apports'


class TestRegimes:
    def test_pea_prelevements_sociaux_seuls(self):
        with get_db() as conn:
            _position(conn, 'PEA', 50000)
            _versement(conn, 'PEA', 30000)
            conn.commit()
            r = impot_latent(conn, DATE)
        assert _ligne(r, 'PEA')['impot'] == pytest.approx(20000 * PS)

    def test_cto_prelevement_forfaitaire(self):
        with get_db() as conn:
            _position(conn, 'CTO', 50000)
            _versement(conn, 'CTO', 30000)
            conn.commit()
            r = impot_latent(conn, DATE)
        assert _ligne(r, 'CTO')['impot'] == pytest.approx(20000 * PFU)

    def test_livret_a_exonere_meme_sans_apports(self):
        # Le resultat est nul quelle que soit l'assiette : l'absence de flux ne
        # disqualifie pas une enveloppe exoneree.
        with get_db() as conn:
            _position(conn, 'Livret A', 23000, category='Cash & dépôts')
            conn.commit()
            r = impot_latent(conn, DATE)
        l = _ligne(r, 'Livret A')
        assert l is not None and l['impot'] == 0

    def test_assurance_vie_abattement_puis_taux_reduit(self):
        with get_db() as conn:
            _position(conn, 'Assurance-vie', 60000, category='Fond Euro')
            _versement(conn, 'Assurance-vie', 50000)
            conn.commit()
            r = impot_latent(conn, DATE)
        l = _ligne(r, 'Assurance-vie')
        assert l['abattement'] == ABATTEMENT_AV
        assert l['impot'] == pytest.approx((10000 - ABATTEMENT_AV) * (IR_AV + PS))

    def test_abattement_double_pour_un_couple(self):
        with get_db() as conn:
            _position(conn, 'Assurance-vie', 30000, owner='Paul')
            _position(conn, 'Assurance-vie', 30000, owner='Claire')
            _versement(conn, 'Assurance-vie', 25000, owner='Paul')
            _versement(conn, 'Assurance-vie', 25000, owner='Claire')
            conn.commit()
            r = impot_latent(conn, DATE)
        assert _ligne(r, 'Assurance-vie')['abattement'] == 2 * ABATTEMENT_AV

    def test_abattement_superieur_au_gain_annule_l_impot(self):
        with get_db() as conn:
            _position(conn, 'Assurance-vie', 52000)
            _versement(conn, 'Assurance-vie', 50000)
            conn.commit()
            r = impot_latent(conn, DATE)
        assert _ligne(r, 'Assurance-vie')['impot'] == 0

    def test_per_et_immobilier_hors_calcul(self):
        with get_db() as conn:
            _position(conn, 'PER', 25000)
            _versement(conn, 'PER', 15000)
            _position(conn, 'SCPI', 40000, category='SCPI')
            _versement(conn, 'SCPI', 30000)
            conn.commit()
            r = impot_latent(conn, DATE)
        # Des apports connus ne suffisent pas : c'est le regime qui manque.
        assert _ecartee(r, 'PER') is not None
        assert _ecartee(r, 'SCPI') is not None
        assert r['impot'] == 0

    def test_moins_value_ne_produit_pas_d_impot(self):
        with get_db() as conn:
            _position(conn, 'CTO', 20000)
            _versement(conn, 'CTO', 30000)
            conn.commit()
            r = impot_latent(conn, DATE)
        # Apports superieurs a la valeur : ecartee, donc aucun impot negatif.
        assert r['impot'] == 0


class TestTotaux:
    def test_identite_brut_moins_impot(self):
        with get_db() as conn:
            _position(conn, 'PEA', 50000)
            _versement(conn, 'PEA', 30000)
            _position(conn, 'Livret A', 20000, category='Cash & dépôts')
            conn.commit()
            r = impot_latent(conn, DATE)
        assert r['brut'] == 70000
        assert r['net_apres_impot'] == pytest.approx(r['brut'] - r['impot'])

    def test_taux_moyen_rapporte_a_la_plus_value(self):
        with get_db() as conn:
            _position(conn, 'PEA', 50000)
            _versement(conn, 'PEA', 30000)
            conn.commit()
            r = impot_latent(conn, DATE)
        assert r['taux_moyen'] == pytest.approx(PS, abs=1e-4)

    def test_filtrage_par_titulaire(self):
        with get_db() as conn:
            _position(conn, 'CTO', 50000, owner='Paul')
            _versement(conn, 'CTO', 30000, owner='Paul')
            _position(conn, 'CTO', 90000, owner='Claire')
            _versement(conn, 'CTO', 40000, owner='Claire')
            conn.commit()
            r = impot_latent(conn, DATE, owner='Paul')
        assert r['brut'] == 50000
        assert _ligne(r, 'CTO')['plus_value'] == 20000

    def test_arrete_vide(self):
        with get_db() as conn:
            r = impot_latent(conn, DATE)
        assert r['brut'] == 0 and r['impot'] == 0 and r['enveloppes'] == []


class TestEndpoint:
    def test_repond_sur_le_dernier_arrete(self, client):
        with get_db() as conn:
            _position(conn, 'PEA', 50000)
            _versement(conn, 'PEA', 30000)
            conn.commit()
        r = client.get('/api/impot-latent')
        assert r.status_code == 200
        assert r.json['brut'] == 50000
        assert r.json['impot'] == pytest.approx(20000 * PS)

    def test_date_explicite(self, client):
        with get_db() as conn:
            _position(conn, 'PEA', 10000, date='2026-01-31')
            _position(conn, 'PEA', 50000, date=DATE)
            _versement(conn, 'PEA', 30000)
            conn.commit()
        assert client.get('/api/impot-latent?date=2026-01-31').json['brut'] == 10000

    def test_sans_donnees(self, client):
        assert client.get('/api/impot-latent').json['brut'] == 0

    def test_exige_la_session(self):
        app.config['TESTING'] = True
        with app.test_client() as anon:
            assert anon.get('/api/impot-latent').status_code in (302, 401)


class TestValorisation:
    def test_une_position_d_entite_pese_au_brut_et_est_ecartee(self):
        # Sommer positions.value oubliait les entites (valeur 0 en base) :
        # l'immobilier en SCI disparaissait, meme des enveloppes ecartees.
        with get_db() as conn:
            conn.execute("INSERT INTO entities (name, type, gross_assets, debt) VALUES ('SCI', 'SCI', 200000, 0)")
            conn.execute("INSERT INTO positions (date, owner, category, envelope, value, entity, ownership_pct) "
                         "VALUES (?, 'Paul', 'Immobilier', 'SCI', 0, 'SCI', 0.5)", (DATE,))
            conn.commit()
            r = impot_latent(conn, DATE)
        assert r['brut'] == pytest.approx(100000)
        assert _ecartee(r, 'SCI')['valeur'] == pytest.approx(100000)
