"""
Parser pour les PDFs de detail Credit Agricole / Predica (Anae).

Extrait ISIN, nombre de parts, VL et valorisation depuis un PDF
genere a partir de la page web de consultation du contrat.

Le layout web-to-PDF casse les nombres sur plusieurs lignes ;
ce parser gere ces coupures en travaillant sur le texte collapse.
"""
from __future__ import annotations
import re
from typing import List

from .common import DetectedLine, isin_luhn_ok


def parse_predica_detail(pdf) -> List[DetectedLine]:
    """Parse un PDF detail Predica/Anae (ISIN + qty + VL + valo)."""
    full = ''
    for page in pdf.pages:
        try:
            full += (page.extract_text() or '') + '\n'
        except Exception:
            continue

    collapsed = re.sub(r'\s+', ' ', full)

    # Index des valorisations (position, valeur)
    valos = []
    for m in re.finditer(r'Valorisation\s*([\d\s]+,\d+)\s*€', collapsed):
        v_str = m.group(1).replace(' ', '').replace(',', '.')
        try:
            valos.append((m.start(), float(v_str)))
        except ValueError:
            pass

    # Index des Code+ISIN — garde la derniere occurrence (gere les doublons de page)
    all_codes = [
        (m.start(), m.group(1))
        for m in re.finditer(r'Code([A-Z]{2}[A-Z0-9]{9}[0-9])', collapsed)
    ]
    last_pos = {}
    for pos, isin in all_codes:
        last_pos[isin] = pos
    isin_positions = sorted(last_pos.items(), key=lambda x: x[1])

    # Extraction par bloc
    claimed_valos = set()
    results = []
    for idx, (isin, code_pos) in enumerate(isin_positions):
        if not isin_luhn_ok(isin):
            continue
        end = isin_positions[idx + 1][1] if idx + 1 < len(isin_positions) else code_pos + 800
        block = collapsed[code_pos:end]

        # Quantite
        m_qty = re.search(r'Nombre([\d]+[,.]?\d*)', block)
        qty = float(m_qty.group(1).replace(',', '.')) if m_qty else None

        # VL : entre "Valeur" et "part|Date|Classe|http"
        m_vl = re.search(r'Valeur(.+?)(?:part|Date|Classe|http)', block)
        vl = None
        if m_vl:
            vl_digits = re.sub(r'[^\d,.]', '', m_vl.group(1)).strip()
            if vl_digits:
                try:
                    vl = float(vl_digits.replace(',', '.'))
                except ValueError:
                    pass

        # Valorisation : la plus proche non reclamee avant ce Code
        mv = None
        best_valo = None
        for vi, (vpos, vval) in enumerate(valos):
            if vi in claimed_valos or vpos >= code_pos:
                continue
            if best_valo is None or vpos > best_valo[0]:
                best_valo = (vpos, vval, vi)
        if best_valo:
            mv = best_valo[1]
            claimed_valos.add(best_valo[2])

        # Fallback : valo = qty * VL
        if mv is None and qty and vl:
            mv = round(qty * vl, 2)

        conf = 0.5
        if qty:
            conf += 0.15
        if vl:
            conf += 0.1
        if mv:
            conf += 0.15

        results.append(DetectedLine(
            isin=isin, name=None, quantity=qty, unit_price=vl,
            market_value=mv, raw='', confidence=min(conf, 1.0),
            source='predica',
        ))

    return results
