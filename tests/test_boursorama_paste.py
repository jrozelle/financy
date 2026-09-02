"""Tests du parser copier-coller de la vue synchronisee Boursorama.

Couvre les deux mises en page (une ligne de chiffres par support vs une valeur
par ligne) et les sources PEA / BoursoVie / Lucya Cardif / Anae.
"""
import os

os.environ['PRICE_PROVIDER'] = 'mock'

from services.parsers import parse_pasted_text
from services.parsers.boursorama_paste import (
    looks_like_boursorama_paste, parse_boursorama_paste,
)
from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa: F401


# ─── Echantillons reels (4 sources) ──────────────────────────────────────────

ANAE = '''Valeur     Date de dernière valorisation     Quantité     Px. Revient     Cours     Montant     +/- latentes     +/- %
ACTIF EURO
    02/06/2026
    -     -     -     41 205,16 €     141,61 €     0,33 %
AM ACTIONS EMERGENTS-R
FR0013297546     27/05/2026
    30.5474     -     158,55 €     5 412,37 €     594,10 €     10,40 %
AM OBLIG MONDE RESPONSABLE-R
FR001400T779     27/05/2026
    25.54967     -     89,65 €     2 604,48 €     -7,05 €     -0,27 %'''

PEA = '''    Valeur    Quantité    Px. Revient    Cours    Montant    +/- Latentes    +/- %    Notification

ISHARES MSCI WORLD SWAP PEA ETF
IE0002XZSHO1

3 200

5,75 €

5,88 €
- 0,49 %

18 825,41 €

2 810,45 €

15,27 %


AMUNDI PEA EMERG MSCI ESG TR UCITS ETFC
FR0013412020

170

28,52 €

30,51 €
- 3,54 %

5 187,44 €

338,97 €

6,08 %'''

BOURSOVIE = '''Valeur    Date de Valeur    Quantité    Px. Revient    Cours    Montant    +/- Latentes    +/- %
Fonds en Euros (Euro Exclusif)

06/06/2026

0


0,00 €

46 518,33 €

0,00 €

0,00 %
Amundi MSCI World II UCITS ETF Dist
FR0010315770

05/06/2026

46,4357

350,41 €

361,55 €

19 297,30 €

594,33 €

2,77 %
iShares Core MSCI Emerging Markets IMI UCITS ETF
IE00BKM4GZ66

05/06/2026

83,9703

40,70 €

40,49 €

3 907,98 €

-19,73 €
- 0,50 %'''

LUCYA = '''Valeur     Date de dernière valorisation     Quantité     Px. Revient     Cours     Montant     +/- latentes     +/- %
Fonds Général Retraite
FGPERIN     -
    -     -     -     8 312,95 €     -     -
Amundi Core MSCI World ETF Acc
IE000BI8OT95     02/06/2026
    44.5548     -     135,73 €     6 790,20 €     -     11,40 %'''


# CTO : noms d'actions courts en majuscules + ISIN a la ligne, % journalier
# intercale entre Cours et Montant, quantite collee au Px.Revient par l'espace.
CTO = '''    Valeur    Quantité    Px. Revient    Cours    Montant    +/- Latentes    +/- %    Notification

ADOBE
US00724F1012

10

156,51 €

161,25 €
2,91 %

1 574,12 €

47,41 €

2,64 %


APPLE
US0378331005

8

150,00 €

152,42 €
0,80 %

1 219,39 €

175,39 €

14,62 %'''


def _by_isin(lines):
    return {l.isin: l for l in lines}



# Vue PEA avec la colonne de boutons "A" / "V" (Acheter / Vendre) : chaque
# libelle se colle sur sa propre ligne, AVANT le nom du support.
PEA_BOUTONS_AV = """    Valeur    Quantite    Px. Revient    Cours    Montant    +/- Latentes    +/- %    Notification
A
V
    
ISHARES MSCI WORLD SWAP PEA UCITS ETF EUR (ACC)
IE0002XZSHO1
    
3 645
    
5,24 €
    
6,05 €
0,17 %
    
24 610,75 €
    
3 391,96 €
    
13,45 %
    
A
V
    
AMUNDI NASDAQ-100 DAILY (2X) LEVERAGED UCITS ETF ACC
FR0010342592
    
82
    
8,02 €
    
8,08 €
- 0,30 %
    
662,46 €
    
4,82 €
    
0,73 %"""

