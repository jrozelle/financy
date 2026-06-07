"""
Parser pour le copier-coller du tableau de detail Credit Agricole / Anae (Predica).

Format du tableau web (copie depuis le navigateur) :

    Valeur  Date de derniere valorisation  Quantite  Px. Revient  Cours  Montant  +/- latentes  +/- %
    ACTIF EURO
        02/06/2026
        -     -     -     49 873,79 €     162,77 €     0,33 %
    AM ACTIONS EMERGENTS-R
    FR0013297546     27/05/2026
        35.1119     -     182,24 €     6 398,79 €     682,87 €     11,95 %
    ...

Structure repetee, 3 lignes logiques par support :
    1. NOM DU SUPPORT
    2. ISIN  +  date de valorisation   (pour ACTIF EURO : juste la date, pas d'ISIN)
    3. Quantite | Px. Revient | Cours | Montant | +/- latentes | +/- %

La ligne de chiffres est la seule a contenir un « € » : on l'utilise comme
delimiteur de bloc. ACTIF EURO (fonds euros, sans ISIN) devient un pseudo-ISIN.
"""
from __future__ import annotations
import re
from typing import List, Optional

from .common import DetectedLine, ISIN_RE, NUMBER_RE, parse_number, isin_luhn_ok

_DATE_RE = re.compile(r'\b(\d{2})/(\d{2})/(\d{4})\b')
# Un montant suivi du symbole €, separateur de milliers quelconque (espace,
# espace insecable, fine), decimale , ou .
_EURO_RE = re.compile(r'(-?\d[\d\s  .,]*?)\s*€')
# Ligne ISIN + date (detection structurelle, meme sans en-tete dans la selection)
_ISIN_DATE_RE = re.compile(r'[A-Z]{2}[A-Z0-9]{9}[0-9]\s+\d{2}/\d{2}/\d{4}')


def _normalize_ws(text: str) -> str:
    """Remplace les espaces speciaux par des espaces normaux."""
    return text.replace(' ', ' ').replace(' ', ' ').replace('\t', ' ')


def looks_like_anae_paste(text: str) -> bool:
    """Empreinte du format Anae.

    Soit l'en-tete (Px. Revient + latentes), soit, si la selection ne contient
    pas l'en-tete, la structure : plusieurs lignes 'ISIN  date' + des montants €.
    """
    low = _normalize_ws(text).lower()
    if ('px. revient' in low or 'px revient' in low) and 'latentes' in low:
        return True
    if len(_ISIN_DATE_RE.findall(text)) >= 2 and '€' in text:
        return True
    return False


def _parse_amounts(amount_line):
    """Extrait (qty, px_revient, cours, montant, latentes) d'une ligne de chiffres.

    Agnostique au separateur : on s'appuie sur la position des montants en euros.
    Ordre des colonnes Anae : Quantite | Px.Revient | Cours | Montant | +/- latentes | +/- %.
    Les colonnes en euros sont, de gauche a droite : [Px.Revient?] Cours? Montant Latentes.
    On lit donc depuis la fin : latentes = dernier €, montant = avant-dernier, etc.
    """
    euros = [parse_number(m.group(1)) for m in _EURO_RE.finditer(amount_line)]
    euros = [e for e in euros if e is not None]

    # Quantite : premier nombre avant le premier symbole €
    head = amount_line.split('€', 1)[0]
    qty = None
    for m in NUMBER_RE.finditer(head):
        n = parse_number(m.group(0))
        if n is not None:
            qty = n
            break

    latentes   = euros[-1] if len(euros) >= 1 else None
    montant    = euros[-2] if len(euros) >= 2 else (euros[-1] if euros else None)
    cours      = euros[-3] if len(euros) >= 3 else None
    px_revient = euros[-4] if len(euros) >= 4 else None
    return qty, px_revient, cours, montant, latentes


