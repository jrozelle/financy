"""Tresorerie d'une entite : lecture verifiee des releves, classement des
operations, bilan du levier."""
import os
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
from services import tresorerie_entite as t  # noqa: E402
from services.parsers.releve_bancaire import _qonto, Releve, Operation, ReleveIllisible  # noqa: E402

H = {'X-CSRF-Token': 'test'}

QONTO = """Relevés de compte
Du 01/10/2025 au 31/10/2025
SCI Test
Solde au 01/10 + 485.59 EUR
Entrées + 1760.12 EUR
Sorties - 1540.25 EUR
BIC: QNTOFRP1XXX Solde au 31/10 + 612.20 EUR
Date de valeur Transactions Débit Crédit
02/10 Paul MARTIN + 1100.00 EUR
Appro SCI
06/10 FEDERAL FINANCE - 1540.25 EUR
705A027A05830060202510050001PECHEAN
24/10 SCPI IMMORENTE + 812.40 EUR
SCPI IMMORENTE DISTRIBUTION 2025 TRIM. 3 SCI
Toutes les cartes de votre compte Qonto sont compatibles avec Apple Pay et Google Pay.
Olinda est agréé par l'Autorité de Contrôle Prudentiel
"""


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


class TestLectureQonto:
    def test_operations_signees_et_motif(self):
        r = _qonto(QONTO)
        assert [o.montant for o in r.operations] == [1100.0, -1540.25, 812.40]
        assert r.operations[0].date == '2025-10-02'
        assert 'Appro SCI' in r.operations[0].libelle
        # Le pied de page ne se colle a aucun motif, ni la reference du prelevement.
        assert all('Olinda' not in o.libelle and 'PECHEAN' not in o.libelle for o in r.operations)

    def test_un_total_faux_est_refuse(self):
        with pytest.raises(ReleveIllisible):
            _qonto(QONTO.replace('Entrées + 1760.12', 'Entrées + 1760.13'))


class TestClassement:
    @pytest.mark.parametrize('libelle,montant,nature', [
        ('Paul MARTIN — Appro SCI', 800, 'apport'),
        ('M Martin Paul Ou Mlle Durand', 500, 'apport'),
        ('FEDERAL FINANCE', -1540.25, 'echeance'),
        ('SCPI IMMORENTE — SCPI IMMORENTE DISTRIBUTION 2025 TRIM. 3 SCI — EXEMPLIA', 812.40, 'revenu'),
        ('SCPI IMMORENTE — DISTRIB CAPITAL NUMERO 27 SCI — EXEMPLIA', 212.40, 'revenu_exceptionnel'),
        ('ActivImmo — ActivImmo - Plus-value du 8 septembre 2025', 84.11, 'revenu_exceptionnel'),
        ('Virement Vir Inst de Exempli?a', 1400, 'interne'),
        ('Exemplia — transfert compte courant', -1400, 'interne'),
        ('CABINET — FACT-202601-07038', -55.01, 'frais'),
        ('Inconnu', -12, 'autre'),
    ])
    def test_nature(self, libelle, montant, nature):
        assert t.classer(libelle, montant, 'Exemplia', {'Paul', 'Claire'}) == nature


def _releve(ops):
    return Releve('Qonto', '0001', '2026-01-01', '2026-01-31', 0, sum(m for _, _, m in ops),
                  [Operation(d, l, m) for d, l, m in ops])


