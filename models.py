import sqlite3
import json
import os
import re
import math
from datetime import datetime
from contextlib import contextmanager

_BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.environ.get('DB_PATH') or os.path.join(_BASE_DIR, 'patrimoine.db')
DEMO_DB_PATH = os.path.join(_BASE_DIR, 'demo.db')
HOLDING_PRICE_DIVERGENCE_THRESHOLD = 0.15

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
    n = parse_number(v)
    if n is None:
        return False
    if not allow_negative and n < 0:
        return False
    return True


def parse_number(v, default=None):
    """Parse un nombre saisi au format FR/US, avec espaces de milliers."""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        n = float(v)
        return n if math.isfinite(n) else default
    if not isinstance(v, str):
        return default
    s = v.strip()
    if not s:
        return default
    s = s.replace('\u2212', '-')
    s = re.sub(r'[\s\u00a0\u202f_\'’]', '', s)
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    else:
        s = s.replace(',', '.')
    try:
        n = float(s)
        return n if math.isfinite(n) else default
    except (ValueError, TypeError):
        return default

def validate_string(s, max_length=500):
    """Vérifie que s est une chaîne non vide et raisonnable."""
    if s is None:
        return True
    return isinstance(s, str) and len(s) <= max_length

def validate_pct(v):
    """Vérifie que v est un pourcentage entre 0 et 1."""
    if v is None:
        return True
    n = parse_number(v)
    if n is None:
        return False
    return 0 <= n <= 1.0001  # petite marge pour les arrondis


