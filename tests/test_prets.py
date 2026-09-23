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


def test_calendrier_prochaines_echeances_et_cumul_annuel():
    with get_db() as c:
        prets.enregistrer(c, _verifier(_tableau()), entity=None)
        c.commit()
        cal = prets.calendrier(c, depuis='2026-01-10')
    assert [e['rang'] for e in cal['prochaines']] == [2, 3]
    assert cal['annees'] == [{'annee': '2026', 'capital': 2000.0, 'interets': 20.0, 'assurance': 0.0,
                              'echeances': 2, 'crd_fin': 0.0}]


def test_un_credit_defini_a_la_main_a_son_echeancier(client):
    r = client.post('/api/prets', json={'libelle': 'Prêt auto', 'montant': 12000, 'taux': 3.5, 'mois': 48,
                                       'premiere': '2026-10-05'}, headers=H)
    assert r.status_code == 201, r.get_json()
    p = client.get('/api/prets?date=2026-09-30').get_json()['prets'][0]
    assert p['crd'] == 12000 and p['fin'] == '2030-09-05' and p['echeances'] == 48
    assert p['mensualite'] == pytest.approx(268.27, abs=0.02)     # annuite a 3,5 % sur 48 mois


def test_differe_partiel_puis_amortissement():
    t = _verifier(prets.echeancier_calcule(12000, 3.0, 24, '2026-01-05', differe=6, type_differe='partiel'))
    e = t.echeances
    assert all(x.capital == 0 and x.crd == 12000 for x in e[:6])          # interets seuls
    assert e[0].interets == 30.0 and e[6].capital > 0 and e[-1].crd == 0


def test_differe_total_capitalise_les_interets():
    t = _verifier(prets.echeancier_calcule(12000, 3.0, 24, '2026-01-05', differe=6, type_differe='total'))
    e = t.echeances
    assert e[0].crd == 12030.0 and e[5].crd > 12150                        # le capital grossit
    assert all(x.interets == 0 for x in e[:6]) and e[-1].crd == 0


def test_le_resume_dit_le_differe(client):
    client.post('/api/prets', json={'libelle': 'Travaux', 'montant': 12000, 'taux': 3, 'mois': 24,
                                    'premiere': '2026-10-05', 'differe': 6, 'type_differe': 'partiel'}, headers=H)
    p = client.get('/api/prets?date=2026-09-30').get_json()['prets'][0]
    assert p['differe'] == {'type': 'partiel', 'jusqu_au': '2027-03-05'}
    assert p['echeance_du_mois'] == 30.0 and p['mensualite'] > 600


def test_ira_plafond_legal_et_renonciation(client):
    assert prets.ira(100000, 1.2) == 600.0          # 6 mois d'interets < 3 %
    assert prets.ira(100000, 8.0) == 3000.0         # 3 % du restant du < 6 mois
    assert prets.ira(100000, 1.2, 'aucune') == 0.0
    client.post('/api/prets', json={'libelle': 'Immo', 'montant': 100000, 'taux': 1.2, 'mois': 120,
                                    'premiere': '2026-10-05'}, headers=H)
    pid = client.get('/api/prets').get_json()['prets'][0]['id']
    assert client.get('/api/prets?date=2026-09-30').get_json()['prets'][0]['ira'] == 600.0
    client.patch(f'/api/prets/{pid}', json={'ira': 'aucune'}, headers=H)
    assert client.get('/api/prets?date=2026-09-30').get_json()['prets'][0]['ira'] == 0.0


def test_taux_deduit_de_l_echeancier():
    with get_db() as c:
        pid = prets.enregistrer(c, _verifier(prets.echeancier_calcule(100000, 2.4, 120, '2026-01-05')))
        c.execute('UPDATE prets SET taux=NULL WHERE id=?', (pid,)); c.commit()
        p = prets.resume(c, '2025-12-01')['prets'][0]
    assert p['taux_deduit'] and p['taux_retenu'] == pytest.approx(2.4, abs=0.02)


class TestCreditAgricoleInFine:
    TEXTE = """AVIS DE RÉALISATION
CREDIT AGRICOLE 18.03.2026
Jean Dupont S.A.S. HOLDING EXEMPLE
Taux : 4,0000 TAUX FIXE Montant déjà réalisé :130 000,00
Différé total : Montant du crédit :140 000,00
N° Date Capital Restant dû Montant échéance Capital amorti Intérêts
1 05.04.2026 140 000,00 440,32 0,00 440,32
2 05.05.2026 140 000,00 466,67 0,00 466,67
3 05.06.2026 0,00 140 466,67 140 000,00 466,67
"""

    def test_in_fine_lu_et_verifie(self):
        from services.parsers.amortissement import _credit_agricole
        t = _verifier(_credit_agricole(None, self.TEXTE))
        assert t.libelle == 'Prêt in fine' and t.emprunteur == 'HOLDING EXEMPLE'
        assert t.montant == 140000 and t.taux == 4.0
        assert [e.capital for e in t.echeances] == [0, 0, 140000] and t.echeances[-1].crd == 0

    def test_une_tranche_seule_est_refusee(self):
        from services.parsers.amortissement import _credit_agricole
        with pytest.raises(ValueError):
            _verifier(_credit_agricole(None, self.TEXTE.replace('140 000,00 440,32', '130 000,00 408,87')))
