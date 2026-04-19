"""
Parser pour les attestations de detention BoursoBank PEA.

Format : "30.0 actions / parts NOM (Code Isin FR0013380607)"
Extrait ISIN + quantite + nom. Pas de prix (needs_price_lookup=True).
"""
from __future__ import annotations
import re
from typing import List

from .common import DetectedLine, parse_number, isin_luhn_ok

_ATTESTATION_RE = re.compile(
    r'([\d.,]+)\s+actions?\s*/\s*parts?\s+(.*?)\s*\(Code\s+I?sin\s+([A-Z]{2}[A-Z0-9]{9}[0-9])\)',
    re.IGNORECASE,
)


def parse_attestation(pdf) -> List[DetectedLine]:
    """Parse les attestations de detention BoursoBank (ISIN + qty, pas de prix)."""
    results = []
    seen = set()
    for page in pdf.pages:
        try:
            text = page.extract_text() or ''
        except Exception:
            continue
        for m in _ATTESTATION_RE.finditer(text):
            qty = parse_number(m.group(1))
            name = m.group(2).strip()
            isin = m.group(3).upper()
            if not isin_luhn_ok(isin) or isin in seen:
                continue
            seen.add(isin)
            results.append(DetectedLine(
                isin=isin, name=name[:120] if name else None,
                quantity=qty, unit_price=None, market_value=None,
                raw=m.group(0).strip(), confidence=0.8,
                source='attestation',
            ))
    return results
