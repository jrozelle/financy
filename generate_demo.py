#!/usr/bin/env python3
"""Génère une base de données de démonstration avec des données 100% fictives."""

import sqlite3
import json
import os
import random
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), 'demo.db')

OWNERS = ['Alice', 'Bob', 'Emma', 'Lucas']

CATEGORIES = [
    'Cash & dépôts', 'Monétaire', 'Obligations', 'Actions',
    'Immobilier', 'SCPI', 'Fond Euro', 'Produits Structurés',
    'Crypto', 'Objets de valeur', 'Autre'
]

ENVELOPE_META = {
    'Compte courant':  {'liquidity': 'J0–J1',  'friction': 'Aucune'},
    'Livret A':        {'liquidity': 'J2–J7',  'friction': 'Fiscale'},
    'LDDS':            {'liquidity': 'J0–J1',  'friction': 'Aucune'},
    'PEA':             {'liquidity': 'J2–J7',  'friction': 'Fiscale'},
    'CTO':             {'liquidity': 'J2–J7',  'friction': 'Fiscale'},
    'Assurance-vie':   {'liquidity': 'J8–J30', 'friction': 'Mixte'},
    'PER':             {'liquidity': 'Bloqué', 'friction': 'Fiscale'},
    'Crypto':          {'liquidity': 'J0–J1',  'friction': 'Décote probable'},
    'Immobilier':      {'liquidity': '30J+',   'friction': 'Mixte'},
    'SCI':             {'liquidity': '30J+',   'friction': 'Mixte'},
}

CATEGORY_MOBILIZABLE = {
    'Cash & dépôts': 1.0, 'Monétaire': 0.95, 'Obligations': 0.95,
    'Actions': 0.9, 'Immobilier': 0.0, 'SCPI': 0.0, 'Fond Euro': 0.95,
    'Produits Structurés': 0.0, 'Crypto': 0.9, 'Objets de valeur': 0.0, 'Autre': 0.8,
}

FLUX_TYPES = ['Versement', 'Retrait', 'Dividende/Intérêt', 'Frais', 'Autre']
ENTITY_TYPES = ['SCI', 'Indivision', 'Holding', 'Autre']
VALUATION_MODES = ['Valeur de marché', "Prix d'acquisition", 'Valeur fiscale', 'Autre']
LIQUIDITY_ORDER = ['J0–J1', 'J2–J7', 'J8–J30', '30J+', 'Bloqué']

ESTABLISHMENTS = [
    'Banque Azur', 'Crédit du Lac', 'Néo Banque', 'Patrimoine & Cie',
    'Bourse Direct', 'Assur Plus', 'Crypto Valley',
]


