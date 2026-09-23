"""Constats du conseil : des faits verifiables, pas des recommandations."""
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
from services.advisor.constats import constats, PLAFONDS  # noqa: E402

D = '2026-09-02'


@pytest.fixture(autouse=True)
def fresh_db():
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)
    init_db()
    yield
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)


def _pos(c, envelope, value, owner='Paul', category='Cash & dépôts', debt=0, establishment='Bourso'):
    c.execute('INSERT INTO positions (date, owner, category, envelope, establishment, value, debt) '
              'VALUES (?,?,?,?,?,?,?)', (D, owner, category, envelope, establishment, value, debt))


def _titres(r, niveau=None):
    return [k['titre'] for k in r['constats'] if niveau is None or k['niveau'] == niveau]


class TestLivrets:
    def test_au_dessus_du_plafond_signale(self):
        with get_db() as c:
            _pos(c, 'Livret A', 49000, owner='Claire'); c.commit()
            r = constats(c, D)
        assert any('au-dessus du plafond' in t for t in _titres(r, 'alerte'))

    def test_interets_capitalises_toleres(self):
        # Un livret plein dont les interets ont depasse le plafond est normal.
        with get_db() as c:
            _pos(c, 'Livret A', PLAFONDS['Livret A'] * 1.03); c.commit()
            r = constats(c, D)
        assert not _titres(r, 'alerte')

    def test_place_libre_et_livret_fiscalise_du_meme_titulaire(self):
        with get_db() as c:
            _pos(c, 'Livret A', 10000)
            _pos(c, 'Livret Bourso+', 30000); c.commit()
            r = constats(c, D)
        action = [k for k in r['constats'] if k['niveau'] == 'action']
        assert action and action[0]['montant'] == pytest.approx(PLAFONDS['Livret A'] - 10000)

    def test_pas_de_transfert_entre_titulaires(self):
        # Le plafond est personnel : la place de Claire ne se remplit pas avec
        # le livret fiscalise de Paul.
        with get_db() as c:
            _pos(c, 'Livret A', 10000, owner='Claire')
            _pos(c, 'Livret Bourso+', 30000, owner='Paul'); c.commit()
            r = constats(c, D)
        assert not _titres(r, 'action')

    def test_livrets_pleins_rien_a_deplacer(self):
        with get_db() as c:
            _pos(c, 'Livret A', PLAFONDS['Livret A'])
            _pos(c, 'Livret Bourso+', 30000); c.commit()
            r = constats(c, D)
        assert not _titres(r, 'action')


class TestDiscretion:
    def test_les_montants_sont_marques_pour_le_front(self):
        # Formates ici, ils echapperaient au mode discretion.
        with get_db() as c:
            _pos(c, 'Livret A', 49000, owner='Claire'); c.commit()
            k = constats(c, D)['constats'][0]
        assert '⟦49000' in k['detail'] and 'EUR' not in k['detail']


class TestAutres:
    def test_especes_dormantes_dans_un_pea(self):
        with get_db() as c:
            _pos(c, 'PEA', 30000, owner='Claire', establishment='CA31'); c.commit()
            r = constats(c, D)
        assert any("espèces non investies dans le PEA" in t for t in _titres(r, 'action'))

    def test_poussiere_ignoree(self):
        with get_db() as c:
            _pos(c, 'PEA', 120); c.commit()
            assert not constats(c, D)['constats']

    def test_tresorerie_de_societe_pas_une_epargne_qui_dort(self):
        # Le compte porte le nom d'une entite declaree, en libelle.
        with get_db() as c:
            c.execute("INSERT INTO entities (name, type, gross_assets, debt) VALUES ('Holding Exemple','Holding',0,0)")
            c.execute("INSERT INTO positions (date, owner, category, envelope, value, label) "
                      "VALUES (?, 'Paul', 'Cash & dépôts', 'Compte courant', 20000, 'Holding Exemple')", (D,))
            c.commit()
            assert not constats(c, D)['constats']

    def test_comptes_courants_personnels_signales(self):
        with get_db() as c:
            _pos(c, 'Compte courant', 20000); c.commit()
            assert any('comptes courants' in t for t in _titres(constats(c, D)))

    def test_dette_superieure_a_la_valeur(self):
        with get_db() as c:
            _pos(c, 'Holding', 150000, category='Parts sociales', debt=160000); c.commit()
            r = constats(c, D)
        assert any('la dette dépasse la valeur' in t for t in _titres(r))

    def test_filtre_titulaire(self):
        with get_db() as c:
            _pos(c, 'Livret A', 49000, owner='Claire')
            _pos(c, 'PEA', 5000, owner='Paul'); c.commit()
            r = constats(c, D, owner='Paul')
        assert not any('Claire' in t for t in _titres(r))

    def test_alerte_avant_action_avant_info(self):
        with get_db() as c:
            _pos(c, 'Livret A', 49000, owner='Claire')
            _pos(c, 'PEA', 5000, owner='Claire')
            _pos(c, 'Livret Bourso+', 50000, owner='Paul'); c.commit()
            niveaux = [k['niveau'] for k in constats(c, D)['constats']]
        assert niveaux == sorted(niveaux, key=['alerte', 'action', 'info'].index)


