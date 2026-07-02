"""Tests de duplication de snapshot via /api/snapshots/duplicate.

Regression : le bouton manuel « Dupliquer snapshot » recreait les positions
sans copier les holdings, d'ou une liste d'actifs vide a la nouvelle date une
fois l'onglet Actifs filtre par date. On verifie ici que la duplication copie
positions ET holdings, gere l'ecrasement sans orphelins, et valide ses entrees.
"""

import os
import pytest

os.environ['PRICE_PROVIDER'] = 'mock'

from models import get_db
from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa

D1 = '2026-05-01'
D2 = '2026-06-01'


def _seed_snapshot_with_holdings(client, date):
    r = _make_position(client, date=date, owner='Alice', category='Actions',
                       envelope='PEA', establishment='Boursorama', value=0, debt=0)
    pid = r.get_json()['id']
    client.put(f'/api/positions/{pid}/holdings', json={'holdings': [
        {'isin': 'FR0010315770', 'name': 'CW8', 'quantity': 20,
         'cost_basis': 8000, 'market_value': 9800},
        {'isin': 'IE00B4L5Y983', 'name': 'IWDA', 'quantity': 50,
         'cost_basis': 4500, 'market_value': 5200},
    ]}, headers=CSRF_HEADERS)
    return pid


class TestDuplicateSnapshot:
    def test_actifs_not_empty_after_duplication(self, client):
        """Le bug d'origine : actifs vides a la nouvelle date."""
        _seed_snapshot_with_holdings(client, D1)

        r = client.post('/api/snapshots/duplicate',
                        json={'source_date': D1, 'target_date': D2},
                        headers=CSRF_HEADERS)
        assert r.status_code == 200, r.get_json()

        data = client.get(f'/api/holdings/consolidated?date={D2}').get_json()
        assert data['snapshot_date'] == D2
        assert data['totals']['lines_count'] == 2
        isins = {l['isin'] for l in data['lines']}
        assert isins == {'FR0010315770', 'IE00B4L5Y983'}
        cw8 = next(l for l in data['lines'] if l['isin'] == 'FR0010315770')
        assert cw8['quantity'] == 20
        assert cw8['cost_basis'] == 8000
        assert cw8['market_value'] > 0

    def test_holdings_attached_to_new_positions(self, client):
        """Les holdings doivent pointer vers les positions de la nouvelle date."""
        _seed_snapshot_with_holdings(client, D1)
        client.post('/api/snapshots/duplicate',
                    json={'source_date': D1, 'target_date': D2},
                    headers=CSRF_HEADERS)

        positions = client.get(f'/api/positions?date={D2}').get_json()
        assert len(positions) == 1
        new_pid = positions[0]['id']
        h = client.get(f'/api/positions/{new_pid}/holdings').get_json()
        assert len(h['holdings']) == 2

    def test_overwrite_replaces_without_orphans(self, client):
        """Ecraser une cible existante purge ses holdings (pas d'orphelins)."""
        _seed_snapshot_with_holdings(client, D1)
        # Cible pre-existante avec un holding different
        stale_pid = _make_position(client, date=D2, owner='Alice',
                                   category='Actions', envelope='CTO',
                                   value=0, debt=0).get_json()['id']
        client.put(f'/api/positions/{stale_pid}/holdings', json={'holdings': [
            {'isin': 'US0378331005', 'name': 'Apple', 'quantity': 5,
             'cost_basis': 500, 'market_value': 750},
        ]}, headers=CSRF_HEADERS)

        r = client.post('/api/snapshots/duplicate',
                        json={'source_date': D1, 'target_date': D2},
                        headers=CSRF_HEADERS)
        assert r.status_code == 200

        # La cible reflete D1, plus l'ancien holding Apple
        data = client.get(f'/api/holdings/consolidated?date={D2}').get_json()
        isins = {l['isin'] for l in data['lines']}
        assert isins == {'FR0010315770', 'IE00B4L5Y983'}

        # Aucun holding orphelin ne subsiste (position_id sans position)
        with get_db() as conn:
            orphans = conn.execute('''
                SELECT COUNT(*) AS c FROM holdings h
                LEFT JOIN positions p ON p.id = h.position_id
                WHERE p.id IS NULL
            ''').fetchone()['c']
        assert orphans == 0

    def test_rejects_same_source_and_target(self, client):
        _seed_snapshot_with_holdings(client, D1)
        r = client.post('/api/snapshots/duplicate',
                        json={'source_date': D1, 'target_date': D1},
                        headers=CSRF_HEADERS)
        assert r.status_code == 400

    def test_rejects_invalid_date(self, client):
        r = client.post('/api/snapshots/duplicate',
                        json={'source_date': 'nope', 'target_date': D2},
                        headers=CSRF_HEADERS)
        assert r.status_code == 400

    def test_rejects_missing_source_snapshot(self, client):
        r = client.post('/api/snapshots/duplicate',
                        json={'source_date': D1, 'target_date': D2},
                        headers=CSRF_HEADERS)
        assert r.status_code == 404