def create_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT    NOT NULL,
            owner           TEXT    NOT NULL,
            category        TEXT    NOT NULL,
            envelope        TEXT,
            establishment   TEXT,
            value           REAL    DEFAULT 0,
            debt            REAL    DEFAULT 0,
            notes           TEXT,
            entity          TEXT,
            ownership_pct   REAL    DEFAULT 1.0,
            debt_pct        REAL    DEFAULT 1.0,
            mobilizable_pct_override REAL DEFAULT NULL,
            created_at      TEXT    DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE entities (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT    NOT NULL UNIQUE,
            type             TEXT,
            valuation_mode   TEXT,
            gross_assets     REAL    DEFAULT 0,
            debt             REAL    DEFAULT 0,
            comment          TEXT,
            created_at       TEXT    DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE flux (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT    NOT NULL,
            owner       TEXT    NOT NULL,
            envelope    TEXT,
            type        TEXT,
            amount      REAL    NOT NULL,
            notes       TEXT,
            category    TEXT,
            created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_positions_date ON positions(date);
        CREATE INDEX idx_flux_date      ON flux(date);
        CREATE TABLE snapshot_notes (
            date  TEXT PRIMARY KEY,
            notes TEXT NOT NULL
        );
        CREATE TABLE config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE entity_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_name  TEXT NOT NULL,
            date         TEXT NOT NULL,
            gross_assets REAL DEFAULT 0,
            debt         REAL DEFAULT 0,
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_name, date)
        );
        CREATE INDEX idx_entity_snap ON entity_snapshots(entity_name, date);
        CREATE TABLE schema_version (
            id      INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO schema_version (id, version) VALUES (1, 3);
    ''')
    return conn


def jitter(base, pct=0.05):
    """Variation aléatoire autour d'une valeur de base."""
    return round(base * (1 + random.uniform(-pct, pct)), 2)


def generate():
    random.seed(42)
    conn = create_db()

    # ── Référentiel custom ──
    ref = {
        'owners': OWNERS,
        'categories': CATEGORIES,
        'category_mobilizable': CATEGORY_MOBILIZABLE,
        'envelope_meta': ENVELOPE_META,
        'entity_types': ENTITY_TYPES,
        'valuation_modes': VALUATION_MODES,
        'flux_types': FLUX_TYPES,
    }
    conn.execute(
        "INSERT INTO config (key, value) VALUES ('referential', ?)",
        (json.dumps(ref),)
    )

    # ── Entités ──
    entities = [
        {'name': 'SCI Horizon',   'type': 'SCI',        'valo': 'Valeur de marché',
         'gross': 320000, 'debt': 180000, 'comment': 'Appartement T3 Lyon 6e'},
        {'name': 'Indivision Villa', 'type': 'Indivision', 'valo': "Prix d'acquisition",
         'gross': 450000, 'debt': 120000, 'comment': 'Maison familiale Annecy'},
    ]
    for e in entities:
        conn.execute(
            'INSERT INTO entities (name, type, valuation_mode, gross_assets, debt, comment) VALUES (?,?,?,?,?,?)',
            (e['name'], e['type'], e['valo'], e['gross'], e['debt'], e['comment'])
        )

    # ── Positions templates (valeur de base au 1er snapshot) ──
    # owner, category, envelope, establishment, value, debt, entity, ownership_pct, debt_pct, notes
    positions_tpl = [
        # Alice
        ('Alice', 'Cash & dépôts', 'Compte courant', 'Banque Azur',     8500, 0, None, 1.0, 1.0, None),
        ('Alice', 'Cash & dépôts', 'Livret A',       'Banque Azur',    22950, 0, None, 1.0, 1.0, None),
        ('Alice', 'Actions',       'PEA',            'Bourse Direct',  45000, 0, None, 1.0, 1.0, 'ETF World + CAC40'),
        ('Alice', 'Fond Euro',     'Assurance-vie',  'Assur Plus',     32000, 0, None, 1.0, 1.0, 'Contrat ouvert 2019'),
        ('Alice', 'Crypto',        'Crypto',         'Crypto Valley',   6200, 0, None, 1.0, 1.0, 'BTC + ETH'),
        ('Alice', 'Immobilier',    'SCI',            'SCI Horizon',        0, 0, 'SCI Horizon', 0.5, 0.5, None),

        # Bob
        ('Bob', 'Cash & dépôts',   'Compte courant', 'Crédit du Lac',   5200, 0, None, 1.0, 1.0, None),
        ('Bob', 'Cash & dépôts',   'LDDS',           'Crédit du Lac',  12000, 0, None, 1.0, 1.0, None),
        ('Bob', 'Actions',         'CTO',            'Bourse Direct',  28000, 0, None, 1.0, 1.0, 'Actions US tech'),
        ('Bob', 'Obligations',     'Assurance-vie',  'Assur Plus',     18000, 0, None, 1.0, 1.0, 'Fonds obligataire'),
        ('Bob', 'Immobilier',      'SCI',            'SCI Horizon',        0, 0, 'SCI Horizon', 0.5, 0.5, None),
        ('Bob', 'Immobilier',      'Immobilier',     'Patrimoine & Cie', 0,  0, 'Indivision Villa', 0.4, 0.4, None),

        # Emma (enfant — petits montants)
        ('Emma', 'Cash & dépôts',  'Livret A',       'Banque Azur',     3800, 0, None, 1.0, 1.0, 'Livret jeune'),
        ('Emma', 'Fond Euro',      'Assurance-vie',  'Assur Plus',      5000, 0, None, 1.0, 1.0, 'Contrat mineur'),

        # Lucas (enfant)
        ('Lucas', 'Cash & dépôts', 'Livret A',       'Crédit du Lac',   2900, 0, None, 1.0, 1.0, 'Livret jeune'),
        ('Lucas', 'Monétaire',     'Assurance-vie',  'Assur Plus',      4500, 0, None, 1.0, 1.0, 'Contrat mineur'),
    ]

    # ── Snapshots : un par trimestre sur 2 ans ──
    base_date = datetime(2024, 1, 1)
    snapshot_dates = []
    for i in range(9):  # Q1 2024 → Q1 2026
        d = base_date + timedelta(days=91 * i)
        snapshot_dates.append(d.strftime('%Y-%m-%d'))

    # Tendances de croissance par catégorie (par trimestre)
    growth = {
        'Cash & dépôts': 0.002, 'Monétaire': 0.008, 'Obligations': 0.006,
        'Actions': 0.035, 'Fond Euro': 0.005, 'Crypto': 0.06,
        'Immobilier': 0.01, 'SCPI': 0.01, 'Produits Structurés': 0.0,
        'Objets de valeur': 0.0, 'Autre': 0.0,
    }

    # Évolution des entités
    entity_growth = {'SCI Horizon': 0.012, 'Indivision Villa': 0.008}
    entity_debt_reduction = {'SCI Horizon': 2500, 'Indivision Villa': 1800}

    entity_values = {}
    for e in entities:
        entity_values[e['name']] = {'gross': e['gross'], 'debt': e['debt']}

    for si, snap_date in enumerate(snapshot_dates):
        # Mettre à jour les entités
        for ename, vals in entity_values.items():
            if si > 0:
                g = entity_growth[ename]
                vals['gross'] = round(vals['gross'] * (1 + g + random.uniform(-0.005, 0.005)), 2)
                vals['debt'] = max(0, round(vals['debt'] - entity_debt_reduction[ename], 2))
            # Entity snapshot
            conn.execute(
                'INSERT OR REPLACE INTO entity_snapshots (entity_name, date, gross_assets, debt) VALUES (?,?,?,?)',
                (ename, snap_date, vals['gross'], vals['debt'])
            )

        # Update entité courante (dernier snapshot)
        if si == len(snapshot_dates) - 1:
            for ename, vals in entity_values.items():
                conn.execute(
                    'UPDATE entities SET gross_assets=?, debt=? WHERE name=?',
                    (vals['gross'], vals['debt'], ename)
                )

        # Positions
        for tpl in positions_tpl:
            owner, cat, env, estab, base_val, base_debt, entity, own_pct, debt_pct, notes = tpl
            if entity:
                val = 0
                debt = 0
            else:
                g = growth.get(cat, 0)
                multiplier = (1 + g) ** si
                val = round(base_val * multiplier * (1 + random.uniform(-0.02, 0.02)), 2)
                debt = round(base_debt * max(0, 1 - 0.01 * si), 2)
            conn.execute(
                '''INSERT INTO positions (date, owner, category, envelope, establishment,
                   value, debt, notes, entity, ownership_pct, debt_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (snap_date, owner, cat, env, estab, val, debt, notes, entity, own_pct, debt_pct)
            )

    # ── Flux ──
    # (date, owner, envelope, type, amount, notes, category)
    flux_data = []
    for si in range(len(snapshot_dates)):
        d = snapshot_dates[si]
        flux_data.append((d, 'Alice', 'PEA',          'Versement',          500, 'Versement mensuel PEA', 'Actions'))
        flux_data.append((d, 'Alice', 'Assurance-vie', 'Versement',         200, 'Versement programmé AV', 'Fond Euro'))
        flux_data.append((d, 'Bob',   'CTO',           'Versement',         300, 'DCA actions US', 'Actions'))
        flux_data.append((d, 'Bob',   'Assurance-vie',  'Versement',        150, 'Versement obligataire', 'Obligations'))
        if si % 2 == 1:
            flux_data.append((d, 'Alice', 'PEA',       'Dividende/Intérêt', 320, 'Dividendes ETF', 'Actions'))
            flux_data.append((d, 'Bob',   'CTO',       'Dividende/Intérêt', 180, 'Dividendes actions', 'Actions'))
            flux_data.append((d, 'Alice', 'Livret A',  'Dividende/Intérêt',  85, 'Intérêts livret', 'Cash & dépôts'))
        if si % 4 == 3:
            flux_data.append((d, 'Alice', 'Assurance-vie', 'Frais', -120, 'Frais de gestion AV', 'Fond Euro'))
            flux_data.append((d, 'Bob',   'Assurance-vie', 'Frais',  -95, 'Frais de gestion AV', 'Obligations'))
        if si % 4 == 0:
            flux_data.append((d, 'Emma',  'Livret A',      'Versement', 200, 'Cadeau anniversaire', 'Cash & dépôts'))
            flux_data.append((d, 'Lucas', 'Livret A',      'Versement', 200, 'Cadeau anniversaire', 'Cash & dépôts'))

    for date, owner, env, ftype, amount, notes, cat in flux_data:
        conn.execute(
            'INSERT INTO flux (date, owner, envelope, type, amount, notes, category) VALUES (?,?,?,?,?,?,?)',
            (date, owner, env, ftype, amount, notes, cat)
        )

    # ── Notes de snapshots ──
    snapshot_notes = {
        snapshot_dates[0]: 'Situation initiale — début du suivi',
        snapshot_dates[4]: 'Achat parts SCPI envisagé mais reporté',
        snapshot_dates[-1]: 'Point annuel — bonne progression Actions',
    }
    for d, note in snapshot_notes.items():
        conn.execute('INSERT INTO snapshot_notes (date, notes) VALUES (?, ?)', (d, note))

    # ── Objectif patrimoine ──
    conn.execute(
        "INSERT INTO config (key, value) VALUES ('wealth_target', ?)",
        (json.dumps({'target': 500000}),)
    )

    # ── Allocation cible ──
    targets = {
        'Cash & dépôts': 10, 'Monétaire': 5, 'Obligations': 10,
        'Actions': 35, 'Immobilier': 25, 'SCPI': 0, 'Fond Euro': 10,
        'Crypto': 5,
    }
    conn.execute(
        "INSERT INTO config (key, value) VALUES ('allocation_targets', ?)",
        (json.dumps(targets),)
    )

    # ── Alertes ──
    alerts = [
        {'category': 'Actions', 'operator': '<', 'value': 30, 'label': 'Actions sous 30%'},
        {'category': 'Cash & dépôts', 'operator': '>', 'value': 15, 'label': 'Trop de cash'},
    ]
    conn.execute(
        "INSERT INTO config (key, value) VALUES ('user_alerts', ?)",
        (json.dumps(alerts),)
    )

    conn.commit()
    conn.close()
    print(f"✓ demo.db générée ({DB_PATH})")


if __name__ == '__main__':
    generate()
