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


# Pseudo-ISIN pour les fonds euros et actifs non cotés :
# format 'FONDS_EUROS_<slug>' ou 'CUSTOM_<slug>', longueur libre, bypass du checksum.
_PSEUDO_ISIN_PREFIXES = ('FONDS_EUROS_', 'CUSTOM_')
_ISIN_RE = re.compile(r'^[A-Z]{2}[A-Z0-9]{9}[0-9]$')


def _isin_checksum_valid(isin):
    """Algorithme Luhn modifié pour ISIN (ISO 6166).

    Remplace les lettres par leur valeur (A=10..Z=35) puis applique Luhn sur la
    chaîne numérique résultante. La somme totale doit être divisible par 10.
    """
    expanded = ''.join(
        str(ord(c) - ord('A') + 10) if c.isalpha() else c
        for c in isin
    )
    total = 0
    # De droite à gauche : les positions paires (0, 2, 4...) sont prises telles
    # quelles, les positions impaires sont doublées puis les chiffres additionnés.
    for i, digit in enumerate(reversed(expanded)):
        n = int(digit)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def validate_isin(isin):
    """Vérifie qu'une chaîne est un ISIN valide ou un pseudo-ISIN autorisé.

    - ISIN standard : 12 caractères, 2 lettres pays + 9 alphanum + 1 chiffre check.
    - Pseudo-ISIN : préfixé 'FONDS_EUROS_' ou 'CUSTOM_' (fonds euros, actifs custom).
    """
    if not isin or not isinstance(isin, str):
        return False
    isin = isin.strip().upper()
    if any(isin.startswith(p) for p in _PSEUDO_ISIN_PREFIXES):
        return len(isin) <= 64 and all(
            c.isalnum() or c == '_' for c in isin
        )
    if not _ISIN_RE.match(isin):
        return False
    return _isin_checksum_valid(isin)


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