class TestDetection:
    def test_all_sources_detected(self):
        for txt in (ANAE, PEA, BOURSOVIE, LUCYA):
            assert looks_like_boursorama_paste(txt) is True

    def test_ignores_voir_la_fiche_format(self):
        other = 'MON FONDS\nVoir la fiche\nCode ISIN\nFR0013297546\nNombre de parts\n10'
        assert looks_like_boursorama_paste(other) is False

    def test_dispatch_format_label(self):
        r = parse_pasted_text(PEA)
        assert r.format == 'boursorama_paste'
        assert 'Boursorama' in r.source_label


class TestAnae:
    def test_fund_and_pru(self):
        d = _by_isin(parse_boursorama_paste(ANAE))
        l = d['FR0013297546']
        assert l.quantity == 30.5474
        assert l.unit_price == 158.55
        assert l.market_value == 5412.37
        assert l.cost_basis == 4832.06      # Montant - latentes
        assert l.as_of_date == '2026-05-27'

    def test_fonds_euros(self):
        d = _by_isin(parse_boursorama_paste(ANAE))
        l = d['FONDS_EUROS_ACTIF_EURO']
        assert l.quantity == 1.0
        assert l.market_value == 41205.16
        assert l.asset_class == 'fonds_euros'


class TestPEA:
    """Mise en page une-valeur-par-ligne, Px.Revient present, % journalier parasite."""

    def test_holdings(self):
        d = _by_isin(parse_boursorama_paste(PEA))
        assert set(d) == {'IE0002XZSHO1', 'FR0013412020'}
        a = d['IE0002XZSHO1']
        assert a.quantity == 3200.0
        assert a.unit_price == 5.88        # Cours (pas le % journalier -0,49)
        assert a.market_value == 18825.41
        assert a.cost_basis == 18400.0     # Px.Revient 5,75 x 3200

    def test_no_false_fonds_euros(self):
        # un PEA d'ETF ne doit pas creer de pseudo-fonds-euros
        assert all(not l.isin.startswith('FONDS_EUROS_')
                   for l in parse_boursorama_paste(PEA))


class TestBoursoVie:
    def test_fonds_euros_no_isin(self):
        d = _by_isin(parse_boursorama_paste(BOURSOVIE))
        fe = [l for l in d.values() if l.asset_class == 'fonds_euros']
        assert len(fe) == 1
        assert fe[0].market_value == 46518.33
        assert fe[0].quantity == 1.0

    def test_fund_with_px_revient(self):
        d = _by_isin(parse_boursorama_paste(BOURSOVIE))
        l = d['FR0010315770']
        assert l.quantity == 46.4357
        assert l.unit_price == 361.55
        assert l.market_value == 19297.30
        assert l.cost_basis == 18265.33    # 350,41 x 46,4357

    def test_negative_latente(self):
        d = _by_isin(parse_boursorama_paste(BOURSOVIE))
        l = d['IE00BKM4GZ66']
        assert l.market_value == 3907.98
        assert l.unit_price == 40.49


class TestLucya:
    def test_internal_code_fonds_euros(self):
        # FGPERIN n'est pas un ISIN valide -> fonds euros
        d = _by_isin(parse_boursorama_paste(LUCYA))
        fe = [l for l in d.values() if l.asset_class == 'fonds_euros']
        assert any(abs(l.market_value - 8312.95) < 0.01 for l in fe)

    def test_real_isin_fund(self):
        d = _by_isin(parse_boursorama_paste(LUCYA))
        l = d['IE000BI8OT95']
        assert l.quantity == 44.5548
        assert l.market_value == 6950.99
        assert l.unit_price == 135.73


