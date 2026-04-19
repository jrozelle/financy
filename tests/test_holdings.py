"""Integration tests for the holdings feature (phase 1)."""

import pytest

# Reuse fixtures & helpers from test_api
from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa


def _make_position_pea(client, **kwargs):
    """Position PEA vide, prête à accueillir des holdings."""
    resp = _make_position(client, category='Actions', envelope='PEA',
                          value=0, debt=0, **kwargs)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


# ─── Validation ISIN ─────────────────────────────────────────────────────────

class TestValidateIsin:
    def test_valid_real_isins(self):
        from models import validate_isin
        assert validate_isin('FR0010315770')  # CW8
        assert validate_isin('IE00B4L5Y983')  # IWDA
        assert validate_isin('US0378331005')  # Apple
        assert validate_isin('FR0000131104')  # BNP Paribas

    def test_pseudo_isins(self):
        from models import validate_isin
        assert validate_isin('FONDS_EUROS_LINXEA_SPIRIT_2')
        assert validate_isin('CUSTOM_SCPI_PRIMOVIE')

    def test_invalid(self):
        from models import validate_isin
        assert not validate_isin('')
        assert not validate_isin(None)
        assert not validate_isin('FR000013110')      # 11 chars
        assert not validate_isin('FR00001311040')    # 13 chars
        assert not validate_isin('FR0000131105')     # mauvais checksum
        assert not validate_isin('ZZ0000131104')     # checksum invalide
        assert not validate_isin('FR 000013110')     # espace


# ─── CRUD holdings ───────────────────────────────────────────────────────────

class TestHoldingsCrud:
    def test_get_empty(self, client):
        pos = _make_position_pea(client)
        r = client.get(f'/api/positions/{pos["id"]}/holdings')
        assert r.status_code == 200
        assert r.get_json()['holdings'] == []

    def test_get_unknown_position(self, client):
        r = client.get('/api/positions/99999/holdings')
        assert r.status_code == 404

    def test_add_valid(self, client):
        pos = _make_position_pea(client)
        r = client.post(f'/api/positions/{pos["id"]}/holdings', json={
            'isin': 'FR0010315770', 'name': 'CW8',
            'quantity': 20, 'cost_basis': 8000, 'market_value': 9800
        }, headers=CSRF_HEADERS)
        assert r.status_code == 201
        h = r.get_json()
        assert h['isin'] == 'FR0010315770'
        assert h['quantity'] == 20
        assert h['is_priceable'] is True

    def test_add_invalid_isin(self, client):
        pos = _make_position_pea(client)
        r = client.post(f'/api/positions/{pos["id"]}/holdings', json={
            'isin': 'BADISIN', 'quantity': 1
        }, headers=CSRF_HEADERS)
        assert r.status_code == 400

    def test_add_zero_qty(self, client):
        pos = _make_position_pea(client)
        r = client.post(f'/api/positions/{pos["id"]}/holdings', json={
            'isin': 'FR0010315770', 'quantity': 0
        }, headers=CSRF_HEADERS)
        assert r.status_code == 400

    def test_replace_all(self, client):
        pos = _make_position_pea(client)
        r = client.put(f'/api/positions/{pos["id"]}/holdings', json={
            'holdings': [
                {'isin': 'FR0010315770', 'quantity': 20, 'cost_basis': 8000, 'market_value': 9800},
                {'isin': 'IE00B4L5Y983', 'quantity': 50, 'cost_basis': 4500, 'market_value': 5200},
            ]
        }, headers=CSRF_HEADERS)
        assert r.status_code == 200
        data = r.get_json()
        assert len(data['holdings']) == 2

    def test_replace_rejects_invalid_line(self, client):
        pos = _make_position_pea(client)
        r = client.put(f'/api/positions/{pos["id"]}/holdings', json={
            'holdings': [
                {'isin': 'FR0010315770', 'quantity': 20},
                {'isin': 'BADISIN', 'quantity': 1},
            ]
        }, headers=CSRF_HEADERS)
        assert r.status_code == 400
        # Verification: aucune ligne n'a ete inseree (validation avant wipe)
        r = client.get(f'/api/positions/{pos["id"]}/holdings')
        assert r.get_json()['holdings'] == []

    def test_patch(self, client):
        pos = _make_position_pea(client)
        r = client.post(f'/api/positions/{pos["id"]}/holdings', json={
            'isin': 'FR0010315770', 'quantity': 20
        }, headers=CSRF_HEADERS)
        hid = r.get_json()['id']
        r = client.patch(f'/api/holdings/{hid}', json={'quantity': 30},
                         headers=CSRF_HEADERS)
        assert r.status_code == 200
        assert r.get_json()['quantity'] == 30

    def test_delete(self, client):
        pos = _make_position_pea(client)
        r = client.post(f'/api/positions/{pos["id"]}/holdings', json={
            'isin': 'FR0010315770', 'quantity': 20
        }, headers=CSRF_HEADERS)
        hid = r.get_json()['id']
        r = client.delete(f'/api/holdings/{hid}', headers=CSRF_HEADERS)
        assert r.status_code == 204

    def test_cascade_delete_on_position(self, client):
        pos = _make_position_pea(client)
        client.post(f'/api/positions/{pos["id"]}/holdings', json={
            'isin': 'FR0010315770', 'quantity': 20
        }, headers=CSRF_HEADERS)
        client.delete(f'/api/positions/{pos["id"]}', headers=CSRF_HEADERS)
        # Position supprimee -> 404, holdings cascades
        r = client.get(f'/api/positions/{pos["id"]}/holdings')
        assert r.status_code == 404


