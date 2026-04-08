import pytest
import sqlite3
import os
import tempfile
from contextlib import contextmanager

# Patch DB_PATH before importing models
import models
_tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_tmp.close()
models.DB_PATH = _tmp.name
models._BASE_DIR = os.path.dirname(_tmp.name)

from models import (
    compute_position, get_entity_map, get_db, init_db, load_referential,
    validate_date, validate_number, validate_string, validate_pct,
    DEFAULT_REFERENTIAL, CATEGORY_MOBILIZABLE, ENVELOPE_META,
)


@pytest.fixture(autouse=True)
def fresh_db():
    """Crée une DB propre avant chaque test."""
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)
    init_db()
    yield
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)


# ─── Validation ───────────────────────────────────────────────────────────────

class TestValidation:
    def test_validate_date_valid(self):
        assert validate_date('2024-01-15') is True
        assert validate_date('2025-12-31') is True

    def test_validate_date_invalid(self):
        assert validate_date('') is False
        assert validate_date(None) is False
        assert validate_date('2024-13-01') is False
        assert validate_date('not-a-date') is False
        assert validate_date('2024/01/15') is False

    def test_validate_number(self):
        assert validate_number(100) is True
        assert validate_number(0) is True
        assert validate_number(None) is True
        assert validate_number(-5) is False
        assert validate_number(-5, allow_negative=True) is True
        assert validate_number('abc') is False

    def test_validate_string(self):
        assert validate_string('hello') is True
        assert validate_string(None) is True
        assert validate_string('a' * 501) is False
        assert validate_string('a' * 500) is True

    def test_validate_pct(self):
        assert validate_pct(0.5) is True
        assert validate_pct(1.0) is True
        assert validate_pct(0) is True
        assert validate_pct(None) is True
        assert validate_pct(-0.1) is False
        assert validate_pct(1.1) is False


# ─── compute_position ────────────────────────────────────────────────────────

class TestComputePosition:
    def test_basic_position(self):
        pos = {
            'category': 'Actions',
            'envelope': 'PEA',
            'value': 10000,
            'debt': 0,
            'ownership_pct': 1.0,
            'debt_pct': 1.0,
            'entity': None,
            'mobilizable_pct_override': None,
        }
        result = compute_position(pos)
        assert result['gross_attributed'] == 10000
        assert result['debt_attributed'] == 0
        assert result['net_attributed'] == 10000
        assert result['net_value'] == 10000
        assert result['liquidity'] == 'J2–J7'
        assert result['mobilizable_pct'] == 0.9  # Actions = 90%
        assert result['mobilizable_value'] == 9000

    def test_partial_ownership(self):
        pos = {
            'category': 'Immobilier',
            'envelope': 'SCI',
            'value': 300000,
            'debt': 150000,
            'ownership_pct': 0.5,
            'debt_pct': 0.5,
            'entity': None,
            'mobilizable_pct_override': None,
        }
        result = compute_position(pos)
        assert result['gross_attributed'] == 150000
        assert result['debt_attributed'] == 75000
        assert result['net_attributed'] == 75000

    def test_entity_position(self):
        entity_map = {
            'SCI Test': {'gross_assets': 400000, 'debt': 200000}
        }
        pos = {
            'category': 'Immobilier',
            'envelope': 'SCI',
            'value': 0,
            'debt': 0,
            'ownership_pct': 0.3,
            'debt_pct': 0.3,
            'entity': 'SCI Test',
            'mobilizable_pct_override': None,
        }
        result = compute_position(pos, entity_map)
        assert result['gross_attributed'] == 120000  # 400000 * 0.3
        assert result['debt_attributed'] == 60000    # 200000 * 0.3
        assert result['net_attributed'] == 60000

    def test_mobilizable_override(self):
        pos = {
            'category': 'Immobilier',
            'envelope': 'Immobilier',
            'value': 200000,
            'debt': 0,
            'ownership_pct': 1.0,
            'debt_pct': 1.0,
            'entity': None,
            'mobilizable_pct_override': 0.5,
        }
        result = compute_position(pos)
        assert result['mobilizable_pct'] == 0.5
        assert result['mobilizable_value'] == 100000

    def test_negative_net_no_mobilizable(self):
        pos = {
            'category': 'Immobilier',
            'envelope': 'Immobilier',
            'value': 100000,
            'debt': 150000,
            'ownership_pct': 1.0,
            'debt_pct': 1.0,
            'entity': None,
            'mobilizable_pct_override': None,
        }
        result = compute_position(pos)
        assert result['net_attributed'] == -50000
        assert result['mobilizable_value'] == 0

    def test_unknown_envelope(self):
        pos = {
            'category': 'Autre',
            'envelope': 'Enveloppe Inconnue',
            'value': 5000,
            'debt': 0,
            'ownership_pct': 1.0,
            'debt_pct': 1.0,
            'entity': None,
            'mobilizable_pct_override': None,
        }
        result = compute_position(pos)
        assert result['liquidity'] == '30J+'
        assert result['friction'] == 'Mixte'


