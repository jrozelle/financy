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
                                        parse_movements, _num, _flat,
                                        _rows_from_words, _split_columns,
                                        _montants, detect_envelope, entete,
                                        parse_situation_generali)

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


# ─── Releve d'especes lu par les coordonnees ────────────────────────────────

# Les deux colonnes de montants sont calees a DROITE : x1=479 pour le debit,
# x1=546 pour le credit. Les libelles etant de longueurs differentes, leurs
# bords GAUCHES ne s'alignent pas — c'est tout le piege que ce gabarit tend au
# texte mis en page, qui place chaque jeton d'apres son bord gauche et melange
# alors les deux colonnes.
def _mot(texte, x1, top):
    return {'text': texte, 'x0': x1 - 7.0 * len(texte), 'x1': x1, 'top': top}


def _ligne(top, date, libelle, montant, x1):
    mots = [_mot(date, 100.0, top)]
    mots.append(_mot(libelle, 100.0 + 7.0 * (len(libelle) + 2), top))
    mots.append(_mot(date, 420.0, top))          # date de valeur
    mots.append(_mot(montant, x1, top + 0.4))    # decale : meme ligne quand meme
    return mots


DEBIT, CREDIT = 479.3, 546.0


def _releve_words():
    """Un releve complet : en-tete parasite, bornes de solde, quatre mouvements."""
    mots = []
    # L'en-tete porte lui aussi une date et un montant, dans une colonne a lui.
    mots += _ligne(50.0, '28/02/2026', 'EUR periode', '0,00', 441.9)
    mots += [_mot('SOLDE AU : 30/01/2026', 300.0, 100.0),
             _mot('4.321,00', CREDIT, 100.4)]
    mots += _ligne(120.0, '02/02/2026', 'VIR frais divers', '670,00', DEBIT)
    mots += _ligne(140.0, '17/02/2026', 'VIR CC vers livret', '1.200,00', CREDIT)
    mots += _ligne(160.0, '17/02/2026', 'VIR epargne vers livret', '2.400,00', CREDIT)
    mots += _ligne(180.0, '27/02/2026', 'VIR livret vers CC', '1.470,00', DEBIT)
    mots += [_mot('Nouveau solde en EUR :', 300.0, 250.0),
             _mot('5.781,00', CREDIT, 250.4)]
    # Hors bornes : ne doit pas etre lu.
    mots += _ligne(400.0, '05/03/2026', 'VIR posterieur au solde', '999,00', DEBIT)
    return [mots]


TEXTE_RELEVE_2026 = 'Extrait de votre compte en EUR\nCompte epargne : LIVRET BOURSO+\n'


class TestReleveParCoordonnees:

    def test_colonnes_separees_par_les_coordonnees(self):
        rows, _ = _rows_from_words(_releve_words())
        seuil = _split_columns([r[3] for r in rows])
        assert seuil is not None
        assert DEBIT < seuil < CREDIT

    def test_entete_et_hors_bornes_ecartes(self):
        """Seules les lignes entre solde initial et solde final sont des mouvements.

        L'en-tete du releve porte une date et un "0,00" dans une troisieme
        colonne : le lire comme un mouvement creait un alignement de plus et
        deplacait la frontiere debit/credit, inversant tous les sens de la page.
        """
        rows, _ = _rows_from_words(_releve_words())
        assert len(rows) == 4
        assert all('periode' not in r[1] and 'posterieur' not in r[1] for r in rows)

    def test_soldes_lus_malgre_le_decalage_de_ligne(self):
        """Le montant du solde final est decale de 0,4 pt : c'est la meme ligne."""
        _, (premier, dernier) = _rows_from_words(_releve_words())
        assert premier == 4321.00
        assert dernier == 5781.00

    def test_sens_verifie_par_les_soldes(self):
        mvs = parse_releve_especes(TEXTE_RELEVE_2026, words=_releve_words())
        assert [m.flux_type for m in mvs] == [
            'Retrait', 'Versement', 'Versement', 'Retrait']
        assert all(m.checks and not m.warnings for m in mvs)

    def test_enveloppe_livret(self):
        mvs = parse_releve_especes(TEXTE_RELEVE_2026, words=_releve_words())
        assert {m.envelope for m in mvs} == {'Livret Bourso+'}

    def test_annee_non_prise_pour_un_millier(self):
        """"27/02/2026 1.470,00" ne doit pas se lire 26 1 470,00.

        Le "026" de l'annee se collait au montant comme groupe de milliers.
        """
        mvs = parse_releve_especes(TEXTE_RELEVE_2026, words=_releve_words())
        assert max(m.net_eur for m in mvs) == 2400.0

    def test_virement_finançant_un_achat_reste_un_flux(self):
        """"VIR Achat crypto" sort bien de l'especes : ce n'est pas un titre.

        La regle qui ecarte les mouvements de titres, deja portes par un avis
        d'opere, happait ce virement et perdait 500 EUR de retrait.
        """
        mots = [_mot('SOLDE AU : 01/01/2026', 300.0, 100.0),
                _mot('1.000,00', CREDIT, 100.0)]
        mots += _ligne(120.0, '30/01/2026', 'VIR Achat crypto', '500,00', DEBIT)
        mots += [_mot('Nouveau solde en EUR :', 300.0, 200.0),
                 _mot('500,00', CREDIT, 200.0)]
        mvs = parse_releve_especes(TEXTE_RELEVE_2026, words=[mots])
        assert [(m.flux_type, m.net_eur) for m in mvs] == [('Retrait', 500.0)]

    def test_virement_mentionnant_une_ouverture_reste_un_flux(self):
        """"VIR vers CC pour ouverture CA31" est un retrait, pas une ouverture."""
        mots = [_mot('SOLDE AU : 01/02/2026', 300.0, 100.0),
                _mot('10.000,00', CREDIT, 100.0)]
        mots += _ligne(120.0, '18/02/2026', 'VIR vers CC pour ouverture CA31',
                       '5.000,00', DEBIT)
        mots += [_mot('Nouveau solde en EUR :', 300.0, 200.0),
                 _mot('5.000,00', CREDIT, 200.0)]
        mvs = parse_releve_especes(TEXTE_RELEVE_2026, words=[mots])
        assert [(m.flux_type, m.net_eur) for m in mvs] == [('Retrait', 5000.0)]