# ─── compute_position avec holdings ──────────────────────────────────────────

class TestComputePositionHoldings:
    def test_value_from_market_value(self, client):
        """Sans last_price, la value de la position = somme des market_value."""
        pos = _make_position_pea(client)
        client.put(f'/api/positions/{pos["id"]}/holdings', json={'holdings': [
            {'isin': 'FR0010315770', 'quantity': 20, 'cost_basis': 8000, 'market_value': 9800},
            {'isin': 'IE00B4L5Y983', 'quantity': 50, 'cost_basis': 4500, 'market_value': 5200},
        ]}, headers=CSRF_HEADERS)
        r = client.get(f'/api/positions?date={pos["date"]}')
        p = next(x for x in r.get_json() if x['id'] == pos['id'])
        assert p['value'] == 15000
        assert p['has_holdings'] is True
        assert p['holdings_count'] == 2

    def test_value_from_last_price(self, client):
        """Avec un last_price connu, value = qty * last_price."""
        pos = _make_position_pea(client)
        client.put(f'/api/positions/{pos["id"]}/holdings', json={'holdings': [
            {'isin': 'FR0010315770', 'quantity': 20, 'cost_basis': 8000, 'market_value': 9800},
        ]}, headers=CSRF_HEADERS)
        # Simule un refresh de cours
        from models import get_db
        with get_db() as conn:
            conn.execute("UPDATE securities SET last_price=500, last_price_date='2024-06-01' WHERE isin='FR0010315770'")
        r = client.get(f'/api/positions?date={pos["date"]}')
        p = next(x for x in r.get_json() if x['id'] == pos['id'])
        assert p['value'] == 10000  # 20 * 500

    def test_fonds_euros_manual(self, client):
        """Fonds euros (is_priceable=false) conserve market_value manuel."""
        pos = _make_position(client, category='Assurance-vie', envelope='Assurance-vie',
                             value=0, debt=0).get_json()
        client.put(f'/api/positions/{pos["id"]}/holdings', json={'holdings': [
            {'isin': 'FONDS_EUROS_LINXEA', 'quantity': 1,
             'cost_basis': 10000, 'market_value': 10250, 'is_priceable': False},
        ]}, headers=CSRF_HEADERS)
        r = client.get(f'/api/positions?date={pos["date"]}')
        p = next(x for x in r.get_json() if x['id'] == pos['id'])
        assert p['value'] == 10250

    def test_position_without_holdings_unchanged(self, client):
        """Une position sans holdings garde son comportement historique."""
        r = _make_position(client, value=5000, debt=0)
        pos = r.get_json()
        r = client.get(f'/api/positions?date={pos["date"]}')
        p = next(x for x in r.get_json() if x['id'] == pos['id'])
        assert p['value'] == 5000
        assert not p.get('has_holdings')


