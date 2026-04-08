import sqlite3
import json
import os
import re
from datetime import datetime
from contextlib import contextmanager

_BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(_BASE_DIR, 'patrimoine.db')
DEMO_DB_PATH = os.path.join(_BASE_DIR, 'demo.db')

_demo_mode = False

def is_demo_mode():
    return _demo_mode

def set_demo_mode(enabled):
    global _demo_mode
    _demo_mode = enabled

def get_db_path():
    return DEMO_DB_PATH if _demo_mode else DB_PATH

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

# ─── Référentiels ────────────────────────────────────────────────────────────

OWNERS = ['Personne 1', 'Personne 2', 'Personne 3', 'Personne 4']

CATEGORIES = [
    'Cash & dépôts', 'Monétaire', 'Obligations', 'Actions',
    'Immobilier', 'SCPI', 'Fond Euro', 'Produits Structurés',
    'Crypto', 'Objets de valeur', 'Autre'
]

ENVELOPE_META = {
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

CATEGORY_MOBILIZABLE = {
    'Cash & dépôts':       1.0,
    'Monétaire':           0.95,
    'Obligations':         0.95,
    'Actions':             0.9,
    'Immobilier':          0.0,
    'SCPI':                0.0,
    'Fond Euro':           0.95,
    'Produits Structurés': 0.0,
    'Crypto':              0.9,
    'Objets de valeur':    0.0,
    'Autre':               0.8,
}

FLUX_TYPES = ['Versement', 'Retrait', 'Dividende/Intérêt', 'Frais', 'Autre']
LIQUIDITY_ORDER = ['J0–J1', 'J2–J7', 'J8–J30', '30J+', 'Bloqué']
ENTITY_TYPES = ['SCI', 'Indivision', 'Holding', 'Autre']
VALUATION_MODES = ['Valeur de marché', "Prix d'acquisition", 'Valeur fiscale', 'Autre']

DEFAULT_REFERENTIAL = {
    'owners':               OWNERS,
    'categories':           CATEGORIES,
    'category_mobilizable': CATEGORY_MOBILIZABLE,
    'envelope_meta':        ENVELOPE_META,
    'entity_types':         ENTITY_TYPES,
    'valuation_modes':      VALUATION_MODES,
    'flux_types':           FLUX_TYPES,
    'liquidity_order':      LIQUIDITY_ORDER,
}

# ─── Référentiel dynamique ───────────────────────────────────────────────────

def load_referential(conn):
    """Charge le référentiel depuis la DB ; fallback sur les defaults."""
    row = conn.execute("SELECT value FROM config WHERE key='referential'").fetchone()
    if row:
        try:
            stored = json.loads(row['value'])
            ref = dict(DEFAULT_REFERENTIAL)
            ref.update(stored)
            ref['liquidity_order'] = LIQUIDITY_ORDER
            return ref
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


def init_db():
    with get_db() as conn:
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
        ''')
        try:
            conn.execute('ALTER TABLE positions ADD COLUMN mobilizable_pct_override REAL DEFAULT NULL')
        except Exception:
            pass

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