# ─── get_entity_map ──────────────────────────────────────────────────────────

class TestGetEntityMap:
    def test_empty(self):
        with get_db() as conn:
            result = get_entity_map(conn)
        assert result == {}

    def test_basic_entity(self):
        with get_db() as conn:
            conn.execute(
                "INSERT INTO entities (name, gross_assets, debt) VALUES (?, ?, ?)",
                ('SCI Test', 300000, 100000)
            )
        with get_db() as conn:
            result = get_entity_map(conn)
        assert 'SCI Test' in result
        assert result['SCI Test']['gross_assets'] == 300000
        assert result['SCI Test']['debt'] == 100000

    def test_entity_with_date_snapshot(self):
        with get_db() as conn:
            conn.execute(
                "INSERT INTO entities (name, gross_assets, debt) VALUES (?, ?, ?)",
                ('SCI A', 300000, 100000)
            )
            conn.execute(
                "INSERT INTO entity_snapshots (entity_name, date, gross_assets, debt) VALUES (?, ?, ?, ?)",
                ('SCI A', '2024-01-01', 250000, 120000)
            )
            conn.execute(
                "INSERT INTO entity_snapshots (entity_name, date, gross_assets, debt) VALUES (?, ?, ?, ?)",
                ('SCI A', '2024-06-01', 280000, 110000)
            )

        # Date avant tous les snapshots → fallback sur la valeur courante
        with get_db() as conn:
            result = get_entity_map(conn, '2023-01-01')
        assert result['SCI A']['gross_assets'] == 300000  # fallback

        # Date entre les deux snapshots → utilise le premier
        with get_db() as conn:
            result = get_entity_map(conn, '2024-03-15')
        assert result['SCI A']['gross_assets'] == 250000

        # Date après le dernier snapshot → utilise le dernier
        with get_db() as conn:
            result = get_entity_map(conn, '2025-01-01')
        assert result['SCI A']['gross_assets'] == 280000

    def test_entity_no_snapshots_with_date(self):
        with get_db() as conn:
            conn.execute(
                "INSERT INTO entities (name, gross_assets, debt) VALUES (?, ?, ?)",
                ('SCI B', 500000, 200000)
            )
        with get_db() as conn:
            result = get_entity_map(conn, '2024-06-01')
        # Pas de snapshot → fallback sur valeur courante de l'entité
        assert result['SCI B']['gross_assets'] == 500000


# ─── load_referential ─────────────────────────────────────────────────────────

class TestLoadReferential:
    def test_default_referential(self):
        with get_db() as conn:
            ref = load_referential(conn)
        assert ref['owners'] == DEFAULT_REFERENTIAL['owners']
        assert 'Actions' in ref['categories']

    def test_custom_referential(self):
        import json
        custom = {'owners': ['Alice', 'Bob'], 'categories': ['Test']}
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES ('referential', ?)",
                (json.dumps(custom),)
            )
        with get_db() as conn:
            ref = load_referential(conn)
        assert ref['owners'] == ['Alice', 'Bob']
        assert ref['categories'] == ['Test']
        # liquidity_order toujours le default
        assert ref['liquidity_order'] == DEFAULT_REFERENTIAL['liquidity_order']


# ─── XIRR ─────────────────────────────────────────────────────────────────────

class TestXIRR:
    def test_basic_xirr(self):
        from routes.synthese import _xirr
        # Investir 1000, récupérer 1100 un an plus tard = ~10%
        cashflows = [('2024-01-01', -1000), ('2025-01-01', 1100)]
        result = _xirr(cashflows)
        assert result is not None
        assert abs(result - 10.0) < 0.5

    def test_no_sign_change(self):
        from routes.synthese import _xirr
        # Tous positifs → pas de TRI
        result = _xirr([('2024-01-01', 100), ('2025-01-01', 200)])
        assert result is None

    def test_insufficient_data(self):
        from routes.synthese import _xirr
        result = _xirr([('2024-01-01', -1000)])
        assert result is None
