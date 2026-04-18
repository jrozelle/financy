#!/usr/bin/env python
"""
Seed la base de dev locale avec quelques donnees de test pour la feature
actifs & conseil patrimonial.

Usage :
    DB_PATH=financy_dev.db python scripts/seed_dev.py

Le script est idempotent : il supprime d'abord les donnees de test (par marqueur
sur 'notes') avant de reinserer. Il ne touche jamais une DB de prod.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import get_db, init_db  # noqa: E402

SEED_MARKER = '[seed_dev]'
TODAY = date.today().isoformat()

# Position PEA de test avec 3 ISIN reels (3 ETF largement diffuses en France)
SEED_OWNER = 'Seed Utilisateur'
SEED_POSITION = {
    'date': TODAY,
    'owner': SEED_OWNER,
    'category': 'Actions',
    'envelope': 'PEA',
    'establishment': 'Seed Banque',
    'value': 0,  # sera recalcule depuis les holdings en phase 1
    'debt': 0,
    'notes': SEED_MARKER + ' PEA de test avec 3 ETF',
    'entity': None,
    'ownership_pct': 1.0,
    'debt_pct': 1.0,
}

# Donnees holdings prepretes pour la phase 1 (seront inserees quand la table
# existera ; pour l'instant on stocke juste la position sans granularite).
SEED_HOLDINGS = [
    {'isin': 'FR0010315770', 'name': 'Amundi MSCI World (CW8)',
     'quantity': 20, 'cost_basis': 8000, 'market_value': 9800},
    {'isin': 'IE00B4L5Y983', 'name': 'iShares Core MSCI World (IWDA)',
     'quantity': 50, 'cost_basis': 4500, 'market_value': 5200},
    {'isin': 'FR0011550185', 'name': 'Amundi MSCI EM Asia (PAASI)',
     'quantity': 30, 'cost_basis': 1200, 'market_value': 1150},
]


def main():
    db_path = os.environ.get('DB_PATH', 'financy_dev.db')
    if 'patrimoine.db' in db_path and 'dev' not in db_path:
        print(f'Refus : DB_PATH={db_path!r} ressemble a une DB de prod.')
        print('Utilisez DB_PATH=financy_dev.db ou equivalent.')
        sys.exit(1)

    print(f'DB cible : {db_path}')
    init_db()

    with get_db() as conn:
        # Purge des donnees de test precedentes
        conn.execute(
            "DELETE FROM positions WHERE notes LIKE ?",
            (f'%{SEED_MARKER}%',)
        )

        # Insertion de la position de test
        cur = conn.execute(
            '''INSERT INTO positions
               (date, owner, category, envelope, establishment, value, debt,
                notes, entity, ownership_pct, debt_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (SEED_POSITION['date'], SEED_POSITION['owner'],
             SEED_POSITION['category'], SEED_POSITION['envelope'],
             SEED_POSITION['establishment'], SEED_POSITION['value'],
             SEED_POSITION['debt'], SEED_POSITION['notes'],
             SEED_POSITION['entity'], SEED_POSITION['ownership_pct'],
             SEED_POSITION['debt_pct'])
        )
        position_id = cur.lastrowid
        print(f'Position seedee : id={position_id} ({SEED_POSITION["envelope"]})')

        # Insertion des holdings si la table existe (phase 1+)
        has_holdings = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='holdings'"
        ).fetchone()
        if has_holdings:
            has_securities = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='securities'"
            ).fetchone()
            for h in SEED_HOLDINGS:
                if has_securities:
                    conn.execute(
                        '''INSERT OR IGNORE INTO securities
                           (isin, name, currency, asset_class, is_priceable, data_source)
                           VALUES (?,?,?,?,?,?)''',
                        (h['isin'], h['name'], 'EUR', 'etf', 1, 'manual')
                    )
                conn.execute(
                    '''INSERT INTO holdings
                       (position_id, isin, quantity, cost_basis, market_value, as_of_date)
                       VALUES (?,?,?,?,?,?)''',
                    (position_id, h['isin'], h['quantity'],
                     h['cost_basis'], h['market_value'], TODAY)
                )
            print(f'{len(SEED_HOLDINGS)} holdings seedes.')
        else:
            print('Table holdings absente (migration 005 non appliquee) : skip.')

    print('Seed termine.')


if __name__ == '__main__':
    main()
