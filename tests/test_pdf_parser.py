"""Tests for the PDF parser service (phase 4).

Utilise fpdf2 pour generer des PDF synthetiques — pas besoin de PDF reel.
"""

import os
import pytest
from io import BytesIO

os.environ['PRICE_PROVIDER'] = 'mock'

from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa


def _make_pdf(lines):
    """Cree un petit PDF avec les lignes fournies."""
    import warnings
    warnings.filterwarnings('ignore', category=DeprecationWarning)
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font('Helvetica', size=10)
    for line in lines:
        pdf.cell(200, 10, txt=line, ln=1)
    return bytes(pdf.output(dest='S'))


# ─── Helpers unitaires ───────────────────────────────────────────────────────

class TestNumberParsing:
    def test_french_format(self):
        from services.pdf_parser import _parse_number
        assert _parse_number('1 234,56') == 1234.56
        assert _parse_number('1\u00a0234,56') == 1234.56
        assert _parse_number('1\u202f234,56') == 1234.56

    def test_english_format(self):
        from services.pdf_parser import _parse_number
        assert _parse_number('1,234.56') == 1234.56
        assert _parse_number('1234.56') == 1234.56

    def test_edge_cases(self):
        from services.pdf_parser import _parse_number
        assert _parse_number('') is None
        assert _parse_number('abc') is None
        assert _parse_number('-1 234,56') == -1234.56
        assert _parse_number('0,50') == 0.5


class TestHeuristic:
    def test_three_numbers_clean_match(self):
        from services.pdf_parser import _heuristic_map_numbers
        qty, price, mv, conf = _heuristic_map_numbers([9800.0, 490.0, 20.0])
        assert qty == 20.0 and price == 490.0 and mv == 9800.0
        assert conf > 0.9

    def test_extra_noise_number_still_matches(self):
        from services.pdf_parser import _heuristic_map_numbers
        # Exemple : une colonne 'frais' ou 'PMR' se rajoute a cote
        qty, price, mv, conf = _heuristic_map_numbers([9800.0, 490.0, 20.0, 400.0])
        assert qty == 20.0 and price == 490.0 and mv == 9800.0

    def test_only_one_number(self):
        from services.pdf_parser import _heuristic_map_numbers
        qty, price, mv, conf = _heuristic_map_numbers([1000.0])
        assert qty is None and price is None and mv == 1000.0
        assert conf < 0.5


class TestFormatDetection:
    def test_boursorama_pea(self):
        from services.pdf_parser import detect_format
        assert detect_format('BOURSORAMA PEA - Releve') == 'boursorama_pea'

    def test_linxea(self):
        from services.pdf_parser import detect_format
        assert detect_format('LINXEA Spirit 2') == 'linxea_av'

    def test_generic_fallback(self):
        from services.pdf_parser import detect_format
        assert detect_format('Contenu sans fingerprint') == 'generic'


# ─── Parser end-to-end ───────────────────────────────────────────────────────

class TestParsePdf:
    def test_boursorama_pea_with_3_etfs(self):
        from services.pdf_parser import parse_pdf
        pdf = _make_pdf([
            'BOURSORAMA PEA - Releve',
            'Detention au 18/04/2026',
            '',
            'Amundi MSCI World CW8 FR0010315770 20,00 490,00 9 800,00',
            'iShares Core MSCI World IWDA IE00B4L5Y983 50,00 104,00 5 200,00',
            'Amundi MSCI EM Asia PAASI FR0011550185 30,00 38,33 1 150,00',
        ])
        result = parse_pdf(pdf)
        assert result.format == 'boursorama_pea'
        assert len(result.lines) == 3
        isins = {l.isin for l in result.lines}
        assert isins == {'FR0010315770', 'IE00B4L5Y983', 'FR0011550185'}
        cw8 = next(l for l in result.lines if l.isin == 'FR0010315770')
        assert cw8.quantity == 20.0
        assert cw8.market_value == 9800.0
        assert cw8.confidence > 0.9

    def test_generic_format_no_fingerprint(self):
        from services.pdf_parser import parse_pdf
        pdf = _make_pdf([
            'Mon portefeuille',
            'FR0010315770 CW8 20 490 9800',
        ])
        result = parse_pdf(pdf)
        assert result.format == 'generic'
        assert len(result.lines) >= 1

    def test_invalid_isin_filtered(self):
        from services.pdf_parser import parse_pdf
        pdf = _make_pdf(['Ligne avec FR0010315771 checksum faux 10 100 1000'])
        result = parse_pdf(pdf)
        # ISIN invalide → rejete
        assert len(result.lines) == 0

    def test_empty_pdf_returns_warning(self):
        from services.pdf_parser import parse_pdf
        pdf = _make_pdf(['Texte sans ISIN'])
        result = parse_pdf(pdf)
        assert len(result.lines) == 0
        assert len(result.warnings) >= 1


