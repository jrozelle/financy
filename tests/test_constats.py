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
