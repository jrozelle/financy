import sqlite3
import json
import os
import re
from datetime import datetime
from contextlib import contextmanager

_BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.environ.get('DB_PATH') or os.path.join(_BASE_DIR, 'patrimoine.db')
DEMO_DB_PATH = os.path.join(_BASE_DIR, 'demo.db')

_demo_mode = False

def is_demo_mode():
    """Check demo mode — prefers request-local (Flask g) over global."""
    try:
        from flask import g
        return getattr(g, '_demo_mode', _demo_mode)
    except RuntimeError:
        return _demo_mode

def set_demo_mode(enabled):
    """Set demo mode — writes to both request-local (Flask g) and global fallback."""
    global _demo_mode
    _demo_mode = enabled
    try:
        from flask import g
        g._demo_mode = enabled
    except RuntimeError:
        pass  # Outside request context (CLI, tests)

def get_db_path():
    return DEMO_DB_PATH if is_demo_mode() else DB_PATH

# ─── Validation ───────────────────────────────────────────────────────────────

def validate_date(s):
    """Vérifie que la chaîne est une date ISO valide (YYYY-MM-DD)."""
    if not s or not isinstance(s, str):
        return False
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return False
    try:
        datetime.strptime(s, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def validate_number(v, allow_negative=False):
    """Vérifie que v est un nombre valide."""
    if v is None:
        return True
    try:
        n = float(v)
        if not allow_negative and n < 0:
            return False
        return True
    except (ValueError, TypeError):
        return False

def validate_string(s, max_length=500):
    """Vérifie que s est une chaîne non vide et raisonnable."""
    if s is None:
        return True
    return isinstance(s, str) and len(s) <= max_length

def validate_pct(v):
    """Vérifie que v est un pourcentage entre 0 et 1."""
    if v is None:
        return True
    try:
        n = float(v)
        return 0 <= n <= 1.0001  # petite marge pour les arrondis
    except (ValueError, TypeError):
        return False

# ─── Référentiels — constantes structurelles ─────────────────────────────────

LIQUIDITY_ORDER = ['J0–J1', 'J2–J7', 'J8–J30', '30J+', 'Bloqué']

# ─── Modèles de référentiel ──────────────────────────────────────────────────

_ENVELOPES_FULL = {
    'Compte courant':  {'liquidity': 'J0–J1',  'friction': 'Aucune'},
    'Livret A':        {'liquidity': 'J2–J7',  'friction': 'Fiscale'},
    'LDDS':            {'liquidity': 'J0–J1',  'friction': 'Aucune'},
    'Livret Bourso+':  {'liquidity': 'J0–J1',  'friction': 'Aucune'},
    'PEL/CEL':         {'liquidity': 'J8–J30', 'friction': 'Frais'},
    'PEA':             {'liquidity': 'J2–J7',  'friction': 'Fiscale'},
    'CTO':             {'liquidity': 'J2–J7',  'friction': 'Fiscale'},
    'Assurance-vie':   {'liquidity': 'J8–J30', 'friction': 'Mixte'},
    'PER':             {'liquidity': 'Bloqué', 'friction': 'Fiscale'},
    'Crypto':          {'liquidity': 'J0–J1',  'friction': 'Décote probable'},
    'Immobilier':      {'liquidity': '30J+',   'friction': 'Mixte'},
    'SCI':             {'liquidity': '30J+',   'friction': 'Mixte'},
    'Dette':           {'liquidity': 'Bloqué', 'friction': 'Aucune'},
    'Autre':           {'liquidity': '30J+',   'friction': 'Mixte'},
}

_CATEGORIES_FULL = [
    'Cash & dépôts', 'Monétaire', 'Obligations', 'Actions',
    'Immobilier', 'SCPI', 'Fond Euro', 'Produits Structurés',
    'Crypto', 'Objets de valeur', 'Autre'
]

_MOBILIZABLE_FULL = {
    'Cash & dépôts': 1.0, 'Monétaire': 0.95, 'Obligations': 0.95,
    'Actions': 0.9, 'Immobilier': 0.0, 'SCPI': 0.0, 'Fond Euro': 0.95,
    'Produits Structurés': 0.0, 'Crypto': 0.9, 'Objets de valeur': 0.0, 'Autre': 0.8,
}

_FLUX_TYPES = ['Versement', 'Retrait', 'Dividende/Intérêt', 'Frais', 'Autre']
_ENTITY_TYPES = ['SCI', 'Indivision', 'Holding', 'Autre']
_VALUATION_MODES = ['Valeur de marché', "Prix d'acquisition", 'Valeur fiscale', 'Autre']

REFERENTIAL_TEMPLATES = {
    'Famille (4 personnes)': {
        'owners':               ['Personne 1', 'Personne 2', 'Personne 3', 'Personne 4'],
        'categories':           _CATEGORIES_FULL,
        'category_mobilizable': _MOBILIZABLE_FULL,
        'envelope_meta':        _ENVELOPES_FULL,
        'entity_types':         _ENTITY_TYPES,
        'valuation_modes':      _VALUATION_MODES,
        'flux_types':           _FLUX_TYPES,
    },
    'Couple': {
        'owners':               ['Personne 1', 'Personne 2'],
        'categories':           _CATEGORIES_FULL,
        'category_mobilizable': _MOBILIZABLE_FULL,
        'envelope_meta':        _ENVELOPES_FULL,
        'entity_types':         _ENTITY_TYPES,
        'valuation_modes':      _VALUATION_MODES,
        'flux_types':           _FLUX_TYPES,
    },
    'Solo': {
        'owners':               ['Moi'],
        'categories':           _CATEGORIES_FULL,
        'category_mobilizable': _MOBILIZABLE_FULL,
        'envelope_meta':        {k: v for k, v in _ENVELOPES_FULL.items() if k != 'SCI'},
        'entity_types':         _ENTITY_TYPES,
        'valuation_modes':      _VALUATION_MODES,
        'flux_types':           _FLUX_TYPES,
    },
    'Simplifié': {
        'owners':               ['Personne 1', 'Personne 2'],
        'categories':           ['Cash & dépôts', 'Actions', 'Obligations', 'Immobilier', 'Autre'],
        'category_mobilizable': {'Cash & dépôts': 1.0, 'Actions': 0.9, 'Obligations': 0.95, 'Immobilier': 0.0, 'Autre': 0.8},
        'envelope_meta':        {k: v for k, v in _ENVELOPES_FULL.items()
                                 if k in ('Compte courant', 'Livret A', 'PEA', 'Assurance-vie', 'Immobilier', 'Autre')},
        'entity_types':         ['SCI', 'Indivision', 'Autre'],
        'valuation_modes':      _VALUATION_MODES,
        'flux_types':           _FLUX_TYPES,
    },
}

# Le template par défaut, utilisé pour le seed initial et comme fallback
DEFAULT_TEMPLATE_NAME = 'Famille (4 personnes)'
DEFAULT_REFERENTIAL = {**REFERENTIAL_TEMPLATES[DEFAULT_TEMPLATE_NAME], 'liquidity_order': LIQUIDITY_ORDER}

# Aliases pour la rétrocompatibilité (tests, compute_position fallback)
OWNERS = DEFAULT_REFERENTIAL['owners']
CATEGORIES = DEFAULT_REFERENTIAL['categories']
ENVELOPE_META = DEFAULT_REFERENTIAL['envelope_meta']
CATEGORY_MOBILIZABLE = DEFAULT_REFERENTIAL['category_mobilizable']
FLUX_TYPES = DEFAULT_REFERENTIAL['flux_types']
ENTITY_TYPES = DEFAULT_REFERENTIAL['entity_types']
VALUATION_MODES = DEFAULT_REFERENTIAL['valuation_modes']

# ─── Référentiel dynamique ───────────────────────────────────────────────────

def load_referential(conn):
    """Charge le référentiel depuis la DB (seedé à l'init)."""
    row = conn.execute("SELECT value FROM config WHERE key='referential'").fetchone()
    if row:
        try:
            stored = json.loads(row['value'])
            stored['liquidity_order'] = LIQUIDITY_ORDER
            # Garantir les clés structurelles
            for key in ('categories', 'owners', 'envelope_meta', 'category_mobilizable',
                        'entity_types', 'valuation_modes', 'flux_types'):
                if key not in stored:
                    stored[key] = DEFAULT_REFERENTIAL[key]
            return stored
        except Exception:
            pass
    return dict(DEFAULT_REFERENTIAL)

# ─── Base de données ─────────────────────────────────────────────────────────

@contextmanager
def get_db():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _get_schema_version(conn):
    """Retourne la version actuelle du schéma (0 si table absente)."""
    try:
        row = conn.execute('SELECT version FROM schema_version').fetchone()
        return row['version'] if row else 0
    except Exception:
        return 0


def _set_schema_version(conn, version):
    conn.execute('INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)', (version,))


# ─── Migrations séquentielles ─────────────────────────────────────────────────
# Chaque migration reçoit la connexion et fait ses modifications.
# Les migrations sont idempotentes (CREATE IF NOT EXISTS, ALTER avec try/except).

def _migration_001(conn):
    """Schéma initial : tables positions, entities, flux, config, entity_snapshots, snapshot_notes."""
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS positions (
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
            created_at      TEXT    DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS entities (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT    NOT NULL UNIQUE,
            type             TEXT,
            valuation_mode   TEXT,
            gross_assets     REAL    DEFAULT 0,
            debt             REAL    DEFAULT 0,
            comment          TEXT,
            created_at       TEXT    DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS flux (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT    NOT NULL,
            owner       TEXT    NOT NULL,
            envelope    TEXT,
            type        TEXT,
            amount      REAL    NOT NULL,
            notes       TEXT,
            created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_positions_date ON positions(date);
        CREATE INDEX IF NOT EXISTS idx_flux_date      ON flux(date);
        CREATE TABLE IF NOT EXISTS config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS entity_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_name  TEXT NOT NULL,
            date         TEXT NOT NULL,
            gross_assets REAL DEFAULT 0,
            debt         REAL DEFAULT 0,
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_name, date)
        );
        CREATE INDEX IF NOT EXISTS idx_entity_snap ON entity_snapshots(entity_name, date);
        CREATE TABLE IF NOT EXISTS snapshot_notes (
            date  TEXT PRIMARY KEY,
            notes TEXT NOT NULL
        );
    ''')


def _migration_002(conn):
    """Ajout colonnes mobilizable_pct_override (positions) et category (flux)."""
    for col, definition, table in [
        ('mobilizable_pct_override', 'REAL DEFAULT NULL', 'positions'),
        ('category', 'TEXT', 'flux'),
    ]:
        try:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')
        except Exception:
            pass  # colonne déjà existante


def _migration_003(conn):
    """Seed du référentiel par défaut si absent."""
    existing = conn.execute("SELECT 1 FROM config WHERE key='referential'").fetchone()
    if not existing:
        seed = dict(REFERENTIAL_TEMPLATES[DEFAULT_TEMPLATE_NAME])
        conn.execute(
            "INSERT INTO config (key, value) VALUES ('referential', ?)",
            (json.dumps(seed),)
        )


def _migration_004(conn):
    """Ajout d'index pour les requêtes fréquentes."""
    for stmt in [
        'CREATE INDEX IF NOT EXISTS idx_positions_owner ON positions(owner)',
        'CREATE INDEX IF NOT EXISTS idx_positions_entity ON positions(entity)',
        'CREATE INDEX IF NOT EXISTS idx_positions_date_owner ON positions(date, owner)',
    ]:
        conn.execute(stmt)


# Registre des migrations — ajouter les futures migrations ici
MIGRATIONS = [
    (1, _migration_001),
    (2, _migration_002),
    (3, _migration_003),
    (4, _migration_004),
]


def init_db():
    with get_db() as conn:
        # Créer la table de versionnement
        conn.execute('''
            CREATE TABLE IF NOT EXISTS schema_version (
                id      INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL DEFAULT 0
            )
        ''')
        current = _get_schema_version(conn)

        for version, migrate_fn in MIGRATIONS:
            if version > current:
                migrate_fn(conn)
                _set_schema_version(conn, version)

        # Pour les DB existantes sans schema_version, s'assurer qu'on enregistre la version max
        if current == 0 and MIGRATIONS:
            _set_schema_version(conn, MIGRATIONS[-1][0])

# ─── Calculs ─────────────────────────────────────────────────────────────────

def compute_position(pos, entity_map=None, ref=None):
    if ref is None:
        ref = DEFAULT_REFERENTIAL
    ownership_pct = pos.get('ownership_pct') if pos.get('ownership_pct') is not None else 1.0
    debt_pct      = pos.get('debt_pct')      if pos.get('debt_pct')      is not None else 1.0
    category      = pos.get('category', '')
    envelope      = pos.get('envelope', '') or ''
    entity        = pos.get('entity')

    if entity and entity_map and entity in entity_map:
        value = entity_map[entity]['gross_assets'] or 0
        debt  = entity_map[entity]['debt'] or 0
    else:
        value = pos.get('value') or 0
        debt  = pos.get('debt') or 0

    gross_attributed = value * ownership_pct
    debt_attributed  = debt * debt_pct
    net_attributed   = gross_attributed - debt_attributed

    env_meta         = ref.get('envelope_meta', ENVELOPE_META)
    cat_mob          = ref.get('category_mobilizable', CATEGORY_MOBILIZABLE)
    env              = env_meta.get(envelope, {'liquidity': '30J+', 'friction': 'Mixte'})
    override         = pos.get('mobilizable_pct_override')
    mobilizable_pct  = override if override is not None else cat_mob.get(category, 0.8)
    mobilizable_val  = net_attributed * mobilizable_pct if net_attributed > 0 else 0

    return {
        **pos,
        'net_value':         value - debt,
        'gross_attributed':  gross_attributed,
        'debt_attributed':   debt_attributed,
        'net_attributed':    net_attributed,
        'liquidity':         env['liquidity'],
        'friction':          env['friction'],
        'mobilizable_pct':   mobilizable_pct,
        'mobilizable_value': mobilizable_val,
    }


def get_entity_map(conn, date=None):
    if date:
        rows = conn.execute('''
            SELECT e.name,
                   COALESCE(s.gross_assets, e.gross_assets) AS gross_assets,
                   COALESCE(s.debt,         e.debt)         AS debt
            FROM entities e
            LEFT JOIN entity_snapshots s
              ON s.entity_name = e.name
             AND s.date = (
                 SELECT MAX(date) FROM entity_snapshots es2
                 WHERE es2.entity_name = e.name AND es2.date <= ?
             )
        ''', (date,)).fetchall()
    else:
        rows = conn.execute('SELECT name, gross_assets, debt FROM entities').fetchall()
    return {r['name']: {'gross_assets': r['gross_assets'] or 0, 'debt': r['debt'] or 0}
            for r in rows}
