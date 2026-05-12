"""Integration tests for the consolidated holdings endpoint (phase 5)."""

import os
import pytest

os.environ['PRICE_PROVIDER'] = 'mock'

from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa


def _seed_two_positions_one_shared_isin(client):
    r = _make_position(client, owner='Alice', category='Actions', envelope='PEA',
                       establishment='Boursorama', value=0, debt=0)
    pea_id = r.get_json()['id']
    r = _make_position(client, owner='Alice', category='Actions', envelope='CTO',
                       establishment='Fortuneo', value=0, debt=0)
    cto_id = r.get_json()['id']
    client.put(f'/api/positions/{pea_id}/holdings', json={'holdings': [
        {'isin': 'FR0010315770', 'name': 'CW8', 'quantity': 20, 'cost_basis': 8000, 'market_value': 9800},
        {'isin': 'IE00B4L5Y983', 'name': 'IWDA', 'quantity': 50, 'cost_basis': 4500, 'market_value': 5200},
    ]}, headers=CSRF_HEADERS)
    client.put(f'/api/positions/{cto_id}/holdings', json={'holdings': [
        {'isin': 'FR0010315770', 'name': 'CW8', 'quantity': 10, 'cost_basis': 4500, 'market_value': 4900},
    ]}, headers=CSRF_HEADERS)


class TestConsolidated:
    def test_empty_when_no_positions(self, client):
        r = client.get('/api/holdings/consolidated')
        assert r.status_code == 200
        assert r.get_json()['totals'] == {}
        assert r.get_json()['lines'] == []

    def test_aggregates_across_positions(self, client):
        _seed_two_positions_one_shared_isin(client)
        r = client.get('/api/holdings/consolidated')
        data = r.get_json()

        # 2 ISIN distincts (CW8 agrege sur PEA+CTO, IWDA seul)
        assert data['totals']['lines_count'] == 2
        cw8 = next(l for l in data['lines'] if l['isin'] == 'FR0010315770')
        assert cw8['quantity'] == 30
        assert cw8['cost_basis'] == 12500
        assert cw8['market_value'] == 14700
        assert cw8['pnl'] == 2200
        assert sorted(cw8['establishments']) == ['Boursorama', 'Fortuneo']
        assert sorted(cw8['envelopes']) == ['CTO', 'PEA']
        assert cw8['positions_count'] == 2

    def test_date_param_uses_requested_snapshot(self, client):
        old = _make_position(client, date='2024-05-01', owner='Alice',
                             category='Actions', envelope='PEA',
                             establishment='Old Bank', value=0, debt=0)
        new = _make_position(client, date='2024-06-01', owner='Alice',
                             category='Actions', envelope='PEA',
                             establishment='New Bank', value=0, debt=0)
        old_id = old.get_json()['id']
        new_id = new.get_json()['id']
        client.put(f'/api/positions/{old_id}/holdings', json={'holdings': [
            {'isin': 'FR0010315770', 'name': 'CW8', 'quantity': 10,
             'cost_basis': 4000, 'market_value': 5000},
        ]}, headers=CSRF_HEADERS)
        client.put(f'/api/positions/{new_id}/holdings', json={'holdings': [
            {'isin': 'FR0010315770', 'name': 'CW8', 'quantity': 20,
             'cost_basis': 8000, 'market_value': 10000},
        ]}, headers=CSRF_HEADERS)

        requested = client.get('/api/holdings/consolidated?date=2024-05-01').get_json()
        latest = client.get('/api/holdings/consolidated').get_json()

        assert requested['snapshot_date'] == '2024-05-01'
        assert requested['lines'][0]['quantity'] == 10
        assert requested['lines'][0]['establishments'] == ['Old Bank']
        assert latest['snapshot_date'] == '2024-06-01'
        assert latest['lines'][0]['establishments'] == ['New Bank']

    def test_totals_and_pnl(self, client):
        _seed_two_positions_one_shared_isin(client)
        data = client.get('/api/holdings/consolidated').get_json()
        t = data['totals']
        assert t['market_value'] == 14700 + 5200
        assert t['cost_basis'] == 12500 + 4500
        assert t['pnl'] == t['market_value'] - t['cost_basis']

    def test_filter_by_owner(self, client):
        _seed_two_positions_one_shared_isin(client)
        r = _make_position(client, owner='Bob', category='Actions', envelope='CTO', value=0, debt=0)
        pid = r.get_json()['id']
        client.put(f'/api/positions/{pid}/holdings', json={'holdings': [
            {'isin': 'US0378331005', 'name': 'Apple', 'quantity': 5, 'cost_basis': 500, 'market_value': 750},
        ]}, headers=CSRF_HEADERS)

        alice = client.get('/api/holdings/consolidated?owner=Alice').get_json()
        bob = client.get('/api/holdings/consolidated?owner=Bob').get_json()
        all_ = client.get('/api/holdings/consolidated').get_json()

        assert alice['totals']['lines_count'] == 2
        assert bob['totals']['lines_count'] == 1
        assert all_['totals']['lines_count'] == 3

    def test_breakdowns_present(self, client):
        _seed_two_positions_one_shared_isin(client)
        data = client.get('/api/holdings/consolidated').get_json()
        assert 'asset_class' in data['breakdowns']
        assert 'currency' in data['breakdowns']
        assert 'envelope' in data['breakdowns']
        envelopes = {b['label'] for b in data['breakdowns']['envelope']}
        assert {'PEA', 'CTO'} <= envelopes

    def test_weight_pct_sums_to_100(self, client):
        _seed_two_positions_one_shared_isin(client)
        data = client.get('/api/holdings/consolidated').get_json()
        total = sum(l['weight_pct'] for l in data['lines'])
        assert abs(total - 100) < 0.5  # tolere les arrondis

    def test_sorted_by_market_value_desc(self, client):
        _seed_two_positions_one_shared_isin(client)
        data = client.get('/api/holdings/consolidated').get_json()
        mvs = [l['market_value'] for l in data['lines']]
        assert mvs == sorted(mvs, reverse=True)

    def test_non_priceable_uses_market_value(self, client):
        r = _make_position(client, owner='Alice', category='Assurance-vie',
                           envelope='Assurance-vie', value=0, debt=0)
        pid = r.get_json()['id']
        client.put(f'/api/positions/{pid}/holdings', json={'holdings': [
            {'isin': 'FONDS_EUROS_LINXEA', 'quantity': 1, 'cost_basis': 10000,
             'market_value': 10250, 'is_priceable': False},
        ]}, headers=CSRF_HEADERS)
        data = client.get('/api/holdings/consolidated').get_json()
        fe = data['lines'][0]
        assert fe['is_priceable'] is False
        assert fe['market_value'] == 10250
