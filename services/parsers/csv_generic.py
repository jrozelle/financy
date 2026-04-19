"""
Parser CSV generique pour imports de holdings.

Auto-detecte :
- Le separateur (; , \\t)
- Le format numerique (FR 1 234,56 vs EN 1,234.56)
- Les colonnes par heuristique semantique (ISIN, qty, prix, valo, nom...)

Fonctionne avec BoursoBank, Fortuneo, Bourse Direct, ou tout CSV
contenant au minimum un ISIN et une quantite.
"""
from __future__ import annotations
import csv
import logging
import re
from io import StringIO
from typing import List, Optional, Dict

from .common import DetectedLine, ParseResult, parse_number

logger = logging.getLogger('financy.parsers.csv_generic')

# ISIN strict (pas de word boundary — on matche une cellule entiere)
ISIN_RE = re.compile(r'^[A-Z]{2}[A-Z0-9]{9}[0-9]$')

# Pattern fonds euros dans les noms
_FONDS_EURO_RE = re.compile(r'fonds?\s*(en\s*)?euros?', re.IGNORECASE)

# Mapping semantique : chaque role -> liste de patterns (lowercase)
_COL_PATTERNS: Dict[str, List[str]] = {
    'isin':         ['isin', 'code isin', 'code_isin'],
    'name':         ['name', 'nom', 'libelle', 'libellé', 'support', 'titre',
                     'designation', 'désignation', 'intitule', 'intitulé', 'valeur'],
    'quantity':     ['quantity', 'quantite', 'quantité', 'qty', 'nb', 'parts',
                     'nombre', 'nbre', 'nb de parts', 'nombre de parts'],
    'cost_price':   ['buyingprice', 'buying_price', 'pru', 'prix achat',
                     'prix_achat', 'prix revient', 'prix de revient',
                     'cout', 'cost', 'cost_price', 'prix moyen',
                     'prix d\'achat', 'prix d\'achat moyen'],
    'last_price':   ['lastprice', 'last_price', 'cours', 'vl',
                     'valeur liquidative', 'valeur_liquidative', 'dernier cours',
                     'price', 'valeur de part'],
    'market_value': ['amount', 'montant', 'valorisation', 'valeur', 'market_value',
                     'marketvalue', 'montant eur', 'total', 'estimation'],
}


def _normalize_header(h: str) -> str:
    return h.strip().strip('"').strip('\ufeff').lower()


def _detect_separator(first_lines: str) -> str:
    counts = {';': 0, ',': 0, '\t': 0}
    for line in first_lines.split('\n')[:5]:
        for sep in counts:
            counts[sep] += line.count(sep)
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ';'


def _match_column(header: str) -> Optional[str]:
    h = _normalize_header(header)
    if h.startswith('date'):
        return None
    for role, patterns in _COL_PATTERNS.items():
        for pat in patterns:
            if pat == h or pat in h:
                return role
    return None


def _detect_columns(headers: List[str]) -> Dict[str, int]:
    mapping = {}
    for idx, header in enumerate(headers):
        role = _match_column(header)
        if role and role not in mapping:
            mapping[role] = idx
    if 'isin' not in mapping:
        for idx, header in enumerate(headers):
            if 'isin' in _normalize_header(header):
                mapping['isin'] = idx
                break
    return mapping


def _parse_csv_number(s: str) -> Optional[float]:
    """Strip guillemets et symboles monetaires, puis delegue a parse_number."""
    if s is None:
        return None
    cleaned = str(s).strip().strip('"').strip()
    if not cleaned or cleaned == '-':
        return None
    cleaned = cleaned.replace('€', '').replace('$', '').replace('%', '').strip()
    return parse_number(cleaned)


def _name_to_pseudo_isin(name: str) -> str:
    """Genere un pseudo-ISIN depuis un nom de fonds."""
    if _FONDS_EURO_RE.search(name):
        suffix = re.sub(r'[^A-Z0-9]', '_', name.upper())[:30]
        return f'FONDS_EUROS_{suffix}'
    suffix = re.sub(r'[^A-Z0-9]', '_', name.upper())[:30]
    return f'CUSTOM_{suffix}'


def _detect_source(headers: List[str]) -> str:
    joined = ' '.join(h.lower() for h in headers)
    if 'buyingprice' in joined and 'lastprice' in joined:
        return 'BoursoBank'
    if 'pru' in joined:
        return 'Courtier (PRU detecte)'
    return 'CSV generique'