class TestBilan:
    def _base(self, conn):
        conn.execute("INSERT INTO entities (name, type) VALUES ('SCI T', 'SCI')")
        conn.execute("INSERT INTO entity_snapshots (entity_name, date, gross_assets, debt) VALUES ('SCI T', '2026-01-01', 100000, 100000)")
        conn.execute("INSERT INTO prets (id, libelle, entity, montant, taux) VALUES (1, 'P', 'SCI T', 100000, 5)")
        for mois in ('01', '02'):
            conn.execute('INSERT INTO pret_echeances VALUES (1, ?, ?, 300, 400, 0, 99000)', (int(mois), f'2026-{mois}-05'))

    def test_levier(self):
        with get_db() as conn:
            self._base(conn)
            ops = []
            for mois in ('01', '02'):
                ops += [(f'2026-{mois}-02', 'Paul — Appro', 400.0), (f'2026-{mois}-05', 'FEDERAL FINANCE', -700.0),
                        (f'2026-{mois}-20', 'SCPI X DISTRIBUTION', 350.0)]
            ajoutees, deja = t.enregistrer(conn, 'SCI T', _releve(ops), 'r.pdf', {'Paul'})
            assert (ajoutees, deja) == (6, 0)
            # Reimporter n'ajoute rien.
            assert t.enregistrer(conn, 'SCI T', _releve(ops), 'r.pdf', {'Paul'}) == (0, 6)
            b = t.bilan(conn, 'SCI T', mois=2)
        i = b['indicateurs']
        assert i['couverture'] == pytest.approx(0.5)
        assert i['apports'] == 800 and i['effort_mensuel'] == pytest.approx(350)
        assert b['credit']['capital'] == 600 and b['credit']['interets'] == 800
        assert i['capital_par_euro_apporte'] == pytest.approx(0.75)
        assert b['tresorerie'] == pytest.approx(100)


class TestRoutes:
    def test_refuse_un_fichier_qui_n_est_pas_un_pdf(self, client):
        import io
        r = client.post('/api/entites/releves', headers=H,
                        data={'file': (io.BytesIO(b'hello'), 'r.pdf')}, content_type='multipart/form-data')
        assert r.status_code == 400

    def test_reclasser(self, client):
        with get_db() as conn:
            conn.execute("INSERT INTO entite_operations (id, entity, date, libelle, montant, nature) "
                         "VALUES (1, 'SCI T', '2026-01-01', 'x', -10, 'autre')")
        assert client.patch('/api/entites/operations/1', json={'nature': 'frais'}, headers=H).status_code == 200
        assert client.patch('/api/entites/operations/1', json={'nature': 'nimporte'}, headers=H).status_code == 400
        assert client.patch('/api/entites/operations/99', json={'nature': 'frais'}, headers=H).status_code == 404
        assert client.get('/api/entites/tresorerie').get_json()['entites'][0]['totaux']['frais'] == -10


class TestEpargneMensuelle:
    def test_la_mediane_ignore_un_versement_exceptionnel(self):
        from services.contribution import epargne_mensuelle
        with get_db() as conn:
            for mois, montant in (('03', 100000), ('04', 3000), ('05', 3200), ('06', 2800), ('07', 3100), ('08', 2900)):
                conn.execute("INSERT INTO flux (date, owner, envelope, type, amount) VALUES (?, 'Paul', 'PEA', 'Versement', ?)",
                             (f'2026-{mois}-15', montant))
            e = epargne_mensuelle(conn, '2026-09-23')
        assert [m['apports'] for m in e['mois']] == [100000, 3000, 3200, 2800, 3100, 2900]
        assert e['mediane'] == pytest.approx(3050)


class TestEpargneNouvelle:
    """Un DCA depuis un livret n'est pas de l'epargne ; un compte qui entre
    dans le suivi non plus ; le salaire qui gonfle un livret, si."""

    def _pos(self, conn, date, envelope, value, label=None, category='Cash & dépôts'):
        conn.execute("INSERT INTO positions (date, owner, category, envelope, establishment, label, value) "
                     "VALUES (?, 'Paul', ?, ?, 'Banque', ?, ?)", (date, category, envelope, label, value))

    def test_dca_et_compte_nouveau_ne_comptent_pas(self):
        from services.contribution import epargne_nouvelle
        with get_db() as conn:
            self._pos(conn, '2026-08-01', 'Livret A', 10000)
            self._pos(conn, '2026-08-01', 'PEA', 5000, category='Actions')
            # Un mois plus tard : 3 000 € de DCA vers le PEA sont partis du
            # livret, qui a aussi recu 1 000 € de salaire ; un LDDS entre dans le suivi.
            self._pos(conn, '2026-08-31', 'Livret A', 8000)
            self._pos(conn, '2026-08-31', 'PEA', 8000, category='Actions')
            self._pos(conn, '2026-08-31', 'LDDS', 12000)
            conn.execute("INSERT INTO flux (date, owner, envelope, type, amount) VALUES ('2026-08-15', 'Paul', 'PEA', 'Versement', 3000)")
            e = epargne_nouvelle(conn, '2026-09-01')
        (p,) = e['periodes']
        assert p['epargne'] == 1000 and p['versements'] == 3000


