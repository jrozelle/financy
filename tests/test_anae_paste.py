"""Tests du parser copier-coller Credit Agricole / Anae (Predica).

Le format est un tableau web colle :
    NOM
    ISIN  date              (ACTIF EURO : juste la date, pas d'ISIN)
    Quantite Px.Revient Cours Montant +/- latentes +/- %
"""
import os

os.environ['PRICE_PROVIDER'] = 'mock'

from services.parsers import parse_pasted_text
from services.parsers.anae_paste import looks_like_anae_paste, parse_anae_paste
from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa: F401


SAMPLE = '''Valeur     Date de derniere valorisation     Quantite     Px. Revient     Cours     Montant     +/- latentes     +/- %
ACTIF EURO
    02/06/2026
    -     -     -     49 873,79 €     162,77 €     0,33 %
AM ACTIONS EMERGENTS-R
FR0013297546     27/05/2026
    35.1119     -     182,24 €     6 398,79 €     682,87 €     11,95 %
AM OBLIG MONDE RESPONSABLE-R
FR001400T779     27/05/2026
    29.36744     -     103,05 €     3 026,31 €     -8,10 €     -0,27 %
IF-EURO BONDS-G
LU1073896877     27/05/2026
    113.50772     -     13,45 €     1 526,68 €     10,59 €     0,70 %'''


def _by_isin(lines):
    return {l.isin: l for l in lines}


class TestDetection:
    def test_detects_anae_header(self):
        assert looks_like_anae_paste(SAMPLE) is True

    def test_ignores_other_paste_format(self):
        other = 'MON FONDS\nVoir la fiche\nCode ISIN\nFR0013297546\nNombre de parts\n10'
        assert looks_like_anae_paste(other) is False

    def test_dispatch_via_parse_pasted_text(self):
        r = parse_pasted_text(SAMPLE)
        assert r.format == 'anae_paste'
        assert len(r.lines) == 4


class TestParsing:
    def test_line_count(self):
        lines = parse_anae_paste(SAMPLE)
        assert len(lines) == 4

    def test_fonds_euros(self):
        l = _by_isin(parse_anae_paste(SAMPLE))['FONDS_EUROS_ACTIF_EURO']
        assert l.name == 'ACTIF EURO'
        assert l.quantity == 1.0
        assert l.market_value == 49873.79
        assert l.asset_class == 'fonds_euros'
        assert l.unit_price is None  # fonds euros : pas de cours

    def test_fund_fields(self):
        l = _by_isin(parse_anae_paste(SAMPLE))['FR0013297546']
        assert l.name == 'AM ACTIONS EMERGENTS-R'
        assert l.quantity == 35.1119
        assert l.unit_price == 182.24
        assert l.market_value == 6398.79

    def test_pru_derived_from_latentes(self):
        # cost_basis (total) = Montant - (+/- latentes) = 6398.79 - 682.87
        l = _by_isin(parse_anae_paste(SAMPLE))['FR0013297546']
        assert l.cost_basis == 5715.92
        # gain% coherent avec Anae (11,95 %)
        gain_pct = (l.market_value - l.cost_basis) / l.cost_basis * 100
        assert round(gain_pct, 2) == 11.95

    def test_pru_negative_latente(self):
        # moins-value : cost_basis > market_value
        l = _by_isin(parse_anae_paste(SAMPLE))['FR001400T779']
        assert l.cost_basis == 3034.41  # 3026.31 - (-8.10)
        assert l.cost_basis > l.market_value

    def test_total_market_value(self):
        r = parse_pasted_text(SAMPLE)
        assert round(r.total_market_value, 2) == round(
            49873.79 + 6398.79 + 3026.31 + 1526.68, 2)

    def test_quantity_dot_decimal(self):
        # Anae ecrit les quantites avec un point decimal
        l = _by_isin(parse_anae_paste(SAMPLE))['LU1073896877']
        assert l.quantity == 113.50772

    def test_as_of_date_parsed(self):
        lines = _by_isin(parse_anae_paste(SAMPLE))
        # ISIN line : FR0013297546  27/05/2026
        assert lines['FR0013297546'].as_of_date == '2026-05-27'
        # ACTIF EURO : la date est sur sa propre ligne (02/06/2026)
        assert lines['FONDS_EUROS_ACTIF_EURO'].as_of_date == '2026-06-02'


SAMPLE_MIXED = '''Valeur     Date     Quantite     Px. Revient     Cours     Montant     +/- latentes     +/- %
ACTIF EURO
    02/06/2026
    -     -     -     49 873,79 €     162,77 €     0,33 %
AM ACTIONS EMERGENTS-R
FR0013297546     27/05/2026
    35.1119     -     182,24 €     6 398,79 €     682,87 €     11,95 %
AM OBLIG MONDE RESPONSABLE-R
FR001400T779     27/05/2026
    29.36744     -     103,05 €     3 026,31 €     -8,10 €     -0,27 %'''


class TestFullImport:
    """Flux reel : preview (paste) -> save (PUT /holdings) -> auto-split par classe."""

    def _import(self, client):
        pos = _make_position(client, category='Actions', envelope='Assurance-vie',
                             owner='Bob', date='2026-06-07').get_json()
        pid = pos['id']
        prev = client.post(f'/api/envelope/{pid}/import-paste',
                           json={'text': SAMPLE_MIXED}, headers=CSRF_HEADERS).get_json()
        holdings = []
        for l in prev['lines']:
            h = {'isin': l['isin'], 'name': l['name'], 'quantity': l['quantity'],
                 'cost_basis': l['cost_basis'], 'market_value': l['market_value']}
            if l.get('asset_class'):
                h['asset_class'] = l['asset_class']
            if l.get('as_of_date'):
                h['as_of_date'] = l['as_of_date']
            if l['isin'].startswith('FONDS_EUROS_'):
                h['is_priceable'] = False
            holdings.append(h)
        res = client.put(f'/api/positions/{pid}/holdings',
                         json={'holdings': holdings}, headers=CSRF_HEADERS)
        assert res.status_code == 200, res.get_json()
        return pid, res.get_json()

    def test_auto_split_by_asset_class(self, client):
        self._import(client)
        avs = [p for p in client.get('/api/positions?date=2026-06-07').get_json()
               if p['envelope'] == 'Assurance-vie']
        by_cat = {p['category']: p for p in avs}
        assert set(by_cat) == {'Fond Euro', 'Actions', 'Obligations'}
        assert by_cat['Fond Euro']['value'] == 49873.79
        assert round(by_cat['Actions']['value'], 2) == 6398.79
        assert round(by_cat['Obligations']['value'], 2) == 3026.31

    def test_total_value_preserved(self, client):
        self._import(client)
        total = sum(p['value'] for p in client.get('/api/positions?date=2026-06-07').get_json()
                    if p['envelope'] == 'Assurance-vie')
        assert abs(total - (49873.79 + 6398.79 + 3026.31)) < 0.5

    def test_as_of_date_persisted(self, client):
        self._import(client)
        avs = [p for p in client.get('/api/positions?date=2026-06-07').get_json()
               if p['envelope'] == 'Assurance-vie']
        as_of = {}
        for p in avs:
            for h in client.get(f"/api/positions/{p['id']}/holdings").get_json()['holdings']:
                as_of[h['isin']] = h['as_of_date']
        assert as_of['FR0013297546'] == '2026-05-27'
        assert as_of['FONDS_EUROS_ACTIF_EURO'] == '2026-06-02'
