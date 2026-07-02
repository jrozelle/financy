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
    -     -     -     49 873,79 €     162,77 €     0,33 %
AM ACTIONS EMERGENTS-R
FR0013297546     27/05/2026
    35.1119     -     182,24 €     6 398,79 €     682,87 €     11,95 %
AM OBLIG MONDE RESPONSABLE-R
FR001400T779     27/05/2026
    29.36744     -     103,05 €     3 026,31 €     -8,10 €     -0,27 %'''

PEA = '''    Valeur    Quantité    Px. Revient    Cours    Montant    +/- Latentes    +/- %    Notification

ISHARES MSCI WORLD SWAP PEA ETF
IE0002XZSHO1

3 200

5,75 €

6,76 €
- 0,49 %

21 638,40 €

3 230,40 €

17,55 %


AMUNDI PEA EMERG MSCI ESG TR UCITS ETFC
FR0013412020

170

32,78 €

35,07 €
- 3,54 %

5 962,58 €

389,62 €

6,99 %'''

BOURSOVIE = '''Valeur    Date de Valeur    Quantité    Px. Revient    Cours    Montant    +/- Latentes    +/- %
Fonds en Euros (Euro Exclusif)

06/06/2026

0


0,00 €

55 070,29 €

0,00 €

0,00 %
Amundi MSCI World II UCITS ETF Dist
FR0010315770

05/06/2026

53,3744

402,77 €

415,57 €

22 180,80 €

683,14 €

3,18 %
iShares Core MSCI Emerging Markets IMI UCITS ETF
IE00BKM4GZ66

05/06/2026

96,5176

46,78 €

46,54 €

4 491,93 €

-22,68 €
- 0,50 %'''

LUCYA = '''Valeur     Date de dernière valorisation     Quantité     Px. Revient     Cours     Montant     +/- latentes     +/- %
Fonds Général Retraite
FGPERIN     -
    -     -     -     9 786,53 €     -     -
Amundi Core MSCI World ETF Acc
IE000BI8OT95     02/06/2026
    51.2124     -     156,01 €     7 989,64 €     -     13,10 %'''


# CTO : noms d'actions courts en majuscules + ISIN a la ligne, % journalier
# intercale entre Cours et Montant, quantite collee au Px.Revient par l'espace.
CTO = '''    Valeur    Quantité    Px. Revient    Cours    Montant    +/- Latentes    +/- %    Notification

ADOBE
US00724F1012

10

179,90 €

185,35 €
2,91 %

1 853,47 €

54,50 €

3,03 %


APPLE
US0378331005

8

150,00 €

175,20 €
0,80 %

1 401,60 €

201,60 €

16,80 %'''


def _by_isin(lines):
    return {l.isin: l for l in lines}


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
        assert l.quantity == 35.1119
        assert l.unit_price == 182.24
        assert l.market_value == 6398.79
        assert l.cost_basis == 5715.92      # Montant - latentes
        assert l.as_of_date == '2026-05-27'

    def test_fonds_euros(self):
        d = _by_isin(parse_boursorama_paste(ANAE))
        l = d['FONDS_EUROS_ACTIF_EURO']
        assert l.quantity == 1.0
        assert l.market_value == 49873.79
        assert l.asset_class == 'fonds_euros'


class TestPEA:
    """Mise en page une-valeur-par-ligne, Px.Revient present, % journalier parasite."""

    def test_holdings(self):
        d = _by_isin(parse_boursorama_paste(PEA))
        assert set(d) == {'IE0002XZSHO1', 'FR0013412020'}
        a = d['IE0002XZSHO1']
        assert a.quantity == 3200.0
        assert a.unit_price == 6.76        # Cours (pas le % journalier -0,49)
        assert a.market_value == 21638.40
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
        assert fe[0].market_value == 55070.29
        assert fe[0].quantity == 1.0

    def test_fund_with_px_revient(self):
        d = _by_isin(parse_boursorama_paste(BOURSOVIE))
        l = d['FR0010315770']
        assert l.quantity == 53.3744
        assert l.unit_price == 415.57
        assert l.market_value == 22180.80
        assert l.cost_basis == 21497.61    # 402,77 x 53,3744

    def test_negative_latente(self):
        d = _by_isin(parse_boursorama_paste(BOURSOVIE))
        l = d['IE00BKM4GZ66']
        assert l.market_value == 4491.93
        assert l.unit_price == 46.54


class TestLucya:
    def test_internal_code_fonds_euros(self):
        # FGPERIN n'est pas un ISIN valide -> fonds euros
        d = _by_isin(parse_boursorama_paste(LUCYA))
        fe = [l for l in d.values() if l.asset_class == 'fonds_euros']
        assert any(abs(l.market_value - 9786.53) < 0.01 for l in fe)

    def test_real_isin_fund(self):
        d = _by_isin(parse_boursorama_paste(LUCYA))
        l = d['IE000BI8OT95']
        assert l.quantity == 51.2124
        assert l.market_value == 7989.64
        assert l.unit_price == 156.01


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
        assert adobe.quantity == 10          # pas 10179,90
        assert adobe.unit_price == 185.35    # Cours, pas le % journalier 2,91
        assert adobe.market_value == 1853.47
        assert adobe.cost_basis == 1799.0    # Px.Revient 179,90 x 10
        apple = d['US0378331005']
        assert apple.quantity == 8           # pas 8150,00
        assert apple.market_value == 1401.60

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
        self._check(ANAE.replace('6 398', '6' + nb + '398'), 3)


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
        assert abs(total - (49873.79 + 6398.79 + 3026.31)) < 0.5

    def test_pea_single_actions_position(self, client):
        pea = self._import(client, PEA, envelope='PEA')
        by_cat = {p['category']: p for p in pea}
        assert set(by_cat) == {'Actions'}
        assert abs(by_cat['Actions']['value'] - (21638.40 + 5962.58)) < 0.5