def parse_csv(file_bytes: bytes) -> ParseResult:
    """Point d'entree : parse un CSV et renvoie un ParseResult."""
    for encoding in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
        try:
            text = file_bytes.decode(encoding)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    else:
        raise ValueError('Impossible de decoder le fichier CSV.')

    sep = _detect_separator(text)
    reader = csv.reader(StringIO(text), delimiter=sep)
    rows = list(reader)
    if len(rows) < 2:
        raise ValueError('Le CSV doit contenir au moins un header et une ligne de donnees.')

    headers = rows[0]
    col_map = _detect_columns(headers)

    if 'isin' not in col_map:
        for row in rows[1:min(6, len(rows))]:
            for idx, cell in enumerate(row):
                val = cell.strip().strip('"').upper()
                if ISIN_RE.match(val):
                    col_map['isin'] = idx
                    break
            if 'isin' in col_map:
                break

    # Mode sans ISIN : utiliser la colonne nom pour generer des pseudo-ISINs
    no_isin_mode = 'isin' not in col_map
    if no_isin_mode and 'name' not in col_map:
        raise ValueError('Aucune colonne ISIN ou nom detectee dans le CSV.')

    source = _detect_source(headers)
    result = ParseResult(format='csv', source_label=f'Import CSV — {source}')
    if no_isin_mode:
        result.warnings.append('Pas de colonne ISIN — pseudo-ISINs generes depuis les noms.')

    seen_isins = set()
    for row in rows[1:]:
        if no_isin_mode:
            if len(row) <= col_map['name']:
                continue
            name = row[col_map['name']].strip().strip('"')[:120] or None
            if not name:
                continue
            raw_isin = _name_to_pseudo_isin(name)
        else:
            if len(row) <= col_map['isin']:
                continue
            raw_isin = row[col_map['isin']].strip().strip('"').upper()
            if not ISIN_RE.match(raw_isin):
                continue
            name = None
            if 'name' in col_map and col_map['name'] < len(row):
                name = row[col_map['name']].strip().strip('"')[:120] or None

        if raw_isin in seen_isins:
            result.warnings.append(f'ISIN en doublon : {raw_isin} (derniere occurrence utilisee)')
        seen_isins.add(raw_isin)

        qty = _parse_csv_number(row[col_map['quantity']]) if 'quantity' in col_map and col_map['quantity'] < len(row) else None
        cost_price = _parse_csv_number(row[col_map['cost_price']]) if 'cost_price' in col_map and col_map['cost_price'] < len(row) else None
        last_price = _parse_csv_number(row[col_map['last_price']]) if 'last_price' in col_map and col_map['last_price'] < len(row) else None
        market_value = _parse_csv_number(row[col_map['market_value']]) if 'market_value' in col_map and col_map['market_value'] < len(row) else None

        cost_basis = round(cost_price * qty, 2) if cost_price is not None and qty is not None else None

        conf = 0.5
        if qty is not None:
            conf += 0.15
        if market_value is not None:
            conf += 0.15
        if last_price is not None and qty is not None and market_value:
            if abs(qty * last_price - market_value) / market_value < 0.05:
                conf += 0.1

        result.lines.append(DetectedLine(
            isin=raw_isin, name=name, quantity=qty, cost_basis=cost_basis,
            market_value=market_value, unit_price=last_price,
            raw=sep.join(row), confidence=min(conf, 1.0), source='csv',
        ))

    if result.lines and all(l.market_value is None for l in result.lines):
        result.needs_price_lookup = True

    result.total_market_value = sum(l.market_value or 0 for l in result.lines)

    if not result.lines:
        result.warnings.append('Aucune ligne avec ISIN valide detectee dans le CSV.')
    else:
        missing_qty = sum(1 for l in result.lines if l.quantity is None)
        if missing_qty:
            result.warnings.append(f'{missing_qty} ligne(s) sans quantite detectee.')
        missing_mv = sum(1 for l in result.lines if l.market_value is None)
        if missing_mv and not result.needs_price_lookup:
            result.warnings.append(f'{missing_mv} ligne(s) sans valorisation.')

    logger.info('CSV parsed: %d lines, sep=%r, cols=%s, source=%s',
                len(result.lines), sep, list(col_map.keys()), source)

    return result
