"""
Parser pour texte colle depuis un navigateur (Credit Agricole, Bourso Vie, etc.).

Detecte les blocs structures type :
    NOM DU FONDS
    Voir la fiche
    Valorisation
    5 889,14 €
    Code ISIN
    FR0013297546
    Nombre de parts
    35,18
    Valeur de la part
    167,39 €
"""
from __future__ import annotations
import re
from typing import List

from .common import DetectedLine, ParseResult, parse_number, isin_luhn_ok, ISIN_RE

# Mapping Classification AMF → asset_class interne
_AMF_TO_ASSET_CLASS = {
    'actions internationales': 'opcvm',
    'actions de pays de la zone euros': 'opcvm',
    'actions de pays de la zone euro': 'opcvm',
    'actions françaises': 'opcvm',
    'diversifié': 'opcvm',
    'diversifie': 'opcvm',
    'fps': 'opcvm',
    'obligations et/ou titres de créances libellés en euros': 'obligation',
    'obligations et/ou titres de créances internationaux': 'obligation',
    'obligations et/ou titres de creances libelles en euros': 'obligation',
    'obligations et/ou titres de creances internationaux': 'obligation',
    'monétaire': 'opcvm',
    'monetaire': 'opcvm',
}


def _classify_amf(lines):
    """Extrait la Classification AMF et la mappe vers asset_class."""
    for i, line in enumerate(lines):
        if line.lower().startswith('classification amf') and i + 1 < len(lines):
            raw = lines[i + 1].strip().lower()
            return _AMF_TO_ASSET_CLASS.get(raw)
    return None


def parse_pasted_text(text: str) -> ParseResult:
    """Parse un texte colle depuis le navigateur."""
    result = ParseResult(format='paste', source_label='Import par copier-coller')

    # Split en blocs par "NOM\nVoir la fiche"
    blocks = re.split(r'\n(?=[A-Z][A-Z0-9\s\-&\'()/.,]+\n\s*Voir la fiche)', text)

    for block in blocks:
        lines = [l.strip() for l in block.strip().split('\n') if l.strip()]
        if len(lines) < 4:
            continue

        # Chercher ISIN
        isin = None
        for i, line in enumerate(lines):
            if line == 'Code ISIN' and i + 1 < len(lines):
                candidate = lines[i + 1].strip()
                m = ISIN_RE.match(candidate)
                if m and isin_luhn_ok(m.group(1)):
                    isin = m.group(1)
                break
        if not isin:
            continue

        # Nom : premiere ligne du bloc
        name = lines[0][:120] if not lines[0].startswith('Voir') else None

        # Valorisation
        mv = _extract_field(lines, 'Valorisation')
        # Nombre de parts
        qty = _extract_field(lines, 'Nombre de parts')
        # Valeur de la part
        vl = _extract_field(lines, 'Valeur de la part')
        # Prix de revient (si present)
        cost_price = _extract_field(lines, 'Prix de revient') or _extract_field(lines, "Prix d'Achat")
        cost_basis = round(cost_price * qty, 2) if cost_price and qty else None

        # Classification AMF → asset_class
        asset_class = _classify_amf(lines)

        result.lines.append(DetectedLine(
            isin=isin, name=name, quantity=qty, unit_price=vl,
            market_value=mv, cost_basis=cost_basis,
            confidence=0.9, source='paste',
            asset_class=asset_class,
        ))

    result.total_market_value = sum(l.market_value or 0 for l in result.lines)

    if not result.lines:
        result.warnings.append('Aucune ligne detectee dans le texte colle.')

    return result


def _extract_field(lines: List[str], label: str):
    """Cherche 'label' suivi de la valeur sur la ligne suivante."""
    for i, line in enumerate(lines):
        if line.lower().startswith(label.lower()) and i + 1 < len(lines):
            raw = lines[i + 1].replace('€', '').replace('%', '').strip()
            return parse_number(raw)
    return None
