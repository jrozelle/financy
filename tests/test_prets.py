"""Prets et echeanciers : capital restant du a une date, dette par entite,
et controle d'un tableau avant de l'accepter."""
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
from services import prets  # noqa: E402
from services.parsers.amortissement import Tableau, Echeance, _verifier  # noqa: E402

H = {'X-CSRF-Token': 'test'}


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


def _tableau(montant=3000.0, mois=3):
    e, crd = [], montant
    for i in range(1, mois + 1):
        crd -= montant / mois
        e.append(Echeance(rang=i, date=f'2026-0{i}-05', capital=montant / mois, interets=10.0, assurance=0.0,
                          crd=round(crd, 2)))
    return Tableau(preteur='Banque', libelle='Prêt test', emprunteur=None, montant=montant, taux=2.0, echeances=e)


def test_capital_restant_du_a_une_date():
    with get_db() as c:
        c.execute("INSERT INTO entities (name, type, gross_assets, debt) VALUES ('SCI', 'SCI', 0, 0)")
        pid = prets.enregistrer(c, _verifier(_tableau()), entity='SCI')
        c.commit()
        assert prets.crd_a(c, pid, '2026-01-01') == 3000.0      # avant la premiere echeance
        assert prets.crd_a(c, pid, '2026-02-10') == 1000.0      # apres la deuxieme
        assert prets.crd_a(c, pid, '2027-01-01') == 0.0
        assert prets.dettes_par_entite(c, '2026-01-05') == {'SCI': 2000.0}


def test_un_tableau_incoherent_est_refuse():
    t = _tableau()
    t.echeances[1].crd += 50                    # une ligne mal lue
    with pytest.raises(ValueError, match='restant dû'):
        _verifier(t)


def test_un_tableau_qui_ne_solde_pas_est_refuse():
    t = _tableau()
    t.echeances.pop()
    with pytest.raises(ValueError, match='solde'):
        _verifier(t)


def test_la_mise_a_jour_propose_la_dette_de_l_echeancier(client):
    with get_db() as c:
        c.execute("INSERT INTO entities (name, type, gross_assets, debt) VALUES ('SCI', 'SCI', 5000, 3000)")
        c.execute("INSERT INTO positions (date, owner, category, envelope, value, entity, ownership_pct) "
                  "VALUES ('2026-01-01', 'Paul', 'Immobilier', 'SCI', 0, 'SCI', 1.0)")
        prets.enregistrer(c, _verifier(_tableau()), entity='SCI')
        c.commit()
    d = client.get('/api/snapshots/update?source=2026-01-01&cible=2026-02-10').get_json()
    assert d['entites'][0]['dette_echeancier'] == 1000.0


def test_l_import_refuse_un_fichier_qui_n_est_pas_un_pdf(client):
    import io
    r = client.post('/api/prets/import', data={'file': (io.BytesIO(b'hello'), 'x.pdf')},
                    headers=H, content_type='multipart/form-data')
    assert r.status_code == 400


def test_projection_totalise_les_prets():
    with get_db() as c:
        prets.enregistrer(c, _verifier(_tableau()), entity=None)
        prets.enregistrer(c, _verifier(_tableau(6000)), entity=None)
        c.commit()
        pj = prets.projection(c, depuis='2026-01-01')
    assert pj['total'][0] == 9000.0 and pj['total'][-1] == 0.0
