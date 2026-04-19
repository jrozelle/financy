"""Tests for auto-split holdings, text paste parser, and settings API."""

import pytest

# Reuse fixtures & helpers from test_api
from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa


def _make_position_av(client, **kwargs):
    """Position Assurance-vie, prete a accueillir des holdings mixtes."""
    resp = _make_position(client, category='Actions', envelope='Assurance-vie',
                          value=0, debt=0, **kwargs)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


# ---- Test 1: Auto-split holdings by category --------------------------------

class TestAutoSplitSameClass:
    """All ETF items stay in the same position (no split)."""

    def test_no_split_all_etf(self, client):
        pos = _make_position_av(client)
        r = client.put(f'/api/positions/{pos["id"]}/holdings', json={
            'holdings': [
                {'isin': 'FR0010315770', 'name': 'Amundi MSCI World ETF',
                 'quantity': 20, 'market_value': 9800},
                {'isin': 'IE00B4L5Y983', 'name': 'iShares Core MSCI World UCITS',
                 'quantity': 50, 'market_value': 5200},
            ]
        }, headers=CSRF_HEADERS)
        assert r.status_code == 200
        data = r.get_json()
        # No split_categories key when all items are the same class
        assert 'split_categories' not in data
        assert len(data['holdings']) == 2


class TestAutoSplitMixedClasses:
    """ETF + fonds euros items get split into companion positions."""

    def test_split_etf_plus_fonds_euros(self, client):
        pos = _make_position_av(client, owner='Alice',
                                establishment='Credit Agricole')
        r = client.put(f'/api/positions/{pos["id"]}/holdings', json={
            'holdings': [
                {'isin': 'FR0010315770', 'name': 'Amundi MSCI World ETF',
                 'quantity': 20, 'market_value': 9800},
                {'isin': 'IE00B4L5Y983', 'name': 'iShares Core MSCI World UCITS',
                 'quantity': 50, 'market_value': 5200},
                {'isin': 'US0378331005', 'name': 'Some Other ETF Tracker',
                 'quantity': 10, 'market_value': 3000},
                {'isin': 'FONDS_EUROS_LINXEA', 'name': 'Fonds en Euros Predica',
                 'quantity': 1, 'market_value': 25000, 'is_priceable': False},
            ]
        }, headers=CSRF_HEADERS)
        assert r.status_code == 200
        data = r.get_json()
        # The response should indicate a split happened
        assert 'split_categories' in data
        cats = data['split_categories']
        assert 'Actions' in cats
        assert 'Fond Euro' in cats

    def test_companion_position_inherits_metadata(self, client):
        """The auto-created companion position copies owner/envelope/establishment/date."""
        pos = _make_position_av(client, owner='Alice', date='2024-06-01',
                                establishment='Credit Agricole')
        client.put(f'/api/positions/{pos["id"]}/holdings', json={
            'holdings': [
                {'isin': 'FR0010315770', 'name': 'Amundi MSCI World ETF',
                 'quantity': 20, 'market_value': 9800},
                {'isin': 'FONDS_EUROS_LINXEA', 'name': 'Fonds en Euros Predica',
                 'quantity': 1, 'market_value': 25000, 'is_priceable': False},
            ]
        }, headers=CSRF_HEADERS)
        # Fetch all positions for this date
        r = client.get('/api/positions?date=2024-06-01')
        positions = r.get_json()
        assert len(positions) == 2
        # Find the companion (Fond Euro)
        companion = next(p for p in positions if p['category'] == 'Fond Euro')
        assert companion['owner'] == 'Alice'
        assert companion['envelope'] == 'Assurance-vie'
        assert companion['date'] == '2024-06-01'
        assert companion.get('establishment') == 'Credit Agricole'


# ---- Test 2: Text paste parser ----------------------------------------------

