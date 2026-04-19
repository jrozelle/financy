"""
Package parsers : dispatch PDF / CSV vers le bon parser specialise.

Usage :
    from services.parsers import parse_pdf, parse_csv
"""
from __future__ import annotations
import logging
from io import BytesIO

from .common import (
    ParseResult, DetectedLine, PdfEncryptedError, PdfImageScanError,
    detect_format, format_label, deduplicate,
)
from .pdf_generic import parse_tables, parse_text_lines
from .pdf_attestation import parse_attestation
from .pdf_predica import parse_predica_detail
from .csv_generic import parse_csv  # noqa: F401 — re-export
from .text_paste import parse_pasted_text  # noqa: F401 — re-export

logger = logging.getLogger('financy.parsers')


def parse_pdf(file_bytes: bytes) -> ParseResult:
    """Point d'entree PDF : detecte le format et dispatch vers le bon parser.

    Leve :
    - PdfEncryptedError  : PDF chiffre (mot de passe requis)
    - PdfImageScanError  : PDF scan sans couche texte exploitable
    - RuntimeError       : tout autre probleme
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError('pdfplumber non installe')

    result = ParseResult(format='generic', source_label='Format inconnu')

    try:
        pdf_ctx = pdfplumber.open(BytesIO(file_bytes))
    except Exception as e:
        msg = str(e).lower()
        if 'password' in msg or 'encrypt' in msg:
            raise PdfEncryptedError('Le PDF est chiffre (mot de passe requis).')
        raise RuntimeError(f"Impossible d'ouvrir le PDF : {e}")

    with pdf_ctx as pdf:
        # Fingerprint sur les 3 premieres pages
        global_text = ''
        for page in pdf.pages[:3]:
            try:
                global_text += (page.extract_text() or '') + '\n'
            except Exception:
                pass
        fmt = detect_format(global_text)
        result.format = fmt
        result.source_label = format_label(fmt)

        # ── Parsers specifiques ──────────────────────────────────────────
        if fmt == 'boursobank_attestation':
            lines = parse_attestation(pdf)
            if lines:
                result.lines = lines
                result.total_market_value = sum(l.market_value or 0 for l in lines)
                result.needs_price_lookup = True
                return result

        if fmt == 'predica_detail':
            lines = parse_predica_detail(pdf)
            if lines:
                result.lines = lines
                result.total_market_value = sum(l.market_value or 0 for l in lines)
                return result

        # ── Parser generique (tableaux + texte) ─────────────────────────
        table_lines = parse_tables(pdf)
        text_lines = parse_text_lines(pdf)

    merged = deduplicate(table_lines + text_lines)
    merged.sort(key=lambda l: (-l.confidence, l.isin))

    result.lines = merged
    result.total_market_value = sum(l.market_value or 0 for l in merged)

    # Heuristique scan image
    if not merged and len(global_text.strip()) < 10:
        raise PdfImageScanError(
            "Le PDF ne contient pas de couche texte (scan image ?). "
            "Utilisez la saisie manuelle ou un OCR externe."
        )

    if not merged:
        result.warnings.append(
            "Aucune ligne detectee. Verifiez que le PDF n'est pas un scan image, "
            "ou saisissez manuellement."
        )
    else:
        low_conf = sum(1 for l in merged if l.confidence < 0.5)
        if low_conf:
            result.warnings.append(
                f'{low_conf} ligne(s) avec faible confiance : verifiez les quantites et valorisations.'
            )

    return result