class TestMontantsRecolles:
    """Le separateur de milliers est une espace : extract_words coupe le montant."""

    def test_millier_recolle(self):
        line = [{'text': '1', 'x0': 553.8, 'x1': 557.3, 'top': 10.0},
                {'text': '000,00', 'x0': 559.0, 'x1': 578.3, 'top': 10.0}]
        assert _montants(line) == [(1000.0, 578.3)]

    def test_million_recolle(self):
        line = [{'text': '2', 'x0': 540.0, 'x1': 543.5, 'top': 10.0},
                {'text': '562,00', 'x0': 545.2, 'x1': 578.3, 'top': 10.0}]
        assert _montants(line) == [(2562.0, 578.3)]

    def test_jeton_eloigne_non_recolle(self):
        """Une quantite separee du montant par la colonne suivante reste dehors."""
        line = [{'text': '409', 'x0': 380.0, 'x1': 396.0, 'top': 10.0},
                {'text': '130,19', 'x0': 493.8, 'x1': 513.1, 'top': 10.0}]
        assert _montants(line) == [(130.19, 513.1)]

    def test_montant_deja_complet_inchange(self):
        """Le gabarit 2026 groupe par des points : le jeton arrive entier."""
        line = [{'text': '100.000,00', 'x0': 438.6, 'x1': 479.3, 'top': 10.0}]
        assert _montants(line) == [(100000.0, 479.3)]


class TestEnveloppeDansLEntete:

    RELEVE = ('Extrait de votre compte en EUR\n'
              'BOURSOBANK\n'
              'MOUVEMENTS EN EUR\n'
              'SOLDE AU : 01/02/2026 1.000,00\n'
              '03/02/2026 VIR Virement interne depuis Livret Bourso+ 03/02/2026 500,00\n'
              'Nouveau solde en EUR : 1.500,00\n')

    def test_marqueur_cherche_dans_l_entete_seulement(self):
        """Un libelle de virement nomme le compte d'en face, pas celui du releve.

        Chercher "Livret Bourso+" dans tout le document rangeait les mouvements
        d'un compte courant dans le livret qu'ils alimentaient.
        """
        assert detect_envelope(entete(self.RELEVE), default=None) is None
        assert detect_envelope(self.RELEVE, default=None) == 'Livret Bourso+'

    def test_entete_s_arrete_au_tableau(self):
        assert 'VIR Virement' not in entete(self.RELEVE)
        assert 'BOURSOBANK' in entete(self.RELEVE)

    def test_compte_courant_ne_devient_pas_compte_titres(self):
        """Le releve d'un compte courant n'a pas d'intitule d'enveloppe.

        Le ranger dans le compte-titres par defaut faisait entrer ses virements
        dans le rendement du CTO.
        """
        mvs = parse_releve_especes(self.RELEVE)
        assert [m.envelope for m in mvs] == ['Compte courant']

    def test_compte_titres_reconnu_par_son_intitule(self):
        releve = self.RELEVE.replace('BOURSOBANK', 'Compte (cid:224) vue ORD')
        assert [m.envelope for m in parse_releve_especes(releve)] == ['Compte-titres']

    def test_ancien_gabarit_sans_intitule_reste_compte_titres(self):
        """"RELEVE COMPTE ESPECES" est celui d'un compte adosse a un portefeuille."""
        releve = ('RELEVE  COMPTE  ESPECES : JUILLET 2024\n'
                  '30/06/2024 ANCIEN SOLDE 0,00\n'
                  '02/07/2024 VIR Virement interne depuis Compte p 1 000,00\n'
                  '31/07/2024 NOUVEAU SOLDE 1 000,00\n')
        assert [m.envelope for m in parse_releve_especes(releve)] == ['Compte-titres']


