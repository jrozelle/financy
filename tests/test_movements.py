"""Tests des parsers de mouvements et de l'import."""
import io
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
from services.parsers.movements import (parse_avis_opere, parse_releve_especes,  # noqa: E402
                                        parse_movements, _num, _flat)

# Gabarits reels reduits a l'essentiel, mise en page conservee.
AVIS_ACHAT = """                                    OPERATION DE BOURSE
                                                                le 30/01/2024
Références de votre compte titres
99999 11111 00000000001               Compte PEA
ACHAT COMPTANT
ACTION
  Date et heure
locale d'exécution         Quantité        Informations sur la valeur       Informations sur l'exécution
    29/01/2024                 25          ETF EXEMPLE MONDE C              Référence :        000000000001
                                           Code ISIN :     FR0000000001     Cours exécuté :        40,000 EUR
                                                                            Lieu d'exécution :  EURONEXT PARIS
                Montant brut             Commission          Frais (¨)      Montant net au débit de votre compte
              1 000,00 EUR                 5,00 EUR                                      1 005,00 EUR
"""

AVIS_VENTE = """                                    OPERATION DE BOURSE
99999 11111 00000000001               Compte PEA
VENTE COMPTANT
ACTION
    02/10/2025                 2           ACTION EXEMPLE                   Référence :        000000000002
                                           Code ISIN :     FR0000000002     Cours exécuté :        250,00 EUR
                                                                            Lieu d'exécution :  EURONEXT PARIS
                Montant brut             Commission          Frais (¨)      Montant net au crédit de votre compte
                500,00 EUR                 2,50 EUR                                        497,50 EUR
"""

AVIS_DEVISE = """                                    OPERATION DE BOURSE
99999 22222 00000000002               Résident Français
ACHAT COMPTANT ETR
ACTION
    28/07/2026                 4           ACTION EXEMPLE US                Référence :   000000000003
                                           Code ISIN :     US0000000003     Cours exécuté :   500,00 USD
                                                                            Lieu d'exécution : NEW YORK STOCK EXCHANGE I
  Montant transaction brut       Intérêts     total brut      Courtages     Montant transaction net
        2 000,00 USD            0,00 USD     2 000,00 USD      0,00 USD          2 000,00 USD
                                 ACHAT DEVISES A TERME     Cours de change   Montant transaction net contrevalorisé
                                  Contrevalorisation en EURO   1,25000000                  1 600,00 EUR
                                                 Commission     Frais divers     Montant total des frais
                                                   5,00 EUR       0,00 EUR              5,00 EUR
                                                            Montant net au débit de votre compte
                                                                        1 605,00 EUR
"""

RELEVE = """                       RELEVE COMPTE ESPECES : JANVIER 2024
Références de votre compte espèces
99999 11111 00000000003                Compte PEA
 Date de
 compta.        Libellé de l'opération          Quantité   Nom de la valeur     Débit EUR          Crédit EUR
 31/12/2023                                  ANCIEN SOLDE                                              0,00
 26/01/2024 VIR VIREMENT CREATION COMPTE                                                              300,00
 26/01/2024 VIR Virement interne depuis Compte p                                                    1 000,00
 29/01/2024 ACHAT COMPTANT                            25   ETF EXEMPLE           1 005,00
 31/01/2024                                  NOUVEAU SOLDE                                            295,00
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


class TestNum:
    def test_format_francais(self):
        assert _num('1 234,56') == pytest.approx(1234.56)

    def test_millier_point(self):
        """Le format 2026 separe les milliers par un point."""
        assert _num('1.717,50') == pytest.approx(1717.50)

    def test_taux_de_change(self):
        assert _num('1,13740500') == pytest.approx(1.137405)

    def test_flat_ignore_espacement(self):
        """Les extracteurs ne s'accordent pas sur les blancs."""
        assert _flat('RELEVE   COMPTE\n ESPECES') == 'RELEVE COMPTE ESPECES'


