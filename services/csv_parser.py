"""Shim de compatibilite — redirige vers services.parsers.csv_generic."""
from services.parsers.csv_generic import parse_csv  # noqa: F401
from services.parsers.common import DetectedLine, ParseResult, parse_number as _parse_number  # noqa: F401