# Pseudo-ISIN pour les fonds euros, actifs non cotés et cryptos :
# format 'FONDS_EUROS_<slug>' / 'CUSTOM_<slug>' / 'CRYPTO_<SYM>', longueur libre,
# bypass du checksum. CRYPTO_* est traité à part (coté via Yahoo <SYM>-EUR).
_PSEUDO_ISIN_PREFIXES = ('FONDS_EUROS_', 'CUSTOM_', 'CRYPTO_')
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

    Restreint a ASCII (les `é`, `中`, emoji sont rejetes — `isalnum()` seul les accepterait).
    """
    if not isin or not isinstance(isin, str):
        return False
    isin = isin.strip().upper()
    if any(isin.startswith(p) for p in _PSEUDO_ISIN_PREFIXES):
        return len(isin) <= 64 and all(
            c.isascii() and (c.isalnum() or c == '_') for c in isin
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
    'Crypto', 'Objets de valeur', 'Société', 'Autre'
]

_MOBILIZABLE_FULL = {
    'Cash & dépôts': 1.0, 'Monétaire': 0.95, 'Obligations': 0.95,
    'Actions': 0.9, 'Immobilier': 0.0, 'SCPI': 0.0, 'Fond Euro': 0.95,
    'Produits Structurés': 0.0, 'Crypto': 0.9, 'Objets de valeur': 0.0,
    'Société': 0.0, 'Autre': 0.8,
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
ENVELOPE_META = DEFAULT_REFERENTIAL['envelope_meta']
CATEGORY_MOBILIZABLE = DEFAULT_REFERENTIAL['category_mobilizable']

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
    import logging
    _m002_logger = logging.getLogger(__name__)
    for col, definition, table in [
        ('mobilizable_pct_override', 'REAL DEFAULT NULL', 'positions'),
        ('category', 'TEXT', 'flux'),
    ]:
        try:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')
        except Exception as e:
            # Colonne deja existante (re-run idempotent) : OK, mais on trace
            # en debug pour distinguer d'une vraie erreur SQL.
            _m002_logger.debug('migration_002: %s.%s already exists (%s)', table, col, e)


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


def _migration_006(conn):
    """Feature conseil patrimonial : profil, objectifs, allocation cible, macro, propositions.

    Toutes les tables utilisees par l'advisor (phases 6 et 7). La phase 6
    exploite owner_profiles + owner_objectives + allocation_targets ; la phase 7
    ajoute macro_snapshots + rebalance_proposals + llm_usage.
    """
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS owner_profiles (
            owner                TEXT PRIMARY KEY,
            horizon_years        INTEGER,
            risk_tolerance       INTEGER,          -- 1 (prudent) a 5 (dynamique)
            employment_type      TEXT,             -- salarie | TNS | fonction_publique | retraite | autre
            has_lbo              INTEGER DEFAULT 0,
            children_count       INTEGER DEFAULT 0,
            main_residence_owned INTEGER DEFAULT 0,
            pension_age          INTEGER,
            notes                TEXT,
            updated_at           TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS owner_objectives (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            owner          TEXT NOT NULL,
            label          TEXT NOT NULL,
            target_amount  REAL,
            horizon_years  INTEGER,
            priority       INTEGER DEFAULT 3,      -- 1 (faible) a 5 (critique)
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_objectives_owner ON owner_objectives(owner);

        CREATE TABLE IF NOT EXISTS macro_snapshots (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            date           TEXT NOT NULL,
            regime_rates   TEXT,                   -- bas | neutre | haut
            inflation_view TEXT,                   -- maitrisee | persistante
            equities_bias  TEXT,                   -- defensif | neutre | offensif
            raw_summary    TEXT,
            source         TEXT,                   -- llm | manual
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS allocation_targets (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            owner          TEXT NOT NULL,
            snapshot_date  TEXT NOT NULL,
            bucket_type    TEXT NOT NULL,          -- liquidity | category
            bucket_name    TEXT NOT NULL,
            target_pct     REAL NOT NULL,
            UNIQUE (owner, snapshot_date, bucket_type, bucket_name)
        );

        CREATE TABLE IF NOT EXISTS rebalance_proposals (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            owner          TEXT NOT NULL,
            snapshot_date  TEXT NOT NULL,
            kind           TEXT NOT NULL,          -- bucket | security | fiscal
            label          TEXT NOT NULL,
            from_ref       TEXT,                   -- ex: 'Actions' ou 'FR0010315770'
            to_ref         TEXT,
            amount         REAL,
            rationale      TEXT,
            status         TEXT DEFAULT 'pending', -- pending | applied | dismissed
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_proposals_owner_status ON rebalance_proposals(owner, status);

        CREATE TABLE IF NOT EXISTS llm_usage (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            date                 TEXT NOT NULL,
            endpoint             TEXT,
            model                TEXT,
            input_tokens         INTEGER DEFAULT 0,
            cached_input_tokens  INTEGER DEFAULT 0,
            output_tokens        INTEGER DEFAULT 0,
            cost_usd             REAL DEFAULT 0,
            latency_ms           INTEGER DEFAULT 0,
            created_at           TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_llm_usage_date ON llm_usage(date);
    ''')


# Registre des migrations — ajouter les futures migrations ici
def _migration_007(conn):
    """Ajout colonnes liquidity_override et label sur positions."""
    for col, defn in [
        ('liquidity_override', 'TEXT DEFAULT NULL'),
        ('label', 'TEXT DEFAULT NULL'),
    ]:
        try:
            conn.execute(f'ALTER TABLE positions ADD COLUMN {col} {defn}')
        except Exception:
            pass


def _migration_008(conn):
    """Ajout colonne label sur positions (si absente)."""
    try:
        conn.execute('ALTER TABLE positions ADD COLUMN label TEXT DEFAULT NULL')
    except Exception:
        pass


def _migration_009(conn):
    """Registre des transactions : le mouvement de titres, piece par piece.

    Ce que `holdings` ne peut pas porter. Une holding decrit un ETAT (quantite
    et cout a une date) ; elle ne garde aucune trace d'une vente. Quand une
    ligne est soldee, elle disparait et sa plus-value avec. Les plus-values
    REALISEES sont donc structurellement hors d'atteinte sans registre.

    Deliberement SANS cle etrangere vers `positions` : une transaction n'est pas
    rattachee a un arrete. Elle survit a la suppression d'un snapshot, ce qui
    evite au passage la question des cascades inertes (`PRAGMA foreign_keys`
    n'est pas positionne dans `get_db`, cf. dette documentee). La seule
    reference est `isin`, souple, vers `securities`.

    `source_doc` porte le chemin de la piece justificative et sert de cle
    naturelle : l'import est ainsi idempotent sans dedoublonnage applicatif.
    Une saisie manuelle sans piece reste possible (plusieurs NULL autorises par
    SQLite sur un index unique).
    """
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS transactions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          TEXT    NOT NULL,              -- date d'execution
            owner         TEXT    NOT NULL,
            envelope      TEXT,
            establishment TEXT,
            isin          TEXT    NOT NULL REFERENCES securities(isin),
            side          TEXT    NOT NULL CHECK (side IN ('ACHAT','VENTE')),
            quantity      REAL    NOT NULL CHECK (quantity > 0),
            price         REAL,                          -- cours en devise de negociation
            currency      TEXT    DEFAULT 'EUR',
            fx_rate       REAL,                          -- cours de change si devise <> EUR
            gross         REAL,                          -- montant brut en devise
            fees          REAL    DEFAULT 0,             -- courtage + taxes, en EUR
            net_eur       REAL    NOT NULL,              -- montant reellement regle
            place         TEXT,
            source_doc    TEXT,                          -- piece justificative
            notes         TEXT,
            created_at    TEXT    DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_tx_date  ON transactions(date);
        CREATE INDEX IF NOT EXISTS idx_tx_isin  ON transactions(isin);
        CREATE INDEX IF NOT EXISTS idx_tx_owner ON transactions(owner, envelope);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_source ON transactions(source_doc);
    ''')


def _migration_010(conn):
    """Ajout de `flux.establishment`.

    Sans cette colonne, un flux ne peut etre rattache qu'a (personne, enveloppe)
    — insuffisant des qu'une enveloppe existe chez plusieurs etablissements. Une
    assurance-vie repartie sur quatre contrats obligeait a repartir les
    versements au prorata de la valeur, ce qui biaise le rendement de chaque
    contrat.

    Backfill sans risque : on ne renseigne l'etablissement que lorsque le couple
    (personne, enveloppe) n'en connait QU'UN SEUL dans `positions`. Toute
    ambiguite est laissee a NULL plutot que devinee.
    """
    try:
        conn.execute('ALTER TABLE flux ADD COLUMN establishment TEXT DEFAULT NULL')
    except Exception:
        pass
    try:
        conn.execute('''
            UPDATE flux SET establishment = (
                SELECT MIN(p.establishment) FROM positions p
                WHERE p.owner = flux.owner
                  AND IFNULL(p.envelope, '') = IFNULL(flux.envelope, '')
                  AND p.establishment IS NOT NULL AND p.establishment <> ''
                HAVING COUNT(DISTINCT p.establishment) = 1
            )
            WHERE establishment IS NULL
        ''')
    except Exception:
        pass
    try:
        conn.execute('CREATE INDEX IF NOT EXISTS idx_flux_account '
                     'ON flux(owner, envelope, establishment)')
    except Exception:
        pass


def _migration_011(conn):
    """Table des cours de change.

    Aucune conversion n'existait dans le modele : un titre cote hors euro etait
    valorise en additionnant sa devise a des euros, surevaluant la position du
    taux de change. Les cours sont dates, comme ceux des titres, pour qu'un
    arrete historique puisse etre valorise au taux de sa date.
    """
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fx_rates (
                pair TEXT NOT NULL,          -- 'EURUSD' : combien de USD pour 1 EUR
                date TEXT NOT NULL,
                rate REAL NOT NULL,
                PRIMARY KEY (pair, date)
            )
        """)
    except Exception:
        pass


def _migration_012(conn):
    """Reserve a garder disponible, par titulaire.

    Le conseiller proposait d'alleger « 130 000 € de liquidites » vers les
    actions sans savoir que ces liquidites servaient a nantir un credit : il
    n'avait aucun moyen de le savoir. Le montant se declare dans le profil, et
    les propositions ne l'entament plus.
    """
    try:
        conn.execute('ALTER TABLE owner_profiles ADD COLUMN reserve_eur REAL')
    except Exception:
        pass            # colonne deja presente