class TestAvis:
    def test_achat_action(self):
        mv = parse_avis_opere(AVIS_ACHAT)
        assert len(mv) == 1
        m = mv[0]
        assert (m.kind, m.side, m.envelope) == ('transaction', 'ACHAT', 'PEA')
        assert m.date == '2024-01-29'          # date d'execution, pas d'edition
        assert m.isin == 'FR0000000001'
        assert m.quantity == 25 and m.price == pytest.approx(40.0)
        assert m.fees == pytest.approx(5.0)
        assert m.net_eur == pytest.approx(1005.0)
        assert len(m.checks) == 2 and not m.warnings

    def test_vente(self):
        m = parse_avis_opere(AVIS_VENTE)[0]
        assert m.side == 'VENTE'
        # A la vente les frais se retranchent : 500,00 - 2,50
        assert m.net_eur == pytest.approx(497.50)
        assert not m.warnings

    def test_devise_et_change(self):
        m = parse_avis_opere(AVIS_DEVISE)[0]
        assert m.currency == 'USD'
        # Le cours de change porte plusieurs decimales : le tronquer a deux
        # faussait la contrevaleur de plus de dix euros.
        assert m.fx_rate == pytest.approx(1.25)
        assert m.envelope == 'Compte-titres'
        assert m.net_eur == pytest.approx(1605.0)
        assert not m.warnings

    def test_montant_incoherent_signale(self):
        faux = AVIS_ACHAT.replace('1 000,00 EUR', '1 234,00 EUR')
        m = parse_avis_opere(faux)[0]
        assert m.warnings and 'brut' in m.warnings[0]

    def test_document_non_avis(self):
        assert parse_avis_opere('Facture EDF 42,00 EUR') == []


class TestReleve:
    def test_versements_extraits(self):
        mvs = parse_releve_especes(RELEVE)
        assert [m.flux_type for m in mvs] == ['Versement', 'Versement']
        assert [m.net_eur for m in mvs] == [300.0, 1000.0]
        assert all(m.envelope == 'PEA' for m in mvs)

    def test_achat_non_repris_en_flux(self):
        """L'achat est porte par son avis : le compter en flux le doublerait."""
        assert all('ACHAT' not in (m.label or '') for m in parse_releve_especes(RELEVE))

    def test_controle_des_soldes(self):
        # 0 + 300 + 1000 - 1005,00 = 295,00
        mvs = parse_releve_especes(RELEVE)
        assert any('solde' in c for m in mvs for c in m.checks)

    def test_sens_retabli_si_colonnes_inversees(self):
        """Sans en-tete lisible, le sens est deduit puis verifie par les soldes."""
        sans_entete = RELEVE.replace('Débit EUR          Crédit EUR', '')
        mvs = parse_releve_especes(sans_entete)
        assert [m.net_eur for m in mvs] == [300.0, 1000.0]

    def test_document_non_releve(self):
        assert parse_releve_especes('Bulletin de salaire') == []


class TestDispatch:
    def test_avis_prioritaire(self):
        assert parse_movements(AVIS_ACHAT)[0].kind == 'transaction'

    def test_releve_reconnu(self):
        assert parse_movements(RELEVE)[0].kind == 'flux'

    def test_inconnu(self):
        assert parse_movements('rien à voir') == []


def _pdf(text):
    """Fabrique un PDF minimal contenant `text` (pour les tests d'endpoint)."""
    pytest.importorskip('reportlab')
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont('Courier', 7)
    y = 800
    for line in text.split('\n'):
        c.drawString(20, y, line)
        y -= 9
    c.save()
    buf.seek(0)
    return buf