def _to_iso(text: str) -> Optional[str]:
    m = _DATE_RE.search(text)
    if not m:
        return None
    d, mo, y = m.groups()
    return f'{y}-{mo}-{d}'


def _slug(name: str) -> str:
    s = re.sub(r'[^A-Za-z0-9]+', '_', name.upper()).strip('_')
    return s or 'FONDS_EUROS'


def _is_header(line: str) -> bool:
    low = _normalize_ws(line).lower()
    if 'px. revient' in low or 'px revient' in low:
        return True
    if 'date de derni' in low and 'valorisation' in low:
        return True
    return False


def _build_entry(buffer: List[str], amount_line: str) -> Optional[DetectedLine]:
    """Construit une DetectedLine a partir des lignes de tete + ligne de chiffres."""
    # ISIN dans le buffer (les lignes avant la ligne de chiffres)
    isin = None
    for b in buffer:
        m = ISIN_RE.search(b)
        if m and isin_luhn_ok(m.group(1)):
            isin = m.group(1)
            break

    # Date de derniere valorisation (sur la ligne ISIN, ou la ligne date d'ACTIF EURO)
    as_of_date = None
    for b in buffer:
        iso = _to_iso(b)
        if iso:
            as_of_date = iso
            break

    # Nom : premiere ligne du buffer qui contient du texte une fois ISIN/date retires
    name = None
    for b in buffer:
        cand = b
        mm = ISIN_RE.search(cand)
        if mm:
            cand = cand.replace(mm.group(1), '')
        cand = _DATE_RE.sub('', cand).strip(' \t-|:;')
        if re.search(r'[A-Za-z]', cand) and len(cand) >= 2:
            name = cand[:120]
            break

    # Colonnes : Quantite | Px. Revient | Cours | Montant | +/- latentes | +/- %
    qty, px_revient, cours, montant, latentes = _parse_amounts(amount_line)

    fonds_euros = isin is None
    if fonds_euros:
        # Fonds euros : pas d'ISIN, valorisation manuelle, quantite = 1.
        slug = _slug(name or 'ACTIF_EURO')
        isin = f'FONDS_EUROS_{slug}'
        qty = 1.0
        cours = None

    if not isin:
        return None

    # PRU : Anae n'affiche pas le Px. Revient (toujours « - »), mais le cout
    # total se deduit de  Montant - (+/- latentes)  (cost_basis = cout total ;
    # le front le reconvertit en PRU unitaire = cost_basis / quantite).
    cost_basis = None
    if px_revient is not None and qty:
        cost_basis = round(px_revient * qty, 2)
    elif montant is not None and latentes is not None:
        cost_basis = round(montant - latentes, 2)

    # Confiance : haute si qty*cours coherent avec montant
    confidence = 0.5
    if fonds_euros and montant is not None:
        confidence = 0.9
    elif qty and cours and montant:
        expected = qty * cours
        err = abs(expected - montant) / montant if montant else 1.0
        confidence = 0.95 if err < 0.02 else (0.7 if err < 0.1 else 0.5)
    elif montant is not None:
        confidence = 0.6

    return DetectedLine(
        isin=isin,
        name=name,
        quantity=qty,
        cost_basis=cost_basis,
        market_value=montant,
        unit_price=cours,
        raw=amount_line.strip(),
        confidence=confidence,
        source='anae-paste',
        asset_class='fonds_euros' if fonds_euros else None,
        as_of_date=as_of_date,
    )


def parse_anae_paste(text: str) -> List[DetectedLine]:
    """Parse le tableau Anae colle depuis le navigateur."""
    results: List[DetectedLine] = []
    buffer: List[str] = []
    for raw in text.split('\n'):
        line = raw.strip()
        if not line:
            continue
        if _is_header(line):
            buffer = []
            continue
        if '€' in line:
            entry = _build_entry(buffer, line)
            if entry:
                results.append(entry)
            buffer = []
        else:
            buffer.append(line)
    return results
