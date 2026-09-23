"""Revue B2 : tresorerie d'une entite — solde d'ouverture du premier releve,
tous les prets de l'entite, projection fiscale sur les mois couverts,
validation des saisies de parts et d'exercices."""
import pytest

from tests.test_api import client, fresh_db, CSRF_HEADERS  # noqa: F401

from models import get_db
from services import tresorerie_entite as t
from services.parsers.releve_bancaire import Releve, Operation

H = CSRF_HEADERS
SCI = 'SCI Exemple'


def _releve(debut, fin, solde_initial, ops, compte='0001'):
    return Releve('Qonto', compte, debut, fin, solde_initial,
                  solde_initial + sum(m for _, _, m in ops), [Operation(d, l, m) for d, l, m in ops])


class TestSoldeInitial:
    def test_le_solde_d_ouverture_compte_dans_la_tresorerie(self):
        with get_db() as conn:
            conn.execute("INSERT INTO entities (name) VALUES (?)", (SCI,))
            t.enregistrer(conn, SCI, _releve('2026-02-01', '2026-02-28', 5000,
                                             [('2026-02-10', 'SCPI A DISTRIBUTION', 300.0)]), 'fev.pdf')
            assert t.tresorerie_a(conn, SCI, '2026-02-28')['montant'] == 5300
            assert t.bilan(conn, SCI)['tresorerie'] == 5300
            # Un releve plus ancien importe apres coup : son ouverture prime.
            t.enregistrer(conn, SCI, _releve('2026-01-01', '2026-01-31', 4800,
                                             [('2026-01-10', 'SCPI A DISTRIBUTION', 200.0)]), 'jan.pdf')
            assert t.tresorerie_a(conn, SCI, '2026-02-28')['montant'] == 5300
            # Un releve plus recent ne change pas le solde retenu.
            t.enregistrer(conn, SCI, _releve('2026-03-01', '2026-03-31', 5300,
                                             [('2026-03-10', 'Frais bancaires', -10.0)]), 'mars.pdf')
            assert t.bilan(conn, SCI)['tresorerie'] == 5290
            r = conn.execute('SELECT date, solde FROM entite_soldes_initiaux').fetchall()
        assert [(x['date'], x['solde']) for x in r] == [('2026-01-01', 4800)]

    def test_deux_comptes_s_additionnent(self):
        with get_db() as conn:
            t.enregistrer(conn, SCI, _releve('2026-01-01', '2026-01-31', 1000, [('2026-01-05', 'x', 1.0)]), 'a.pdf')
            t.enregistrer(conn, SCI, _releve('2026-01-01', '2026-01-31', 2000, [('2026-01-06', 'y', 1.0)],
                                             compte='0002'), 'b.pdf')
            assert t.tresorerie_a(conn, SCI, '2026-01-31')['montant'] == 3002


class TestTousLesPrets:
    def test_le_bilan_agrege_les_prets_de_l_entite(self):
        with get_db() as conn:
            conn.execute("INSERT INTO prets (id, libelle, entity, montant, taux) VALUES (1, 'P1', ?, 100000, 2)", (SCI,))
            conn.execute("INSERT INTO prets (id, libelle, entity, montant, taux) VALUES (2, 'P2', ?, 50000, 4)", (SCI,))
            for pid, crd in ((1, 60000), (2, 20000)):
                conn.execute('INSERT INTO pret_echeances VALUES (?, 1, ?, 100, 50, 5, ?)', (pid, '2026-01-05', crd))
            t.enregistrer(conn, SCI, _releve('2026-01-01', '2026-01-31', 0, [('2026-01-05', 'FEDERAL FINANCE', -310.0)]),
                          'r.pdf')
            c = t.bilan(conn, SCI, mois=1)['credit']
        assert c['prets'] == 2 and c['capital'] == 200 and c['interets'] == 100 and c['assurance'] == 10
        assert c['crd'] == 80000
        # Taux moyen pondere par le restant du : (60 000 x 2 + 20 000 x 4) / 80 000.
        assert c['taux'] == pytest.approx(2.5)


class TestProjectionFiscale:
    def test_annualisee_sur_les_mois_couverts(self):
        with get_db() as conn:
            conn.execute("INSERT INTO entite_exercices (entity, fin, resultat) VALUES (?, '2025-12-31', 0)", (SCI,))
            ops = [(f'2026-0{m}-10', 'SCPI A DISTRIBUTION', 100.0) for m in (1, 2, 3)]
            ops.append(('2026-03-15', 'Frais bancaires', -30.0))
            t.enregistrer(conn, SCI, _releve('2026-01-01', '2026-03-31', 0, ops), 'r.pdf')
            f = t.bilan(conn, SCI)['fiscal']          # fenetre de 12 mois, 3 couverts
        assert f['projection']['revenus'] == 1200 and f['projection']['frais'] == 120
        assert f['projection']['resultat'] == 1080


class TestSaisies:
    @pytest.fixture(autouse=True)
    def _entite(self):
        with get_db() as conn:
            conn.execute("INSERT INTO entities (name) VALUES (?)", (SCI,))

    def test_parts_au_format_francais(self, client):
        r = client.put(f'/api/entites/{SCI}/parts', headers=H, json={'parts': [
            {'nom': 'SCPI A', 'parts': '12,5', 'montant_souscrit': '2 500,00', 'prix_souscription': '200'}]})
        assert r.status_code == 200, r.get_json()
        l = r.get_json()['lignes'][0]
        assert l['parts'] == 12.5 and l['montant_souscrit'] == 2500

    @pytest.mark.parametrize('corps', [
        {'parts': ['SCPI A']},
        {'parts': [{'nom': 'SCPI A', 'parts': 'abc'}]},
        {'parts': [{'nom': 'SCPI A', 'parts': 1}, {'nom': 'SCPI A', 'parts': 2}]},
        {'parts': [{'nom': 5, 'parts': 1}]},
        ['pas', 'un', 'objet'],
    ])
    def test_parts_invalides(self, client, corps):
        assert client.put(f'/api/entites/{SCI}/parts', headers=H, json=corps).status_code == 400

    def test_exercices_au_format_francais_et_doublons(self, client):
        r = client.put(f'/api/entites/{SCI}/exercices', headers=H,
                       json={'exercices': [{'fin': '2025-12-31', 'resultat': '-1 200,50'}]})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['exercices'][0]['resultat'] == -1200.5
        r = client.put(f'/api/entites/{SCI}/exercices', headers=H, json={'exercices': [
            {'fin': '2025-12-31', 'resultat': 1}, {'fin': '2025-12-31', 'resultat': 2}]})
        assert r.status_code == 400
        assert client.put(f'/api/entites/{SCI}/exercices', headers=H, json={'exercices': [1]}).status_code == 400

    def test_reclasser_corps_invalide(self, client):
        assert client.patch('/api/entites/operations/1', headers=H, json=['frais']).status_code == 400
        assert client.patch('/api/entites/operations/1', headers=H, json={'nature': ['frais']}).status_code == 400