class TestParts:
    def _entite(self, conn):
        conn.execute("INSERT INTO entities (name, type) VALUES ('SCI T', 'SCI')")

    def test_valeur_au_prix_de_retrait_et_estimation(self, client):
        with get_db() as conn:
            self._entite(conn)
        r = client.put('/api/entites/SCI T/parts', headers=H, json={'parts': [
            {'nom': 'A', 'parts': 100, 'montant_souscrit': 34000, 'prix_souscription': 340, 'prix_retrait': 306},
            {'nom': 'B', 'parts': 50, 'montant_souscrit': 10000, 'prix_souscription': 200}]})
        assert r.status_code == 200
        d = r.get_json()
        b = next(l for l in d['lignes'] if l['nom'] == 'B')
        assert b['retrait_estime'] and b['prix_retrait_retenu'] == 180
        assert d['valeur_retrait'] == 30600 + 9000 and d['montant_souscrit'] == 44000

    def test_refus(self, client):
        with get_db() as conn:
            self._entite(conn)
        assert client.put('/api/entites/SCI T/parts', headers=H, json={'parts': [{'nom': 'A', 'parts': 0}]}).status_code == 400
        assert client.put('/api/entites/Inconnue/parts', headers=H, json={'parts': []}).status_code == 404

    def test_la_mise_a_jour_propose_parts_plus_tresorerie(self, client):
        with get_db() as conn:
            self._entite(conn)
            conn.execute("INSERT INTO entity_snapshots (entity_name, date, gross_assets, debt) VALUES ('SCI T', '2026-08-31', 44000, 40000)")
            conn.execute("INSERT INTO positions (date, owner, category, envelope, value, entity) "
                         "VALUES ('2026-08-31', 'Paul', 'SCPI', 'SCI', 0, 'SCI T')")
            conn.execute("INSERT INTO entite_operations (entity, date, libelle, montant, nature) "
                         "VALUES ('SCI T', '2026-08-15', 'x', 1500, 'revenu')")
            conn.execute("INSERT INTO entite_parts (entity, nom, parts, montant_souscrit, prix_souscription, prix_retrait) "
                         "VALUES ('SCI T', 'A', 100, 44000, 440, 396)")
        d = client.get('/api/snapshots/update?source=2026-08-31&cible=2026-09-30').get_json()
        e = next(x for x in d['entites'] if x['name'] == 'SCI T')
        assert e['valeur_proposee'] == 39600 + 1500


class TestImpotSocietes:
    def test_bareme(self):
        assert t.impot_societes(-100) == 0
        assert t.impot_societes(10000) == 1500
        assert t.impot_societes(52500) == 42500 * 0.15 + 10000 * 0.25

    def test_deficit_reporte_absorbe_le_benefice(self, client):
        with get_db() as conn:
            conn.execute("INSERT INTO entities (name, type) VALUES ('SCI T', 'SCI')")
        r = client.put('/api/entites/SCI T/exercices', headers=H,
                       json={'exercices': [{'fin': '2025-12-31', 'resultat': -5264.28, 'source': 'liasse'}]})
        assert r.status_code == 200
        with get_db() as conn:
            ops = [('2026-01-10', 'SCPI X DISTRIBUTION', 1000.0), ('2026-02-10', 'SCPI X DISTRIBUTION', 1000.0)]
            t.enregistrer(conn, 'SCI T', _releve(ops), 'r.pdf')
            f = t.bilan(conn, 'SCI T', mois=2)['fiscal']
        assert f['annee'] == '2026' and f['deficit_reportable'] == 5264.28
        assert f['projection']['resultat'] == 2000 and f['impot'] == 0
        assert f['deficit_apres'] == pytest.approx(3264.28)

    def test_exercice_invalide(self, client):
        with get_db() as conn:
            conn.execute("INSERT INTO entities (name, type) VALUES ('SCI T', 'SCI')")
        assert client.put('/api/entites/SCI T/exercices', headers=H,
                          json={'exercices': [{'fin': 'hier', 'resultat': 1}]}).status_code == 400