# ─── Situation annuelle d'assurance-vie (Generali / Bourso Vie) ─────────────

SITUATION_GENERALI = """\
Contrat N° : 12345678
MONSIEUR DUPONT CAMILLE
EPARGNE ATTEINTE DE VOTRE CONTRAT AU 31/12/2025                    1 234,00 €
                 OPERATIONS REALISEES DU 01/01/2025 AU 31/12/2025
       Opérations / Supports Montant net A la date du Valeur de la part Nombre de parts
Versement initial de 300,00 € du 13/05/2025 (Frais : 0,00%)
ETF MONDE ACC                        300,00 € 24/05/2025   50,26 €        5,9695
Versement libre programmé de 75,00 € du 10/06/2025 (Frais : 0,00%)
ETF MONDE ACC                         75,00 € 13/06/2025   59,03 €        1,2704
Frais de gestion de 2,97 € du 24/06/2025 (Frais : 0,18723%)
ETF MONDE ACC                         -2,97 € 24/06/2025   54,71 €       -0,0543
Distribution de dividendes de 23,75 € du 09/12/2025 (Frais : 0,00%)
ETF MONDE ACC                         23,75 € 09/12/2025   60,40 €        0,3933
Arbitrage de 100,00 € du 15/12/2025 (Frais : 0,00%)
ETF MONDE ACC                        100,00 € 15/12/2025   59,44 €        1,6823
"""


class TestSituationGenerali:

    OWNERS = ['Camille', 'Dominique']

    def test_types_de_flux(self):
        mvs = parse_situation_generali(SITUATION_GENERALI, self.OWNERS)
        assert [(m.flux_type, m.net_eur) for m in mvs] == [
            ('Versement', 300.0), ('Versement', 75.0),
            ('Frais', 2.97), ('Dividende/Intérêt', 23.75)]

    def test_arbitrage_ecarte(self):
        """Un arbitrage deplace l'epargne au sein du contrat.

        Le compter comme un versement gonflerait l'apport et effacerait d'autant
        le rendement.
        """
        mvs = parse_situation_generali(SITUATION_GENERALI, self.OWNERS)
        assert all('Arbitrage' not in (m.label or '') for m in mvs)

    def test_date_de_valeur_retenue(self):
        """C'est l'investissement qui fait bouger l'epargne, pas l'ordre."""
        mvs = parse_situation_generali(SITUATION_GENERALI, self.OWNERS)
        assert mvs[0].date == '2025-05-24'      # ordre le 13/05, investi le 24

    def test_chaque_ligne_verifiee(self):
        """parts x valeur de la part = montant net, a l'arrondi de la part pres.

        Une tolerance absolue rejetait les gros versements : 2 200 EUR sur
        42 parts laissent 0,13 EUR de jeu, 75 EUR sur 1,27 en laissent 0,02.
        """
        mvs = parse_situation_generali(SITUATION_GENERALI, self.OWNERS)
        assert all(m.checks and not m.warnings for m in mvs)

    def test_titulaire_lu_dans_le_document(self):
        mvs = parse_situation_generali(SITUATION_GENERALI, self.OWNERS)
        assert {m.owner for m in mvs} == {'Camille'}

    def test_titulaire_inconnu_du_referentiel_non_invente(self):
        mvs = parse_situation_generali(SITUATION_GENERALI, ['Dominique'])
        assert all(m.owner is None for m in mvs)
        assert all('titulaire non identifie' in ' '.join(m.warnings) for m in mvs)

    def test_titulaire_ambigu_non_tranche(self):
        """Deux noms connus dans le document : aucun ne peut etre retenu."""
        mvs = parse_situation_generali(
            SITUATION_GENERALI.replace('MONSIEUR DUPONT CAMILLE',
                                       'MONSIEUR DUPONT CAMILLE ET DOMINIQUE'),
            self.OWNERS)
        assert all(m.owner is None for m in mvs)

    def test_enveloppe_assurance_vie(self):
        mvs = parse_situation_generali(SITUATION_GENERALI, self.OWNERS)
        assert {m.envelope for m in mvs} == {'Assurance-vie'}

    def test_autre_document_ignore(self):
        assert parse_situation_generali('Relevé de compte espèces', self.OWNERS) == []

    def test_dispatche_par_parse_movements(self):
        mvs = parse_movements(SITUATION_GENERALI, owners=self.OWNERS)
        assert len(mvs) == 4 and mvs[0].kind == 'flux'