class TestImportEndpoint:
    H = {'X-CSRF-Token': 'test'}

    def _post(self, client, step, files):
        return client.post(
            f'/api/import/movements?step={step}',
            data={'owner': 'Alice',
                  'files': [(_pdf(t), f'{n}.pdf') for n, t in files]},
            headers=self.H, content_type='multipart/form-data')

    def test_personne_requise(self, client):
        r = client.post('/api/import/movements',
                        data={'files': [(_pdf(AVIS_ACHAT), 'a.pdf')]},
                        headers=self.H, content_type='multipart/form-data')
        assert r.status_code == 400

    def test_aucun_fichier(self, client):
        r = client.post('/api/import/movements', data={'owner': 'Alice'},
                        headers=self.H, content_type='multipart/form-data')
        assert r.status_code == 400

    def test_preview_n_ecrit_rien(self, client):
        r = self._post(client, 'preview', [('avis', AVIS_ACHAT)])
        assert r.status_code == 200
        assert r.get_json()['summary']['transactions'] == 1
        with get_db() as conn:
            assert conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 0

    def test_commit_insere(self, client):
        r = self._post(client, 'commit', [('avis', AVIS_ACHAT), ('rel', RELEVE)])
        ins = r.get_json()['inserted']
        assert ins['transactions'] == 1
        assert ins['flux'] == 2
        with get_db() as conn:
            row = conn.execute('SELECT * FROM transactions').fetchone()
            assert row['isin'] == 'FR0000000001'
            assert row['establishment'] == 'BoursoBank'
            # L'etablissement doit suivre jusque dans les flux, sinon la
            # performance par compte reste approximative.
            assert conn.execute(
                'SELECT COUNT(*) FROM flux WHERE establishment IS NOT NULL'
            ).fetchone()[0] == 2

    def test_import_idempotent(self, client):
        """Reimporter les memes operations ne les duplique pas.

        Les PDF regeneres n'ont pas les memes octets (horodatage), donc la
        detection ne peut pas reposer sur la seule empreinte du fichier : c'est
        la cle metier (date, ISIN, sens, quantite, montant) qui tranche.
        """
        self._post(client, 'commit', [('avis', AVIS_ACHAT), ('rel', RELEVE)])
        r = self._post(client, 'commit', [('avis', AVIS_ACHAT), ('rel', RELEVE)])
        d = r.get_json()
        assert d['inserted']['transactions'] == 0
        assert d['inserted']['flux'] == 0
        assert d['summary']['duplicates'] == 3
        raisons = {i['duplicate_reason'] for i in d.get('transactions', [])
                   if i.get('duplicate_reason')}
        assert raisons <= {'opération déjà enregistrée', 'document déjà importé'}

    def test_meme_lot_deux_fois_dans_un_envoi(self, client):
        """Le meme fichier envoye deux fois dans un lot ne compte qu'une fois."""
        r = self._post(client, 'commit', [('a', AVIS_ACHAT), ('b', AVIS_ACHAT)])
        assert r.get_json()['inserted']['transactions'] == 1

    def test_isin_inconnu_cree(self, client):
        self._post(client, 'commit', [('avis', AVIS_ACHAT)])
        with get_db() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM securities WHERE isin='FR0000000001'"
            ).fetchone()[0] == 1

    def test_etablissement_impose(self, client):
        """L'appelant impose l'etablissement, pour coller a l'orthographe des positions.

        Un import ecrivant "BoursoBank" quand les positions disent "Boursorama"
        cree un compte distinct : les versements ne se rattachent plus, et le
        rendement de l'enveloppe absorbe les apports. Vu en prod : un PEA affiche
        a +44,86 % au lieu de +11,56 %.
        """
        r = client.post('/api/import/movements?step=commit',
                        data={'owner': 'Alice', 'establishment': 'Ma Banque',
                              'files': [(_pdf(AVIS_ACHAT), 'a.pdf')]},
                        headers=self.H, content_type='multipart/form-data')
        assert r.status_code == 200
        with get_db() as conn:
            assert conn.execute(
                'SELECT establishment FROM transactions').fetchone()[0] == 'Ma Banque'

    def test_etablissements_connus_proposes(self, client):
        with get_db() as conn:
            conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                establishment, value, debt, ownership_pct, debt_pct)
                VALUES ('2026-01-01','Alice','Actions','PEA','Ma Banque',1,0,1.0,1.0)""")
            conn.commit()
        r = self._post(client, 'preview', [('avis', AVIS_ACHAT)])
        assert 'Ma Banque' in r.get_json()['summary']['known_establishments']

    def test_document_rejete_signale(self, client):
        r = self._post(client, 'preview', [('facture', 'Facture EDF 42,00 EUR')])
        assert r.get_json()['summary']['rejected'][0]['file'] == 'facture.pdf'

    def test_enveloppe_alignee_sur_les_positions(self, client):
        """"Compte-titres" lu dans le document doit devenir "CTO" si c'est le nom employe.

        Sinon les flux ne se rattachent a aucun compte et l'enveloppe affiche un
        rendement qui absorbe les versements : un CTO ressortait a +114 %.
        """
        with get_db() as conn:
            conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                establishment, value, debt, ownership_pct, debt_pct)
                VALUES ('2026-01-01','Alice','Actions','CTO','X',1,0,1.0,1.0)""")
            conn.commit()
        r = self._post(client, 'commit', [('avis', AVIS_DEVISE)])
        assert r.status_code == 200
        with get_db() as conn:
            assert conn.execute(
                'SELECT envelope FROM transactions').fetchone()[0] == 'CTO'

    def test_enveloppe_inconnue_signalee(self, client):
        r = self._post(client, 'preview', [('avis', AVIS_DEVISE)])
        # Aucune position : l'enveloppe lue ne correspond a rien de connu
        assert 'Compte-titres' in r.get_json()['summary']['unresolved_envelopes']