# ─── Route /api/envelope/<id>/import-pdf ────────────────────────────────────

class TestImportRoute:
    def test_preview_returns_detected_lines(self, client):
        r = _make_position(client, category='Actions', envelope='PEA', value=0, debt=0)
        pid = r.get_json()['id']
        pdf = _make_pdf([
            'BOURSORAMA PEA Releve',
            'CW8 FR0010315770 20,00 490,00 9 800,00',
        ])
        r = client.post(
            f'/api/envelope/{pid}/import-pdf?step=preview',
            data={'file': (BytesIO(pdf), 'pea.pdf')},
            content_type='multipart/form-data',
            headers=CSRF_HEADERS,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data['format'] == 'boursorama_pea'
        assert len(data['lines']) == 1
        assert data['lines'][0]['isin'] == 'FR0010315770'

    def test_commit_replaces_existing_holdings(self, client):
        r = _make_position(client, category='Actions', envelope='PEA', value=0, debt=0)
        pid = r.get_json()['id']
        # Ligne initiale : une seule
        client.post(f'/api/positions/{pid}/holdings', json={
            'isin': 'FR0011550185', 'quantity': 1, 'market_value': 38
        }, headers=CSRF_HEADERS)

        # Commit avec 2 nouvelles lignes → l'ancienne disparait
        r = client.post(
            f'/api/envelope/{pid}/import-pdf?step=commit',
            json={'holdings': [
                {'isin': 'FR0010315770', 'quantity': 20, 'market_value': 9800},
                {'isin': 'IE00B4L5Y983', 'quantity': 50, 'market_value': 5200},
            ]},
            headers=CSRF_HEADERS,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 2

        # Verification
        r = client.get(f'/api/positions/{pid}/holdings')
        holdings = r.get_json()['holdings']
        isins = sorted(h['isin'] for h in holdings)
        assert isins == ['FR0010315770', 'IE00B4L5Y983']

    def test_reject_too_large_pdf(self, client):
        r = _make_position(client, category='Actions', envelope='PEA', value=0, debt=0)
        pid = r.get_json()['id']
        big = b'%PDF-1.0\n' + b'X' * (6 * 1024 * 1024)  # 6 Mo
        r = client.post(
            f'/api/envelope/{pid}/import-pdf?step=preview',
            data={'file': (BytesIO(big), 'big.pdf')},
            content_type='multipart/form-data',
            headers=CSRF_HEADERS,
        )
        assert r.status_code == 413

    def test_reject_wrong_extension(self, client):
        r = _make_position(client, category='Actions', envelope='PEA', value=0, debt=0)
        pid = r.get_json()['id']
        r = client.post(
            f'/api/envelope/{pid}/import-pdf?step=preview',
            data={'file': (BytesIO(b'%PDF-1.0\n'), 'fake.txt')},
            content_type='multipart/form-data',
            headers=CSRF_HEADERS,
        )
        assert r.status_code == 400

    def test_position_not_found(self, client):
        pdf = _make_pdf(['FR0010315770 20 490 9800'])
        r = client.post(
            '/api/envelope/99999/import-pdf?step=preview',
            data={'file': (BytesIO(pdf), 'x.pdf')},
            content_type='multipart/form-data',
            headers=CSRF_HEADERS,
        )
        assert r.status_code == 404

    def test_commit_rejects_invalid_isin(self, client):
        r = _make_position(client, category='Actions', envelope='PEA', value=0, debt=0)
        pid = r.get_json()['id']
        r = client.post(
            f'/api/envelope/{pid}/import-pdf?step=commit',
            json={'holdings': [{'isin': 'BADISIN', 'quantity': 1}]},
            headers=CSRF_HEADERS,
        )
        assert r.status_code == 400
