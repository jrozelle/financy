"""
Shim de compatibilite — redirige vers services.parsers.

Les imports historiques (from services.pdf_parser import ...) continuent
de fonctionner. Le code reel est dans services/parsers/.
"""
# Re-exports publics
from services.parsers import parse_pdf  # noqa: F401
from services.parsers.common import (  # noqa: F401
    DetectedLine, ParseResult, PdfEncryptedError, PdfImageScanError,
    parse_number as _parse_number, detect_format,
    isin_luhn_ok as _isin_luhn_ok, ISIN_RE, NUMBER_RE,
)
from services.parsers.pdf_generic import _heuristic_map_numbers  # noqa: F401
