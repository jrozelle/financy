"""Releve de compte titres BoursoBank : lecture et controle du total.

Releves fictifs, de la structure des vrais (montants ronds, titres publics)."""
import os
from io import BytesIO

import pytest

os.environ['PRICE_PROVIDER'] = 'mock'

from services.parsers import pdf_releve_titres as rt
from services.parsers.common import ReleveIncoherentError, verifier_total, DetectedLine
from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa
from tests.test_pdf_parser import _make_pdf

PEA = """BOURSOBANK
RELEVE COMPTE TITRES : JUIN 2026
Valorisé au 30/06/2026
Compte PEA
Quantité Nom de la valeur (code) (1)(2) en devise de négociation Valorisation de la ligne Portef. Prix de revient fiscal unitaire
VALEURS FRANCAISES EUR EUR EUR
1 000 ETF MONDE ACC (FR0010315770) * 10,125 10 125,00 50,00 9,500
200 TOTALENERGIES (FR0000120271) 50,625 10 125,00 50,00 45,25
TOTAL EUR 20 250,00 100,00
TOTAL DU PORTEFEUILLE 20 250,00 EUR
SOLDE ESPECES (EUR) 100,00 EUR
TOTAL DE L'ACTIF 20 350,00 EUR
"""

CTO = """BOURSOBANK
RELEVE COMPTE TITRES : JUIN 2026
Valorisé au 30/06/2026
VALEURS ETRANGERES 1 EUR = 1,100 USD USD EUR EUR
10 APPLE (US0378331005) * 220,00 2 000,00 100,00 150,00
TOTAL DU PORTEFEUILLE 2 000,00 EUR
"""


def test_cours_a_trois_decimales_et_milliers():
    lignes, avert = rt.lire_texte(PEA)
    assert [(l.isin, l.quantity, l.market_value) for l in lignes] == [
        ('FR0010315770', 1000, 10125.0), ('FR0000120271', 200, 10125.0)]
    # « 10,125 » est un cours, pas dix mille cent vingt-cinq.
    assert lignes[0].unit_price == 10.125
    assert lignes[0].cost_basis == 9500.0
    assert lignes[0].as_of_date == '2026-06-30'
    assert 'espèces' in avert[0]


def test_cours_en_devise_non_repris_comme_euros():
    (ligne,), _ = rt.lire_texte(CTO)
    assert ligne.market_value == 2000.0 and ligne.quantity == 10
    assert ligne.unit_price is None


def test_total_faux_refuse():
    with pytest.raises(ReleveIncoherentError, match='20'):
        rt.lire_texte(PEA.replace('TOTAL DU PORTEFEUILLE 20 250,00', 'TOTAL DU PORTEFEUILLE 30 250,00'))


def test_ligne_illisible_refusee():
    # Une ligne que le lecteur ne reconnait pas manque a la somme : refus.
    with pytest.raises(ReleveIncoherentError):
        rt.lire_texte(PEA.replace(' 50,625 ', ' 50.625 '))


def test_sans_total_refuse():
    with pytest.raises(ReleveIncoherentError, match='introuvable'):
        rt.lire_texte(CTO.replace('TOTAL DU PORTEFEUILLE 2 000,00 EUR', ''))


def test_total_de_l_actif_jamais_pris_pour_le_portefeuille():
    texte = 'TOTAL DE L\'ACTIF 2 100,00 EUR\n'
    verifier_total([DetectedLine(isin='US0378331005', market_value=2000.0)], texte)


def test_generique_refuse_un_total_incoherent():
    lignes = [DetectedLine(isin='US0378331005', market_value=10125.0)]
    with pytest.raises(ReleveIncoherentError, match='10'):
        verifier_total(lignes, 'TOTAL DU PORTEFEUILLE 1 012,50 EUR')
    verifier_total(lignes, 'TOTAL DU PORTEFEUILLE 10 125,00 EUR')


def test_route_renvoie_le_refus(client):
    pid = _make_position(client, category='Actions', envelope='PEA', value=0, debt=0).get_json()['id']
    pdf = _make_pdf(['BOURSOBANK', 'RELEVE COMPTE TITRES : JUIN 2026', 'Valorise au 30/06/2026',
                     '10 APPLE (US0378331005) * 220,00 2 000,00 100,00 150,00',
                     'TOTAL DU PORTEFEUILLE 3 000,00 EUR'])
    r = client.post(f'/api/envelope/{pid}/import-pdf?step=preview',
                    data={'file': (BytesIO(pdf), 'cto.pdf')},
                    content_type='multipart/form-data', headers=CSRF_HEADERS)
    assert r.status_code == 422
    assert 'Rien n' in r.get_json()['error']