def _migration_013(conn):
    """Prets et leurs echeanciers.

    Un tableau d'amortissement donne le capital restant du a chaque echeance :
    de quoi prevoir la dette a toute date, pre-remplir la mise a jour des
    soldes, et signaler une dette saisie qui s'en ecarte. Un pret se rattache
    a une entite (SCI, residence) ou reste libre.
    """
    conn.execute('''
        CREATE TABLE IF NOT EXISTS prets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            libelle     TEXT NOT NULL,
            preteur     TEXT,
            emprunteur  TEXT,
            entity      TEXT,               -- entite dont il porte la dette
            montant     REAL,
            taux        REAL,
            debut       TEXT,
            fin         TEXT,
            source      TEXT,               -- nom du document importe
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS pret_echeances (
            pret_id    INTEGER NOT NULL,
            rang       INTEGER NOT NULL,
            date       TEXT NOT NULL,
            capital    REAL NOT NULL,       -- baisse du restant du a cette echeance
            interets   REAL NOT NULL DEFAULT 0,
            assurance  REAL NOT NULL DEFAULT 0,
            crd        REAL NOT NULL,       -- capital restant du APRES l'echeance
            PRIMARY KEY (pret_id, rang)
        )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_pret_echeances_date ON pret_echeances(pret_id, date)')


def _migration_014(conn):
    """Indemnites de remboursement anticipe d'un pret : 'legale' (plafond du
    Code de la consommation) ou 'aucune' (contrat qui y renonce)."""
    try:
        conn.execute("ALTER TABLE prets ADD COLUMN ira TEXT DEFAULT 'legale'")
    except Exception:
        pass            # colonne deja presente



def _migration_015(conn):
    """Operations bancaires d'une entite (SCI, holding), lues sur ses releves.
    Elles mesurent ce que l'entite recoit, rembourse et coute — et ce que
    ses associes y remettent. Unicite sur l'operation elle-meme : reimporter
    un releve n'ajoute rien."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entite_operations (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            entity    TEXT NOT NULL,
            date      TEXT NOT NULL,
            libelle   TEXT NOT NULL,
            montant   REAL NOT NULL,          -- signe : + entree, - sortie
            nature    TEXT NOT NULL,          -- revenu, revenu_exceptionnel, echeance, apport, frais, interne, autre
            banque    TEXT,
            compte    TEXT,
            source    TEXT,                   -- nom du releve importe
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity, banque, compte, date, montant, libelle)
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entite_op ON entite_operations(entity, date)")



def _migration_016(conn):
    """Part de tresorerie comprise dans la valeur d'un arrete d'entite. Sans
    elle, ajouter la tresorerie a la valeur precedente la recompterait a
    chaque arrete."""
    try:
        conn.execute("ALTER TABLE entity_snapshots ADD COLUMN tresorerie REAL")
    except Exception:
        pass            # colonne deja presente



def _migration_017(conn):
    """Parts detenues par une entite (SCPI d'une SCI) : leur nombre, le prix
    paye, et les prix publies de souscription et de retrait. La valeur de
    l'entite se lit alors au prix de retrait — ce qu'on toucherait en sortant —
    et non au prix d'achat, qui comprend des frais d'entree deja partis."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entite_parts (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            entity            TEXT NOT NULL,
            nom               TEXT NOT NULL,
            parts             REAL NOT NULL,
            montant_souscrit  REAL,              -- prix paye, frais compris
            prix_souscription REAL,              -- prix de part publie
            prix_retrait      REAL,              -- publie ; a defaut, souscription moins les frais
            date_prix         TEXT,
            source            TEXT,
            UNIQUE(entity, nom)
        )""")



def _migration_018(conn):
    """Exercices clos d'une entite a l'IS, d'apres ses comptes : le resultat
    fiscal de chacun. Les deficits se reportent sur les benefices suivants ;
    l'estimation de l'exercice en cours part de la."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entite_exercices (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            entity    TEXT NOT NULL,
            debut     TEXT,
            fin       TEXT NOT NULL,
            resultat  REAL NOT NULL,          -- resultat fiscal : negatif = deficit
            source    TEXT,
            UNIQUE(entity, fin)
        )""")



def _migration_019(conn):
    """Date d'effet d'un contrat (assurance-vie, PEA...) : c'est elle, et non
    le premier arrete ou il apparait, qui fixe l'anciennete fiscale — 8 ans
    pour l'abattement d'une assurance-vie, 5 ans pour un PEA. Un contrat se
    designe comme ses positions : titulaire, enveloppe, etablissement."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contrats (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            owner         TEXT NOT NULL,
            envelope      TEXT NOT NULL,
            establishment TEXT NOT NULL DEFAULT '',
            date_effet    TEXT,
            numero        TEXT,
            source        TEXT,
            UNIQUE(owner, envelope, establishment)
        )""")


def _migration_020(conn):
    """Solde d'ouverture du premier releve importe de chaque compte d'une
    entite. La tresorerie se reconstituait des seules operations, comme si
    chaque compte avait ete ouvert a zero le jour de son premier releve."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entite_soldes_initiaux (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            entity    TEXT NOT NULL,
            banque    TEXT NOT NULL DEFAULT '',
            compte    TEXT NOT NULL DEFAULT '',
            date      TEXT NOT NULL,          -- debut du premier releve
            solde     REAL NOT NULL,          -- solde a l'ouverture de ce releve
            source    TEXT,
            UNIQUE(entity, banque, compte)
        )""")


def _reconstruire_en_centimes(conn, table, creation, colonnes):
    """Reconstruit `table` en table STRICT, ses montants `colonnes` en centimes
    entiers (services/montants.py).

    SQLite ne change pas le type d'une colonne : nouvelle table, copie
    convertie, verification ligne a ligne, puis DROP de l'ancienne et
    renommage. Seule operation destructive admise sur le schema, et sous
    controle : tout se fait dans un point de sauvegarde, et le moindre ecart
    (nombre de lignes, colonne non montant alteree, montant deplace de plus
    d'un demi-centime) annule l'ensemble avant le DROP. Idempotente : une table
    deja STRICT est laissee telle quelle.

    `creation` : l'ordre CREATE TABLE de la nouvelle table, nomme `{t}`.
    """
    from services.montants import centimes
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                       (table,)).fetchone()
    if sql is None:
        raise RuntimeError(f'{table} : table absente')
    if re.search(r'\)\s*STRICT\s*$', sql[0], re.I):
        return
    if conn.execute('PRAGMA foreign_keys').fetchone()[0]:
        raise RuntimeError('cles etrangeres actives : reconstruction refusee')
    for (vsql,) in conn.execute("SELECT sql FROM sqlite_master WHERE type='view'"):
        if re.search(r'\b%s\b' % table, vsql or ''):
            raise RuntimeError(f'{table} : une vue en depend, reconstruction refusee')

    neuve = f'{table}__centimes'
    anciennes = [r[1] for r in conn.execute(f'PRAGMA table_info({table})')]
    annexes = [r[0] for r in conn.execute(
        "SELECT sql FROM sqlite_master WHERE type IN ('index','trigger') AND tbl_name=? AND sql IS NOT NULL",
        (table,))]
    seq = conn.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (table,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone() else None

    conn.execute('SAVEPOINT reconstruction')
    try:
        conn.execute(creation.format(t=neuve))
        nouvelles = [r[1] for r in conn.execute(f'PRAGMA table_info({neuve})')]
        if sorted(nouvelles) != sorted(anciennes):
            raise RuntimeError(f'{table} : colonnes differentes ({sorted(anciennes)} / {sorted(nouvelles)})')
        liste = ', '.join(anciennes)
        lignes = conn.execute(f'SELECT rowid AS _r, {liste} FROM {table}').fetchall()
        idx = {c: i + 1 for i, c in enumerate(anciennes)}
        conn.executemany(
            f'INSERT INTO {neuve} (rowid, {liste}) VALUES ({", ".join("?" * (len(anciennes) + 1))})',
            [(l[0], *[centimes(l[idx[c]]) if c in colonnes else l[idx[c]] for c in anciennes])
             for l in lignes])

        # Verification, avant tout DROP.
        n = conn.execute(f'SELECT COUNT(*) FROM {neuve}').fetchone()[0]
        if n != len(lignes):
            raise RuntimeError(f'{table} : {len(lignes)} lignes, {n} copiees')
        for c in anciennes:
            if c in colonnes:
                cond = (f'(a.{c} IS NULL) != (b.{c} IS NULL) OR typeof(b.{c}) NOT IN (\'integer\', \'null\') '
                        f'OR ABS(b.{c} / 100.0 - a.{c}) > 0.0050001')
            else:
                cond = f'a.{c} IS NOT b.{c}'
            ecart = conn.execute(f'SELECT COUNT(*) FROM {table} a JOIN {neuve} b ON b.rowid = a.rowid '
                                 f'WHERE {cond}').fetchone()[0]
            if ecart:
                raise RuntimeError(f'{table}.{c} : {ecart} ligne(s) en ecart')

        conn.execute(f'DROP TABLE {table}')
        conn.execute(f'ALTER TABLE {neuve} RENAME TO {table}')
        for a in annexes:
            conn.execute(a)
        if seq:
            conn.execute('UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name=?', (seq[0], table))
        conn.execute('RELEASE reconstruction')
    except Exception:
        conn.execute('ROLLBACK TO reconstruction')
        conn.execute('RELEASE reconstruction')
        raise


def _migration_021(conn):
    """Tresorerie des entites en centimes entiers (tables STRICT) : operations
    des releves, soldes d'ouverture, parts, exercices. L'unicite d'une
    operation portait sur un montant flottant — 1234.5 et 1234.4999999
    passaient pour deux operations."""
    _reconstruire_en_centimes(conn, 'entite_operations', """
        CREATE TABLE {t} (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            entity    TEXT NOT NULL,
            date      TEXT NOT NULL,
            libelle   TEXT NOT NULL,
            montant   INTEGER NOT NULL,       -- centimes, signe : + entree, - sortie
            nature    TEXT NOT NULL,
            banque    TEXT,
            compte    TEXT,
            source    TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity, banque, compte, date, montant, libelle)
        ) STRICT""", ('montant',))
    _reconstruire_en_centimes(conn, 'entite_soldes_initiaux', """
        CREATE TABLE {t} (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            entity    TEXT NOT NULL,
            banque    TEXT NOT NULL DEFAULT '',
            compte    TEXT NOT NULL DEFAULT '',
            date      TEXT NOT NULL,
            solde     INTEGER NOT NULL,       -- centimes
            source    TEXT,
            UNIQUE(entity, banque, compte)
        ) STRICT""", ('solde',))
    _reconstruire_en_centimes(conn, 'entite_parts', """
        CREATE TABLE {t} (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            entity            TEXT NOT NULL,
            nom               TEXT NOT NULL,
            parts             REAL NOT NULL,
            montant_souscrit  INTEGER,           -- centimes, frais compris
            prix_souscription REAL,              -- prix d'une part (euros)
            prix_retrait      REAL,
            date_prix         TEXT,
            source            TEXT,
            UNIQUE(entity, nom)
        ) STRICT""", ('montant_souscrit',))
    _reconstruire_en_centimes(conn, 'entite_exercices', """
        CREATE TABLE {t} (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            entity    TEXT NOT NULL,
            debut     TEXT,
            fin       TEXT NOT NULL,
            resultat  INTEGER NOT NULL,       -- centimes ; negatif = deficit
            source    TEXT,
            UNIQUE(entity, fin)
        ) STRICT""", ('resultat',))


def _migration_022(conn):
    """Credits en centimes entiers (tables STRICT) : montant emprunte, et
    chaque echeance (capital, interets, assurance, restant du). Un pret se
    reconnaissait a un montant flottant ; son echeancier cumulait des
    arrondis que la verification du tableau tolerait."""
    _reconstruire_en_centimes(conn, 'prets', """
        CREATE TABLE {t} (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            libelle     TEXT NOT NULL,
            preteur     TEXT,
            emprunteur  TEXT,
            entity      TEXT,               -- entite dont il porte la dette
            montant     INTEGER,            -- centimes
            taux        REAL,
            debut       TEXT,
            fin         TEXT,
            source      TEXT,               -- nom du document importe
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            ira         TEXT DEFAULT 'legale'
        ) STRICT""", ('montant',))
    _reconstruire_en_centimes(conn, 'pret_echeances', """
        CREATE TABLE {t} (
            pret_id    INTEGER NOT NULL,
            rang       INTEGER NOT NULL,
            date       TEXT NOT NULL,
            capital    INTEGER NOT NULL,    -- centimes : baisse du restant du
            interets   INTEGER NOT NULL DEFAULT 0,
            assurance  INTEGER NOT NULL DEFAULT 0,
            crd        INTEGER NOT NULL,    -- centimes : restant du APRES l'echeance
            PRIMARY KEY (pret_id, rang)
        ) STRICT""", ('capital', 'interets', 'assurance', 'crd'))


def _migration_023(conn):
    """Flux et operations sur titres en centimes entiers (tables STRICT). Le
    rapprochement d'un flux et d'un document portait sur un montant
    flottant ; le cours unitaire et la quantite restent en REAL."""
    _reconstruire_en_centimes(conn, 'flux', """
        CREATE TABLE {t} (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          TEXT    NOT NULL,
            owner         TEXT    NOT NULL,
            envelope      TEXT,
            type          TEXT,
            amount        INTEGER NOT NULL,     -- centimes
            notes         TEXT,
            created_at    TEXT    DEFAULT CURRENT_TIMESTAMP,
            category      TEXT,
            establishment TEXT    DEFAULT NULL
        ) STRICT""", ('amount',))
    _reconstruire_en_centimes(conn, 'transactions', """
        CREATE TABLE {t} (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          TEXT    NOT NULL,              -- date d'execution
            owner         TEXT    NOT NULL,
            envelope      TEXT,
            establishment TEXT,
            isin          TEXT    NOT NULL REFERENCES securities(isin),
            side          TEXT    NOT NULL CHECK (side IN ('ACHAT','VENTE')),
            quantity      REAL    NOT NULL CHECK (quantity > 0),
            price         REAL,                          -- cours en devise de negociation
            currency      TEXT    DEFAULT 'EUR',
            fx_rate       REAL,
            gross         INTEGER,                       -- centimes, en devise
            fees          INTEGER DEFAULT 0,             -- centimes, en EUR
            net_eur       INTEGER NOT NULL,              -- centimes, montant regle
            place         TEXT,
            source_doc    TEXT,
            notes         TEXT,
            created_at    TEXT    DEFAULT CURRENT_TIMESTAMP
        ) STRICT""", ('gross', 'fees', 'net_eur'))


def _migration_024(conn):
    """Positions, entites et valorisations datees des entites en centimes
    entiers (tables STRICT). Quotes-parts et surcharge de mobilisable restent
    en REAL : ce sont des proportions."""
    _reconstruire_en_centimes(conn, 'positions', """
        CREATE TABLE {t} (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT    NOT NULL,
            owner           TEXT    NOT NULL,
            category        TEXT    NOT NULL,
            envelope        TEXT,
            establishment   TEXT,
            value           INTEGER DEFAULT 0,       -- centimes
            debt            INTEGER DEFAULT 0,       -- centimes
            notes           TEXT,
            entity          TEXT,
            ownership_pct   REAL    DEFAULT 1.0,
            debt_pct        REAL    DEFAULT 1.0,
            created_at      TEXT    DEFAULT CURRENT_TIMESTAMP,
            mobilizable_pct_override REAL DEFAULT NULL,
            liquidity_override TEXT DEFAULT NULL,
            label           TEXT    DEFAULT NULL
        ) STRICT""", ('value', 'debt'))
    _reconstruire_en_centimes(conn, 'entities', """
        CREATE TABLE {t} (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT    NOT NULL UNIQUE,
            type             TEXT,
            valuation_mode   TEXT,
            gross_assets     INTEGER DEFAULT 0,      -- centimes
            debt             INTEGER DEFAULT 0,      -- centimes
            comment          TEXT,
            created_at       TEXT    DEFAULT CURRENT_TIMESTAMP
        ) STRICT""", ('gross_assets', 'debt'))
    _reconstruire_en_centimes(conn, 'entity_snapshots', """
        CREATE TABLE {t} (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_name  TEXT NOT NULL,
            date         TEXT NOT NULL,
            gross_assets INTEGER DEFAULT 0,          -- centimes
            debt         INTEGER DEFAULT 0,          -- centimes
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            tresorerie   INTEGER,                    -- centimes compris dans la valeur
            UNIQUE(entity_name, date)
        ) STRICT""", ('gross_assets', 'debt', 'tresorerie'))


def _migration_025(conn):
    """Lignes de titres et leurs photos datees en centimes entiers (tables
    STRICT) : prix de revient et valorisation. Quantite et cours unitaire
    restent en REAL."""
    _reconstruire_en_centimes(conn, 'holdings', """
        CREATE TABLE {t} (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id  INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
            isin         TEXT NOT NULL REFERENCES securities(isin),
            quantity     REAL NOT NULL,
            cost_basis   INTEGER,                -- centimes
            market_value INTEGER,                -- centimes
            as_of_date   TEXT,
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP
        ) STRICT""", ('cost_basis', 'market_value'))
    _reconstruire_en_centimes(conn, 'holdings_snapshots', """
        CREATE TABLE {t} (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date  TEXT NOT NULL,
            position_id    INTEGER NOT NULL,
            isin           TEXT NOT NULL,
            quantity       REAL,
            cost_basis     INTEGER,              -- centimes
            price          REAL,                 -- cours unitaire
            market_value   INTEGER,              -- centimes
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP
        ) STRICT""", ('cost_basis', 'market_value'))


def _migration_026(conn):
    """Conseil en centimes entiers (tables STRICT) : montant vise d'un
    objectif, reserve de precaution d'un profil, montant d'une proposition
    d'arbitrage. Derniere etape : tous les montants en euros sont en centimes."""
    _reconstruire_en_centimes(conn, 'owner_objectives', """
        CREATE TABLE {t} (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            owner          TEXT NOT NULL,
            label          TEXT NOT NULL,
            target_amount  INTEGER,                -- centimes
            horizon_years  INTEGER,
            priority       INTEGER DEFAULT 3,      -- 1 (faible) a 5 (critique)
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP
        ) STRICT""", ('target_amount',))
    _reconstruire_en_centimes(conn, 'owner_profiles', """
        CREATE TABLE {t} (
            owner                TEXT PRIMARY KEY,
            horizon_years        INTEGER,
            risk_tolerance       INTEGER,
            employment_type      TEXT,
            has_lbo              INTEGER DEFAULT 0,
            children_count       INTEGER DEFAULT 0,
            main_residence_owned INTEGER DEFAULT 0,
            pension_age          INTEGER,
            notes                TEXT,
            updated_at           TEXT DEFAULT CURRENT_TIMESTAMP,
            reserve_eur          INTEGER             -- centimes
        ) STRICT""", ('reserve_eur',))
    _reconstruire_en_centimes(conn, 'rebalance_proposals', """
        CREATE TABLE {t} (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            owner          TEXT NOT NULL,
            snapshot_date  TEXT NOT NULL,
            kind           TEXT NOT NULL,
            label          TEXT NOT NULL,
            from_ref       TEXT,
            to_ref         TEXT,
            amount         INTEGER,                -- centimes
            rationale      TEXT,
            status         TEXT DEFAULT 'pending',
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP
        ) STRICT""", ('amount',))


def _migration_027(conn):
    """Epargne de precaution : ses deux reglages dans le profil, les charges
    mensuelles (centimes) et le nombre de mois a couvrir. Leur produit est la
    cible ; elle remplace la reserve libre, qui ne sert plus que tant que la
    cible n'est pas renseignee (reserve_eur reste, rien n'est efface)."""
    for colonne in ('charges_mensuelles INTEGER', 'mois_precaution INTEGER'):
        try:
            conn.execute(f'ALTER TABLE owner_profiles ADD COLUMN {colonne}')
        except sqlite3.OperationalError:
            pass                  # deja ajoutee


def _migration_028(conn):
    """Journal des modifications : qui a ecrit quoi, maintenant que chacun se
    connecte sous son nom (Authelia)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS journal (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            quand       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            utilisateur TEXT,
            methode     TEXT NOT NULL,
            chemin      TEXT NOT NULL,
            statut      INTEGER NOT NULL
        ) STRICT""")
    conn.execute('CREATE INDEX IF NOT EXISTS idx_journal_quand ON journal(quand)')


MIGRATIONS = [
    (1, _migration_001),
    (2, _migration_002),
    (3, _migration_003),
    (4, _migration_004),
    (5, _migration_005),
    (6, _migration_006),
    (7, _migration_007),
    (8, _migration_008),
    (9, _migration_009),
    (10, _migration_010),
    (11, _migration_011),
    (12, _migration_012),
    (13, _migration_013),
    (14, _migration_014),
    (15, _migration_015),
    (16, _migration_016),
    (17, _migration_017),
    (18, _migration_018),
    (19, _migration_019),
    (20, _migration_020),
    (21, _migration_021),
    (22, _migration_022),
    (23, _migration_023),
    (24, _migration_024),
    (25, _migration_025),
    (26, _migration_026),
    (27, _migration_027),
    (28, _migration_028),
]


def init_db():
    """Migre la base principale, et la base de demo si elle existe : restee a
    son schema d'origine, elle aurait ete lue avec des regles qui ne sont plus
    les siennes (montants en centimes, par exemple)."""
    migrer(DB_PATH)
    if os.path.exists(DEMO_DB_PATH) and os.path.abspath(DEMO_DB_PATH) != os.path.abspath(DB_PATH):
        migrer(DEMO_DB_PATH)


def migrer(chemin):
    """Applique a la base `chemin` les migrations qui lui manquent."""
    import logging
    logger = logging.getLogger(__name__)
    conn = sqlite3.connect(chemin)
    conn.row_factory = sqlite3.Row
    try:
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
        conn.commit()
    finally:
        conn.close()

# ─── Calculs ─────────────────────────────────────────────────────────────────

def _parse_holding_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except (TypeError, ValueError):
        return None


def _holding_decision(h):
    """(valorisation, alerte) — l'arbitrage et sa justification au meme endroit.

    Le modele choisit entre `quantity x last_price` et le `market_value`
    enregistre. Ce choix doit etre RESTITUABLE : une alerte calculee a part
    finit par affirmer autre chose que ce que la valorisation a fait. Les deux
    sortent donc de la meme fonction.

    L'arbitrage muet a masque pendant des mois deux titres du Nasdaq dont le
    cours arrivait en dollars et dont la devise etait restee au defaut EUR du
    schema : l'ecart valait exactement le taux de change, et la valorisation
    n'etait juste que parce que ce taux depassait le seuil de divergence. A 1,14
    au lieu de 1,1545, le dollar serait passe pour de l'euro.
    """
    def alerte(kind, reason, gap=None):
        return {'isin': h.get('isin'), 'name': h.get('name'), 'kind': kind,
                'currency': (h.get('currency') or 'EUR').upper(),
                'gap': round(gap, 4) if gap is not None else None,
                'reason': reason}

    is_priceable = h.get('is_priceable')
    if is_priceable is None:
        is_priceable = True
    price = h.get('last_price')
    q = h.get('quantity') or 0
    manual = h.get('market_value')
    if not is_priceable:
        return manual or 0, None

    # Un cours hors euro se convertit. A defaut de taux, il ne valorise rien :
    # additionner des dollars a des euros surevaluerait la ligne du change.
    devise = (h.get('currency') or 'EUR').upper()
    if devise != 'EUR':
        taux = h.get('fx_rate')
        if not taux or taux <= 0:
            if manual is not None:
                return manual, alerte(
                    'devise', f'cours en {devise} et taux de change inconnu : '
                              'valeur enregistrée retenue')
            return 0, alerte('devise', f'cours en {devise}, taux inconnu')
        # `pair` vaut EURxxx : le taux dit combien de xxx pour un euro.
        price = price / taux if price is not None else None

    manual_date = _parse_holding_date(h.get('as_of_date') or h.get('position_date'))
    price_date = _parse_holding_date(h.get('last_price_date'))
    unite = (manual / q) if (manual is not None and q) else None
    gap = (abs(price - unite) / unite) if (unite and unite > 0 and price is not None) else None

    if manual is not None and manual_date and (not price_date or manual_date > price_date):
        return manual, None          # saisie plus recente que le cours : normal

    if (manual is not None and price is not None and q
            and h.get('data_source') != 'mock'
            and manual_date and price_date and manual_date >= price_date
            and gap is not None and gap > HOLDING_PRICE_DIVERGENCE_THRESHOLD):
        return manual, alerte(
            'divergence',
            f'cours {price:.2f} contre {unite:.2f} enregistré '
            f'({gap * 100:.1f} % d\'écart) : valeur enregistrée retenue', gap)

    if price is not None:
        # Le cours l'emporte. Un ecart important reste digne d'etre signale :
        # il dit que la valeur enregistree a vieilli, pas que le cours est faux.
        if gap is not None and gap > HOLDING_PRICE_DIVERGENCE_THRESHOLD:
            quand = f" du {h.get('as_of_date')}" if h.get('as_of_date') else ''
            return q * price, alerte(
                'cours_retenu',
                f'cours du jour retenu ({price:.2f}) : la valeur enregistrée'
                f'{quand} en diffère de {gap * 100:.1f} %', gap)
        return q * price, None

    return manual or 0, None


def holding_price_warning(h):
    """Alerte de valorisation d'une ligne, ou None. Voir _holding_decision."""
    return _holding_decision(h)[1]


def _holding_effective_value(h):
    """Valorisation effective d'une ligne. Voir _holding_decision."""
    return _holding_decision(h)[0]


def _holding_value_or_none(h):
    """Valorisation d'une ligne, ou None quand RIEN ne la fonde : ni valeur
    enregistree, ni cours utilisable (titre non cote, cours absent, devise sans
    taux). `_holding_effective_value` rend alors 0, ce qui convient a une
    somme d'actifs mais pas a une plus-value : une ligne en dollars sans taux
    comptait son prix de revient en perte."""
    if h.get('market_value') is not None:
        return _holding_effective_value(h)
    if not h.get('is_priceable') or h.get('last_price') is None:
        return None
    devise = (h.get('currency') or 'EUR').upper()
    if devise != 'EUR' and not (h.get('fx_rate') or 0) > 0:
        return None
    return _holding_effective_value(h)


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
    liquidity        = pos.get('liquidity_override') or env['liquidity']
    # Bloque = pas mobilisable, quelle que soit la pct
    if liquidity == 'Bloqué':
        mobilizable_val = 0
    else:
        mobilizable_val = net_attributed * mobilizable_pct if net_attributed > 0 else 0

    result = {
        **pos,
        'value':             value,
        'net_value':         value - debt,
        'gross_attributed':  gross_attributed,
        'debt_attributed':   debt_attributed,
        'net_attributed':    net_attributed,
        'liquidity':         pos.get('liquidity_override') or env['liquidity'],
        'friction':          env['friction'],
        'mobilizable_pct':   mobilizable_pct,
        'mobilizable_value': mobilizable_val,
    }
    if holdings is not None:
        result['has_holdings']    = True
        result['holdings_count']  = len(holdings)
        result.update(_plus_value(holdings, ownership_pct))
    return result


def _plus_value(holdings, ownership_pct):
    """Plus-value latente d'une position a lignes de titres.

    Seules comptent les lignes dont le prix de revient est connu : un
    `cost_basis` egal au centime pres a la valeur de marche n'est pas un prix
    paye, c'est une case remplie par defaut — la moitie des lignes en base. Les
    compter en ferait des lignes a gain nul, et le gain affiche serait faux sans
    le dire. `gain_lignes` rend donc le nombre de lignes reellement mesurees,
    a comparer a `holdings_count`.
    """
    cout = gain = 0.0
    mesurees = 0
    for h in holdings:
        cb, mv = h.get('cost_basis'), h.get('market_value')
        if not cb or (mv is not None and abs(cb - mv) < 0.01):
            continue
        valeur = _holding_value_or_none(h)
        if valeur is None:           # non valorisable : ni gain ni perte connus
            continue
        cout += cb
        gain += valeur - cb
        mesurees += 1
    if not mesurees:
        return {'gain_lignes': 0}
    return {
        'gain_lignes':      mesurees,
        'cost_attributed':  cout * ownership_pct,
        'gain_attributed':  gain * ownership_pct,
        'gain_pct':         gain / cout if cout else None,
    }


def snapshot_holdings_to_date(conn, snapshot_date):
    """Capture l'état courant des holdings dans holdings_snapshots.

    Inséré lors d'un événement de snapshot (auto_snapshot, snapshot_update,
    duplicateSnapshot côté front). Idempotent pour une date donnée : on supprime
    d'abord les lignes existantes à cette date pour éviter les doublons en cas
    de re-snapshot.

    Lock : `BEGIN IMMEDIATE` evite que deux snapshots concurrents creent des
    doublons (delete + insert pas atomiques sinon).
    """
    try:
        # Si une transaction est deja ouverte par l'appelant (ex: snapshot_update),
        # on ne re-ouvre pas — SQLite ne supporte pas les transactions imbriquees.
        in_txn = conn.in_transaction
        if not in_txn:
            conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM holdings_snapshots WHERE snapshot_date=?', (snapshot_date,))
        # Ne capturer QUE les holdings des positions de CETTE date (sinon on
        # ré-empile tout l'historique sous chaque snapshot_date -> sur-capture).
        rows = conn.execute('''
            SELECT h.position_id, h.isin, h.quantity, h.cost_basis, h.market_value,
                   s.is_priceable, s.last_price
            FROM holdings h
            JOIN positions p ON p.id = h.position_id
            LEFT JOIN securities s ON s.isin = h.isin
            WHERE p.date = ?
        ''', (snapshot_date,)).fetchall()
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


def freeze_holdings_prices(holdings_map):
    """Neutralise le cours du jour pour valoriser un arrete historique.

    Sans cela, `_holding_effective_value` prefere `securities.last_price` des
    qu'il est plus recent que la ligne : chaque arrete passe se retrouve
    revalorise aux prix d'aujourd'hui. Correct pour le portefeuille courant,
    faux pour une serie historique. Le dernier arrete, lui, garde le cours du
    jour pour rester aligne sur les KPI live.
    """
    for holdings in holdings_map.values():
        for h in holdings:
            h['last_price'] = None
    return holdings_map


def holdings_a_date(conn, position_ids, date):
    """Lignes de titres valorisables a `date` : cours du jour pour le dernier
    arrete, valeur enregistree pour les autres. Trois routes (positions d'une
    date, frise, historique d'une position) chargeaient les lignes sans figer
    les cours : tout l'historique se revalorisait au cours du jour, et une
    ligne achetee 10 € puis cotee 20 € dessinait une courbe plate a 20 €."""
    hmap = get_holdings_map(conn, position_ids)
    dernier = conn.execute('SELECT MAX(date) AS d FROM positions').fetchone()['d']
    if date and dernier and date != dernier:
        freeze_holdings_prices(hmap)
    return hmap


def get_holdings_map(conn, position_ids=None):
    """Retourne un dict {position_id: [holdings]} joint avec securities.

    Si position_ids est fourni, limite la requête à ces positions (plus rapide
    pour les grosses bases). Sinon (None) retourne toutes les holdings.

    Une liste VIDE ne veut pas dire « tout » : un arrete sans position rendait
    les lignes de toute la base, que l'appelant additionnait ensuite.
    """
    if position_ids is not None:
        position_ids = list(position_ids)
        if not position_ids:
            return {}
    try:
        base_query = '''
            SELECT h.id, h.position_id, h.isin, h.quantity, h.cost_basis,
                   h.market_value, h.as_of_date,
                   p.date AS position_date,
                   s.name, s.ticker, s.currency, s.asset_class,
                   s.is_priceable, s.last_price, s.last_price_date, s.data_source,
                   (SELECT f.rate FROM fx_rates f
                     WHERE f.pair = 'EUR' || s.currency
                     ORDER BY f.date DESC LIMIT 1) AS fx_rate
            FROM holdings h
            JOIN positions p ON p.id = h.position_id
            LEFT JOIN securities s ON s.isin = h.isin
        '''
        if position_ids is not None:
            placeholders = ','.join('?' * len(position_ids))
            rows = conn.execute(
                base_query + f' WHERE h.position_id IN ({placeholders})',
                position_ids
            ).fetchall()
        else:
            rows = conn.execute(base_query).fetchall()
    except sqlite3.OperationalError:
        # Table holdings absente (migration 005 pas appliquée)
        return {}

    from services.montants import ligne_en_euros
    result = {}
    for r in rows:
        d = ligne_en_euros('holdings', r)
        if d.get('is_priceable') is not None:
            d['is_priceable'] = bool(d['is_priceable'])
        result.setdefault(d['position_id'], []).append(d)
    return result


def sync_position_value(conn, position_id):
    """Re-synchronise positions.value = Σ holdings.market_value pour une position
    A HOLDINGS, afin que la valeur stockee suive les holdings (leur source de
    verite). A appeler apres toute mutation de holdings (ajout/remplacement/
    suppression/import).

    NE TOUCHE PAS une position sans holdings : la value y est la saisie manuelle
    (immobilier, cash, fonds euros...), qui reste la source de verite du modele.
    Utilise market_value (valeur enregistree) et non le cours du jour, pour ne pas
    corrompre la valeur d'un snapshot historique lors d'un backfill.
    """
    row = conn.execute(
        'SELECT COUNT(*) AS n, COALESCE(SUM(market_value), 0) AS v '
        'FROM holdings WHERE position_id=?', (position_id,)
    ).fetchone()
    if row['n'] > 0:
        # Centimes des deux cotes : la somme est exacte, rien a arrondir.
        conn.execute('UPDATE positions SET value=? WHERE id=?',
                     (int(row['v'] or 0), position_id))


def get_entity_map(conn, date=None):
    if date:
        rows = conn.execute('''
            SELECT e.name,
                   COALESCE(s.gross_assets, e.gross_assets) AS gross_assets,
                   COALESCE(s.debt,         e.debt)         AS debt
            FROM entities e
            LEFT JOIN entity_snapshots s
              ON s.entity_name = e.name
             AND s.date = COALESCE(
                 (SELECT MAX(date) FROM entity_snapshots es2
                   WHERE es2.entity_name = e.name AND es2.date <= ?),
                 -- Avant la premiere valorisation datee, la plus ancienne :
                 -- la valeur courante reecrivait ces arretes a chaque
                 -- modification de l'entite, sans le dire.
                 (SELECT MIN(date) FROM entity_snapshots es3
                   WHERE es3.entity_name = e.name)
             )
        ''', (date,)).fetchall()
    else:
        rows = conn.execute('SELECT name, gross_assets, debt FROM entities').fetchall()
    from services.montants import euros
    return {r['name']: {'gross_assets': euros(r['gross_assets'] or 0), 'debt': euros(r['debt'] or 0)}
            for r in rows}
