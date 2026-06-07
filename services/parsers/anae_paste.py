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

from .common import DetectedLine, ISIN_RE, parse_number, isin_luhn_ok

_DATE_RE = re.compile(r'\b(\d{2})/(\d{2})/(\d{4})\b')
_DASHES = {'', '-', '–', '—'}


def looks_like_anae_paste(text: str) -> bool:
    """Empreinte du format : en-tete avec 'Px. Revient' et '+/- latentes'."""
    low = text.lower()
    has_pxr = 'px. revient' in low or 'px revient' in low
    return has_pxr and 'latentes' in low


def _to_iso(text: str) -> Optional[str]:
    m = _DATE_RE.search(text)
    if not m:
        return None
    d, mo, y = m.groups()
    return f'{y}-{mo}-{d}'


def _clean_num(token: Optional[str]) -> Optional[float]:
    """Nettoie un token de colonne (€, %, tiret) et le convertit en float."""
    if token is None:
        return None
    t = token.replace('€', '').replace('%', '').strip()
    if t in _DASHES:
        return None
    return parse_number(t)


def _split_columns(line: str) -> List[str]:
    """Decoupe la ligne de chiffres en colonnes.

    Le separateur de colonnes est une tabulation ou >=2 espaces ; l'espace
    simple a l'interieur des nombres (« 6 398,79 ») est ainsi preserve.
    """
    return [c for c in re.split(r'\t+| {2,}', line.strip()) if c != '']


def _slug(name: str) -> str:
    s = re.sub(r'[^A-Za-z0-9]+', '_', name.upper()).strip('_')
    return s or 'FONDS_EUROS'


def _is_header(line: str) -> bool:
    low = line.lower()
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
    cols = _split_columns(amount_line)
    euro_vals = [_clean_num(c) for c in cols if '€' in c]
    euro_vals = [v for v in euro_vals if v is not None]

    qty = px_revient = cours = montant = latentes = None
    if len(cols) >= 6:
        qty        = _clean_num(cols[0])
        px_revient = _clean_num(cols[1])
        cours      = _clean_num(cols[2])
        montant    = _clean_num(cols[3])
        latentes   = _clean_num(cols[4])
    else:
        # Fallback robuste si le decoupage en colonnes echoue :
        # Montant = plus grand montant en euros (la valorisation totale domine
        # toujours le cours unitaire et la +/- latente).
        if euro_vals:
            montant = max(euro_vals)
        # quantite = premier nombre non-euro de la ligne
        for c in cols:
            if '€' not in c and c.strip() not in _DASHES:
                n = _clean_num(c)
                if n is not None:
                    qty = n
                    break

    # Garde-fou : si le decoupage positionnel a pris le montant pour le cours
    # (cas separateur inhabituel), on recale sur le plus gros euro.
    if euro_vals and montant is not None and montant < max(euro_vals):
        montant = max(euro_vals)

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