class TestFluxProvisoires:
    """Un versement programme peut etre saisi avant que le releve l'atteste.

    Le releve annuel doit alors le CORRIGER, pas le doubler : les deux sources
    ne datent pas le meme versement pareil — prelevement en debut de mois sur le
    compte courant, investissement une dizaine de jours plus tard chez
    l'assureur.
    """
    H = {'X-CSRF-Token': 'test'}

    def _seed_flux(self, date, notes, montant=75.0):
        with get_db() as conn:
            conn.execute("""INSERT INTO positions (date, owner, category, envelope,
                establishment, value, debt, ownership_pct, debt_pct)
                VALUES ('2025-01-01','Camille','Actions','Assurance-vie','BoursoBank',
                        1,0,1.0,1.0)""")
            conn.execute("""INSERT INTO flux (date, owner, envelope, establishment,
                type, amount, notes) VALUES (?,'Camille','Assurance-vie','BoursoBank',
                'Versement',?,?)""", (date, montant, notes))
            conn.commit()

    def _post(self, client, step='preview'):
        return client.post(
            f'/api/import/movements?step={step}',
            data={'owner': 'Camille',
                  'files': [(_pdf(SITUATION_GENERALI), 'situation.pdf')]},
            headers=self.H, content_type='multipart/form-data')

    def test_provisoire_corrige_et_non_double(self, client):
        # Saisi le 10/06, la situation l'atteste au 13/06 : trois jours d'ecart.
        self._seed_flux('2025-06-10', '[provisoire] versement programmé')
        d = self._post(client, 'commit').get_json()
        assert d['inserted']['corrections'] == 1
        with get_db() as conn:
            lignes = conn.execute("SELECT date, notes FROM flux WHERE amount=75.0").fetchall()
        assert len(lignes) == 1, 'un seul enregistrement, pas deux'
        assert lignes[0]['date'] == '2025-06-13', 'redate par le document'
        assert '[provisoire]' not in lignes[0]['notes']

    def test_flux_atteste_reste_un_doublon(self, client):
        """Sans mention provisoire, le meme flux a trois jours pres est un doublon.

        Il n'est ni insere ni modifie : deux documents peuvent decrire le meme
        mouvement, mais rien ne dit lequel fait foi.
        """
        self._seed_flux('2025-06-10', 'saisi a la main')
        d = self._post(client, 'commit').get_json()
        assert d['inserted']['flux'] == 3      # les trois autres operations
        assert d['inserted']['corrections'] == 0
        with get_db() as conn:
            row = conn.execute("SELECT date FROM flux WHERE amount=75.0").fetchone()
        assert row['date'] == '2025-06-10', 'date d origine conservee'

    def test_hors_tolerance_reste_un_flux_distinct(self, client):
        """A plus de quinze jours, c'est un autre versement."""
        self._seed_flux('2025-05-01', '[provisoire] versement programmé')
        d = self._post(client, 'commit').get_json()
        assert d['inserted']['corrections'] == 0
        with get_db() as conn:
            n = conn.execute('SELECT COUNT(*) FROM flux WHERE amount=75.0').fetchone()[0]
        assert n == 2

    def test_montant_different_non_rapproche(self, client):
        self._seed_flux('2025-06-10', '[provisoire] versement programmé', montant=80.0)
        d = self._post(client, 'commit').get_json()
        assert d['inserted']['corrections'] == 0

    def test_apercu_annonce_la_correction(self, client):
        self._seed_flux('2025-06-10', '[provisoire] versement programmé')
        d = self._post(client, 'preview').get_json()
        assert d['summary']['corrections'] == 1
        vise = [f for f in d['flux'] if f.get('corrects')]
        assert len(vise) == 1 and 'provisoire' in vise[0]['correction_reason']
        with get_db() as conn:
            assert conn.execute("SELECT date FROM flux WHERE amount=75.0"
                                ).fetchone()[0] == '2025-06-10', 'apercu n ecrit rien'