class TestTextPasteParser:
    """Tests for services/parsers/text_paste.parse_pasted_text."""

    SINGLE_BLOCK = (
        "AMUNDI ETF MSCI WORLD\n"
        "Voir la fiche\n"
        "Valorisation\n"
        "5 889,14 \u20ac\n"
        "Code ISIN\n"
        "FR0013297546\n"
        "Nombre de parts\n"
        "35,18\n"
        "Valeur de la part\n"
        "167,39 \u20ac\n"
    )

    MULTI_BLOCK = (
        "AMUNDI ETF MSCI WORLD\n"
        "Voir la fiche\n"
        "Valorisation\n"
        "5 889,14 \u20ac\n"
        "Code ISIN\n"
        "FR0013297546\n"
        "Nombre de parts\n"
        "35,18\n"
        "Valeur de la part\n"
        "167,39 \u20ac\n"
        "\n"
        "LYXOR UCITS STOXX 600\n"
        "Voir la fiche\n"
        "Valorisation\n"
        "12 345,67 \u20ac\n"
        "Code ISIN\n"
        "IE00B4L5Y983\n"
        "Nombre de parts\n"
        "100,00\n"
        "Valeur de la part\n"
        "123,45 \u20ac\n"
    )

    def test_parse_single_block(self):
        from services.parsers.text_paste import parse_pasted_text
        result = parse_pasted_text(self.SINGLE_BLOCK)
        assert len(result.lines) == 1
        line = result.lines[0]
        assert line.isin == 'FR0013297546'
        assert line.quantity == pytest.approx(35.18)
        assert line.unit_price == pytest.approx(167.39)
        assert line.market_value == pytest.approx(5889.14)

    def test_parse_multiple_blocks(self):
        from services.parsers.text_paste import parse_pasted_text
        result = parse_pasted_text(self.MULTI_BLOCK)
        assert len(result.lines) == 2

    def test_parse_empty_text(self):
        from services.parsers.text_paste import parse_pasted_text
        result = parse_pasted_text('')
        assert len(result.lines) == 0
        assert len(result.warnings) > 0

    def test_parse_invalid_text(self):
        from services.parsers.text_paste import parse_pasted_text
        result = parse_pasted_text('Some random text without any structure')
        assert len(result.lines) == 0
        assert len(result.warnings) > 0

    def test_fund_name_with_digits(self):
        from services.parsers.text_paste import parse_pasted_text
        block = (
            "ELTIF-B1 PRIVATE EQUITY FUND\n"
            "Voir la fiche\n"
            "Valorisation\n"
            "10 000,00 \u20ac\n"
            "Code ISIN\n"
            "FR0010315770\n"
            "Nombre de parts\n"
            "50,00\n"
            "Valeur de la part\n"
            "200,00 \u20ac\n"
        )
        result = parse_pasted_text(block)
        assert len(result.lines) == 1
        assert result.lines[0].name == 'ELTIF-B1 PRIVATE EQUITY FUND'
        assert result.lines[0].isin == 'FR0010315770'
        assert result.lines[0].quantity == pytest.approx(50.0)


# ---- Test 3: Settings API ---------------------------------------------------

class TestSettingsAPI:
    """Tests for GET/PUT /api/settings."""

    @pytest.fixture(autouse=True)
    def _clear_env_key(self, monkeypatch):
        """Ensure no ANTHROPIC_API_KEY env var interferes."""
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        # Invalidate the settings cache so each test starts fresh
        from services.settings import invalidate_cache
        invalidate_cache()
        yield
        invalidate_cache()

    def test_get_no_settings(self, client):
        r = client.get('/api/settings')
        assert r.status_code == 200
        data = r.get_json()
        assert data['anthropic_api_key_set'] is False
        assert data['effective_source'] == 'none'
        assert data['llm_available'] is False

    def test_put_valid_key(self, client):
        r = client.put('/api/settings', json={
            'anthropic_api_key': 'sk-ant-test123456',
        }, headers=CSRF_HEADERS)
        assert r.status_code == 200
        assert r.get_json()['ok'] is True

    def test_get_after_put_shows_masked_key(self, client):
        client.put('/api/settings', json={
            'anthropic_api_key': 'sk-ant-test123456abcdef',
        }, headers=CSRF_HEADERS)
        from services.settings import invalidate_cache
        invalidate_cache()
        r = client.get('/api/settings')
        data = r.get_json()
        assert data['anthropic_api_key_set'] is True
        assert data['effective_source'] == 'db'
        # Key should be masked — starts with first chars, ends with ...
        masked = data['anthropic_api_key_masked']
        assert masked.startswith('sk-ant-tes')
        assert '...' in masked
        # Full key must NOT appear
        assert 'test123456abcdef' not in masked

    def test_put_empty_key_removes_it(self, client):
        # Set a key first
        client.put('/api/settings', json={
            'anthropic_api_key': 'sk-ant-test123456',
        }, headers=CSRF_HEADERS)
        # Remove it
        client.put('/api/settings', json={
            'anthropic_api_key': '',
        }, headers=CSRF_HEADERS)
        from services.settings import invalidate_cache
        invalidate_cache()
        r = client.get('/api/settings')
        data = r.get_json()
        assert data['anthropic_api_key_set'] is False
        # With no env var either, source should be 'none'
        assert data['effective_source'] == 'none'

    def test_put_invalid_key_returns_400(self, client):
        r = client.put('/api/settings', json={
            'anthropic_api_key': 'not-a-valid-key-format',
        }, headers=CSRF_HEADERS)
        assert r.status_code == 400
        assert 'error' in r.get_json()