def _migration_005(conn):
    """Feature actifs : tables securities, holdings, price_history, holdings_snapshots.

    Les positions existantes restent intactes. Tant qu'une position n'a pas de
    holdings, son comportement (value/debt manuels) est identique à avant.
    """
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS securities (
            isin             TEXT PRIMARY KEY,
            name             TEXT,
            ticker           TEXT,
            currency         TEXT DEFAULT 'EUR',
            asset_class      TEXT,
            is_priceable     INTEGER DEFAULT 1,
            last_price       REAL,
            last_price_date  TEXT,
            data_source      TEXT,
            created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at       TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS holdings (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id  INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
            isin         TEXT NOT NULL REFERENCES securities(isin),
            quantity     REAL NOT NULL,
            cost_basis   REAL,
            market_value REAL,
            as_of_date   TEXT,
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_holdings_position ON holdings(position_id);
        CREATE INDEX IF NOT EXISTS idx_holdings_isin     ON holdings(isin);
        CREATE TABLE IF NOT EXISTS price_history (
            isin  TEXT NOT NULL,
            date  TEXT NOT NULL,
            price REAL NOT NULL,
            PRIMARY KEY (isin, date)
        );
        CREATE TABLE IF NOT EXISTS holdings_snapshots (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date  TEXT NOT NULL,
            position_id    INTEGER NOT NULL,
            isin           TEXT NOT NULL,
            quantity       REAL,
            cost_basis     REAL,
            price          REAL,
            market_value   REAL,
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_holdings_snap_date ON holdings_snapshots(snapshot_date);
        CREATE INDEX IF NOT EXISTS idx_holdings_snap_pos  ON holdings_snapshots(position_id);
    ''')


# Registre des migrations — ajouter les futures migrations ici
MIGRATIONS = [
    (1, _migration_001),
    (2, _migration_002),
    (3, _migration_003),
    (4, _migration_004),
    (5, _migration_005),
]


def init_db():
    import logging
    logger = logging.getLogger(__name__)
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
                try:
                    migrate_fn(conn)
                    _set_schema_version(conn, version)
                    logger.info('Migration %d applied successfully', version)
                except Exception:
                    conn.rollback()
                    logger.exception('Migration %d failed — rolled back', version)
                    raise

        # Pour les DB existantes sans schema_version, s'assurer qu'on enregistre la version max
        if current == 0 and MIGRATIONS:
            _set_schema_version(conn, MIGRATIONS[-1][0])

# ─── Calculs ─────────────────────────────────────────────────────────────────

def _holding_effective_value(h):
    """Valorisation effective d'une ligne : qty*last_price si is_priceable et
    last_price connu, sinon market_value saisi. Pour les fonds euros
    (is_priceable=false) on utilise toujours market_value."""
    is_priceable = h.get('is_priceable')
    if is_priceable is None:
        is_priceable = True
    last_price = h.get('last_price')
    quantity   = h.get('quantity') or 0
    if is_priceable and last_price is not None:
        return quantity * last_price
    return h.get('market_value') or 0


def compute_position(pos, entity_map=None, ref=None, holdings_map=None):
    """Calcule les agrégats d'une position.

    Priorité de la valorisation :
    1. Entité liée → valeur de l'entité (inchangé).
    2. Holdings présents (pas d'entité) → somme des valorisations effectives.
    3. Sinon → champ `value` stocké (comportement historique).
    """
    if ref is None:
        ref = DEFAULT_REFERENTIAL
    ownership_pct = pos.get('ownership_pct') if pos.get('ownership_pct') is not None else 1.0
    debt_pct      = pos.get('debt_pct')      if pos.get('debt_pct')      is not None else 1.0
    category      = pos.get('category', '')
    envelope      = pos.get('envelope', '') or ''
    entity        = pos.get('entity')

    holdings = None
    if holdings_map is not None and pos.get('id') is not None:
        holdings = holdings_map.get(pos['id'])

    if entity and entity_map and entity in entity_map:
        value = entity_map[entity]['gross_assets'] or 0
        debt  = entity_map[entity]['debt'] or 0
    elif holdings:
        value = sum(_holding_effective_value(h) for h in holdings)
        debt  = pos.get('debt') or 0
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

    result = {
        **pos,
        'value':             value,
        'net_value':         value - debt,
        'gross_attributed':  gross_attributed,
        'debt_attributed':   debt_attributed,
        'net_attributed':    net_attributed,
        'liquidity':         env['liquidity'],
        'friction':          env['friction'],
        'mobilizable_pct':   mobilizable_pct,
        'mobilizable_value': mobilizable_val,
    }
    if holdings is not None:
        result['has_holdings']    = True
        result['holdings_count']  = len(holdings)
    return result


def snapshot_holdings_to_date(conn, snapshot_date):
    """Capture l'état courant des holdings dans holdings_snapshots.

    Inséré lors d'un événement de snapshot (auto_snapshot, snapshot_update,
    duplicateSnapshot côté front). Idempotent pour une date donnée : on supprime
    d'abord les lignes existantes à cette date pour éviter les doublons en cas
    de re-snapshot.
    """
    try:
        conn.execute('DELETE FROM holdings_snapshots WHERE snapshot_date=?', (snapshot_date,))
        rows = conn.execute('''
            SELECT h.position_id, h.isin, h.quantity, h.cost_basis, h.market_value,
                   s.is_priceable, s.last_price
            FROM holdings h
            LEFT JOIN securities s ON s.isin = h.isin
        ''').fetchall()
        for r in rows:
            is_priceable = r['is_priceable'] if r['is_priceable'] is not None else 1
            price = r['last_price'] if is_priceable else None
            conn.execute(
                '''INSERT INTO holdings_snapshots
                   (snapshot_date, position_id, isin, quantity, cost_basis, price, market_value)
                   VALUES (?,?,?,?,?,?,?)''',
                (snapshot_date, r['position_id'], r['isin'],
                 r['quantity'], r['cost_basis'], price, r['market_value'])
            )
        return len(rows)
    except sqlite3.OperationalError:
        # Tables non encore migrées
        return 0


def get_holdings_map(conn, position_ids=None):
    """Retourne un dict {position_id: [holdings]} joint avec securities.

    Si position_ids est fourni, limite la requête à ces positions (plus rapide
    pour les grosses bases). Sinon retourne toutes les holdings.
    """
    try:
        base_query = '''
            SELECT h.id, h.position_id, h.isin, h.quantity, h.cost_basis,
                   h.market_value, h.as_of_date,
                   s.name, s.ticker, s.currency, s.asset_class,
                   s.is_priceable, s.last_price, s.last_price_date
            FROM holdings h
            LEFT JOIN securities s ON s.isin = h.isin
        '''
        if position_ids:
            placeholders = ','.join('?' * len(position_ids))
            rows = conn.execute(
                base_query + f' WHERE h.position_id IN ({placeholders})',
                list(position_ids)
            ).fetchall()
        else:
            rows = conn.execute(base_query).fetchall()
    except sqlite3.OperationalError:
        # Table holdings absente (migration 005 pas appliquée)
        return {}

    result = {}
    for r in rows:
        d = dict(r)
        if d.get('is_priceable') is not None:
            d['is_priceable'] = bool(d['is_priceable'])
        result.setdefault(d['position_id'], []).append(d)
    return result


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