def test_endpoint_exige_la_session():
    app.config['TESTING'] = True
    with app.test_client() as anon:
        assert anon.get('/api/advisor/constats').status_code in (302, 401)


class TestLivretsDistincts:
    def test_deux_livrets_a_d_une_meme_titulaire_ne_depassent_rien(self):
        # Les Livret A des enfants, tenus par leur mere : 23 000 et 26 000 €,
        # chacun sous le plafond. Leur somme n'est pas un depassement.
        with get_db() as c:
            _pos(c, 'Livret A', 23000, owner='Claire')
            _pos(c, 'Livret A', 26000, owner='Claire')
            c.commit()
            r = constats(c, D)
        assert not [k for k in r['constats'] if k['niveau'] == 'alerte']

    def test_un_livret_seul_au_dela_du_plafond_reste_signale(self):
        with get_db() as c:
            _pos(c, 'Livret A', 40000, owner='Claire'); c.commit()      # 1,74 fois le plafond
            r = constats(c, D)
        assert any('au-dessus du plafond' in k['titre'] for k in r['constats'])


class TestGarderOuRembourser:
    def _base(self, conn, entite_type='Indivision'):
        conn.execute("INSERT INTO entities (name, type) VALUES ('Maison', ?)", (entite_type,))
        conn.execute("INSERT INTO positions (date, owner, category, envelope, value, entity) "
                     "VALUES ('2026-09-01', 'Paul', 'Immobilier', 'Immobilier', 0, 'Maison')")
        conn.execute("INSERT INTO prets (id, libelle, entity, montant, taux, debut, fin) "
                     "VALUES (1, 'Prêt maison', 'Maison', 100000, 1.1, '2026-01-05', '2036-12-05')")
        crd = 100000
        for i in range(1, 13):
            crd -= 700
            conn.execute('INSERT INTO pret_echeances VALUES (1, ?, ?, 700, 90, 0, ?)',
                         (i, f'2027-{i:02d}-05', crd))

    def _credits(self, owner=None):
        from services.advisor.constats import constats
        with get_db() as conn:
            return [k for k in constats(conn, '2026-09-01', owner)['constats'] if k['onglet'] == 'credits']

    def test_garder_est_la_norme_et_le_seuil_est_le_taux_du_contrat(self):
        with get_db() as conn:
            self._base(conn)
        (k,) = self._credits()
        assert k['niveau'] == 'info' and 'le garder' in k['titre']
        assert '1,1 % net fait mieux' in k['detail']

    def test_une_sci_garde_son_levier(self):
        with get_db() as conn:
            self._base(conn, 'SCI')
        (k,) = self._credits()
        assert 'levier' in k['detail'] and 'fait mieux' not in k['detail']

    def test_le_credit_d_une_autre_personne_n_apparait_pas(self):
        with get_db() as conn:
            self._base(conn)
        assert self._credits(owner='Claire') == []


class TestNetDesEntites:
    def test_la_tresorerie_saisie_au_nom_de_l_entite_compte(self):
        from services.advisor.constats import constats
        with get_db() as conn:
            conn.execute("INSERT INTO entities (name, type) VALUES ('Holding H', 'Holding')")
            conn.execute("INSERT INTO entity_snapshots (entity_name, date, gross_assets, debt) VALUES ('Holding H', '2026-04-01', 150000, 160000)")
            conn.execute("INSERT INTO positions (date, owner, category, envelope, value, entity, ownership_pct, debt_pct) "
                         "VALUES ('2026-09-01', 'Paul', 'Parts sociales', 'Holding', 0, 'Holding H', 1, 1)")
            conn.execute("INSERT INTO positions (date, owner, category, envelope, label, value) "
                         "VALUES ('2026-09-01', 'Paul', 'Cash & dépôts', 'Compte courant', 'Holding H', 7500)")
            ks = [k for k in constats(conn, '2026-09-01')['constats'] if 'dette dépasse' in k['titre']]
        assert len(ks) == 1 and ks[0]['montant'] == 2500
        assert 'datent du 01/04/2026' in ks[0]['detail']