class TestCTO:
    """Compte-titres : noms d'actions courts (ADOBE, APPLE) suivis de leur ISIN."""

    def test_detected(self):
        assert looks_like_boursorama_paste(CTO) is True

    def test_short_uppercase_names_parsed(self):
        d = _by_isin(parse_boursorama_paste(CTO))
        # Sans le fix, ADOBE/APPLE sont pris pour des codes -> 0 ligne detectee
        assert set(d) == {'US00724F1012', 'US0378331005'}
        assert {l.name for l in d.values()} == {'ADOBE', 'APPLE'}

    def test_quantity_not_merged_with_px_revient(self):
        d = _by_isin(parse_boursorama_paste(CTO))
        adobe = d['US00724F1012']
        assert adobe.quantity == 10          # pas 8856,51
        assert adobe.unit_price == 161.25    # Cours, pas le % journalier 2,91
        assert adobe.market_value == 1574.12
        assert adobe.cost_basis == 1565.1    # Px.Revient 156,51 x 10
        apple = d['US0378331005']
        assert apple.quantity == 8           # pas 7090,50
        assert apple.market_value == 1219.39

    def test_no_false_fonds_euros(self):
        assert all(not l.isin.startswith('FONDS_EUROS_')
                   for l in parse_boursorama_paste(CTO))


class TestSeparatorRobustness:
    def _check(self, text, n):
        r = parse_boursorama_paste(text)
        assert len(r) == n
        assert all(l.market_value for l in r)

    def test_tabs(self):
        self._check(ANAE.replace('     ', '\t'), 3)

    def test_single_space(self):
        self._check(ANAE.replace('     ', ' '), 3)

    def test_nbsp_thousands(self):
        nb = chr(0x00a0)
        self._check(ANAE.replace('5 566', '6' + nb + '398'), 3)


class TestFullImport:
    """preview (paste) -> PUT /holdings -> auto-split par classe."""

    def _import(self, client, text, envelope='Assurance-vie'):
        pos = _make_position(client, category='Actions', envelope=envelope,
                             owner='Bob', date='2026-06-07').get_json()
        pid = pos['id']
        prev = client.post(f'/api/envelope/{pid}/import-paste',
                           json={'text': text}, headers=CSRF_HEADERS).get_json()
        assert prev['format'] == 'boursorama_paste'
        holdings = []
        for l in prev['lines']:
            h = {'isin': l['isin'], 'name': l['name'], 'quantity': l['quantity'],
                 'cost_basis': l['cost_basis'], 'market_value': l['market_value']}
            if l.get('asset_class'):
                h['asset_class'] = l['asset_class']
            if l.get('as_of_date'):
                h['as_of_date'] = l['as_of_date']
            if l['isin'].startswith(('FONDS_EUROS_', 'CUSTOM_')):
                h['is_priceable'] = False
            holdings.append(h)
        res = client.put(f'/api/positions/{pid}/holdings',
                         json={'holdings': holdings}, headers=CSRF_HEADERS)
        assert res.status_code == 200, res.get_json()
        return [p for p in client.get('/api/positions?date=2026-06-07').get_json()
                if p['envelope'] == envelope]

    def test_av_split_fond_euro_actions_obligations(self, client):
        avs = self._import(client, ANAE)
        by_cat = {p['category']: p for p in avs}
        assert set(by_cat) == {'Fond Euro', 'Actions', 'Obligations'}
        total = sum(p['value'] for p in avs)
        assert abs(total - (41205.16 + 5412.37 + 2604.48)) < 0.5

    def test_pea_single_actions_position(self, client):
        pea = self._import(client, PEA, envelope='PEA')
        by_cat = {p['category']: p for p in pea}
        assert set(by_cat) == {'Actions'}
        assert abs(by_cat['Actions']['value'] - (18825.41 + 5187.44)) < 0.5

class TestBoutonsAchatVente:
    """Regression : la colonne de boutons fabriquait deux faux fonds euros par
    support. "A" et "V", promus en nom de support, ouvraient un bloc sans
    aucune donnee, et 5 lignes collees en rendaient 15."""

    def test_pas_de_ligne_parasite(self):
        lines = parse_boursorama_paste(PEA_BOUTONS_AV)
        assert len(lines) == 2
        assert {l.isin for l in lines} == {'IE0002XZSHO1', 'FR0010342592'}

    def test_valeurs_intactes(self):
        d = _by_isin(parse_boursorama_paste(PEA_BOUTONS_AV))
        a = d['IE0002XZSHO1']
        assert a.quantity == 3645.3
        assert a.unit_price == 6.05
        assert a.market_value == 24610.75
        assert a.cost_basis == 21450.10      # Px.Revient 5,24 x 3645
        b = d['FR0010342592']
        assert b.quantity == 71.3
        assert b.market_value == 648.20