# ─── Snapshots ───────────────────────────────────────────────────────────────

class TestHoldingsSnapshot:
    def test_auto_snapshot_copies_holdings(self, client):
        pos = _make_position_pea(client, date='2024-06-01')
        client.put(f'/api/positions/{pos["id"]}/holdings', json={'holdings': [
            {'isin': 'FR0010315770', 'quantity': 20, 'cost_basis': 8000, 'market_value': 9800},
            {'isin': 'IE00B4L5Y983', 'quantity': 50, 'cost_basis': 4500, 'market_value': 5200},
        ]}, headers=CSRF_HEADERS)
        r = client.post('/api/auto-snapshot', json={'date': '2024-07-01'},
                        headers=CSRF_HEADERS)
        data = r.get_json()
        assert data['copied'] == 1
        assert data['holdings_copied'] == 2
        # La nouvelle position a bien la valeur figee (Σ market_value)
        r = client.get('/api/positions?date=2024-07-01')
        p = r.get_json()[0]
        assert p['value'] == 15000

    def test_snapshot_idempotent(self, client):
        pos = _make_position_pea(client, date='2024-06-01')
        client.put(f'/api/positions/{pos["id"]}/holdings', json={'holdings': [
            {'isin': 'FR0010315770', 'quantity': 20, 'cost_basis': 8000, 'market_value': 9800},
        ]}, headers=CSRF_HEADERS)
        r1 = client.post('/api/holdings/snapshot', json={'date': '2024-07-01'},
                         headers=CSRF_HEADERS)
        r2 = client.post('/api/holdings/snapshot', json={'date': '2024-07-01'},
                         headers=CSRF_HEADERS)
        assert r1.get_json()['count'] == r2.get_json()['count']


# ─── Import/export JSON ──────────────────────────────────────────────────────

class TestHoldingsImportExport:
    def test_round_trip(self, client):
        pos = _make_position_pea(client)
        client.put(f'/api/positions/{pos["id"]}/holdings', json={'holdings': [
            {'isin': 'FR0010315770', 'name': 'CW8', 'quantity': 20,
             'cost_basis': 8000, 'market_value': 9800},
            {'isin': 'FONDS_EUROS_LINXEA', 'quantity': 1,
             'cost_basis': 10000, 'market_value': 10250, 'is_priceable': False},
        ]}, headers=CSRF_HEADERS)

        export = client.get('/api/export').get_json()
        assert len(export['securities']) == 2
        assert len(export['holdings']) == 2

        client.post('/api/reset', headers=CSRF_HEADERS)
        r = client.post('/api/import-json', json=export, headers=CSRF_HEADERS)
        imp = r.get_json()
        assert imp['positions'] == 1
        assert imp['holdings'] == 2
        assert imp['securities'] == 2
        assert imp['skipped'] == 0

        # La valeur recalculee est correcte apres round-trip
        r = client.get('/api/positions?date=2024-06-01')
        p = r.get_json()[0]
        assert p['value'] == 9800 + 10250


# ─── Securities ──────────────────────────────────────────────────────────────

class TestSecurities:
    def test_search(self, client):
        pos = _make_position_pea(client)
        client.post(f'/api/positions/{pos["id"]}/holdings', json={
            'isin': 'FR0010315770', 'name': 'Amundi MSCI World', 'quantity': 10
        }, headers=CSRF_HEADERS)
        r = client.get('/api/securities?q=amundi')
        results = r.get_json()
        assert len(results) == 1
        assert results[0]['isin'] == 'FR0010315770'

    def test_update_metadata(self, client):
        pos = _make_position_pea(client)
        client.post(f'/api/positions/{pos["id"]}/holdings', json={
            'isin': 'FR0010315770', 'quantity': 10
        }, headers=CSRF_HEADERS)
        r = client.patch('/api/securities/FR0010315770',
                         json={'ticker': 'CW8.PA', 'asset_class': 'etf'},
                         headers=CSRF_HEADERS)
        assert r.status_code == 200
        assert r.get_json()['ticker'] == 'CW8.PA'
