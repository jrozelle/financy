"""
Parser PDF generique : tableaux pdfplumber + lignes de texte avec ISIN.
"""
from __future__ import annotations
import logging
import re
from typing import List, Optional, Tuple

from .common import (DetectedLine, ISIN_RE, NUMBER_RE,
                     parse_number, extract_numbers, line_has_isin, isin_luhn_ok)

logger = logging.getLogger('financy.parsers.pdf_generic')


def _heuristic_map_numbers(numbers: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float], float]:
    """Tente de mapper (quantity, unit_price, market_value) par coherence qty*prix~=valo."""
    clean = sorted((n for n in numbers if 1e-6 < abs(n) < 1e12), reverse=True)
    if not clean:
        return None, None, None, 0.0

    if len(clean) == 1:
        return None, None, clean[0], 0.2

    best = None
    best_err = float('inf')
    for i, mv in enumerate(clean):
        for j, price in enumerate(clean):
            if j == i:
                continue
            for k, qty in enumerate(clean):
                if k in (i, j):
                    continue
                if qty <= 0 or price <= 0 or mv <= 0:
                    continue
                expected = qty * price
                err = abs(expected - mv) / mv
                if 0.01 <= qty <= 1e7 and 0.01 <= price <= 1e6 and err < best_err:
                    best_err = err
                    best = (qty, price, mv)

    if best and best_err < 0.03:
        return best[0], best[1], best[2], max(0.5, 1.0 - best_err * 10)

    if len(clean) >= 2:
        mv = clean[0]
        other = clean[1]
        if 1e-6 < other < 1e7 and mv > 0:
            return None, None, mv, 0.3
    return None, None, clean[0] if clean else None, 0.2


def _guess_name(text: str, isin: str) -> Optional[str]:
    """Extrait un libelle probable autour de l'ISIN."""
    before = text.split(isin)[0].strip()
    while before and NUMBER_RE.fullmatch(before.split()[-1] if before.split() else ''):
        before = ' '.join(before.split()[:-1]).strip()
    name = re.sub(r'\s+', ' ', before).strip(' -|:;')
    return name[:120] if len(name) > 2 else None


def parse_tables(pdf) -> List[DetectedLine]:
    """Parcourt tous les tableaux extraits et produit des DetectedLine."""
    results = []
    for page in pdf.pages:
        try:
            tables = page.extract_tables()
        except Exception as e:
            logger.debug('extract_tables failed on page: %s', e)
            continue
        for table in tables or []:
            for row in table:
                cells = [(c or '').strip() for c in row]
                joined = ' | '.join(cells)
                isin = line_has_isin(joined)
                if not isin:
                    continue
                numbers = []
                name_parts = []
                for c in cells:
                    if isin in c or ISIN_RE.search(c):
                        continue
                    nums = extract_numbers(c)
                    if nums:
                        numbers.extend(nums)
                    else:
                        name_parts.append(c)
                qty, price, mv, conf = _heuristic_map_numbers(numbers)
                name = ' '.join(p for p in name_parts if len(p) > 1)[:120] or None
                results.append(DetectedLine(
                    isin=isin, name=name, quantity=qty, unit_price=price,
                    market_value=mv,
                    raw=joined, confidence=conf + 0.1,
                    source='table',
                ))
    return results


def parse_text_lines(pdf) -> List[DetectedLine]:
    """Parcourt le texte page par page et detecte les lignes contenant un ISIN."""
    results = []
    seen = set()
    for page in pdf.pages:
        try:
            text = page.extract_text() or ''
        except Exception as e:
            logger.debug('extract_text failed on page: %s', e)
            continue
        for line in text.split('\n'):
            isin = line_has_isin(line)
            if not isin:
                continue
            numbers = extract_numbers(line.replace(isin, ''))
            qty, price, mv, conf = _heuristic_map_numbers(numbers)
            name = _guess_name(line, isin)
            key = (isin, qty, mv)
            if key in seen:
                continue
            seen.add(key)
            results.append(DetectedLine(
                isin=isin, name=name, quantity=qty, unit_price=price,
                market_value=mv, raw=line.strip(), confidence=conf,
                source='text',
            ))
    return results
