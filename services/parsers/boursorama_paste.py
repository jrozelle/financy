"""
Parser pour le copier-coller de la vue synchronisee Boursorama.

Couvre les comptes agreges dans Boursorama : PEA, et assurances-vie synchronisees
(BoursoVie, Lucya Cardif, contrats Predica/Anae, etc.). Le tableau se copie sous
deux mises en page selon la page :
- une ligne de chiffres par support (detail PEA, AV Anae/Lucya),
- une valeur par ligne (vue synchronisee PEA / BoursoVie).

Strategie robuste, agnostique a la mise en page : on segmente en blocs (un par
support, delimite par la ligne de NOM), puis dans chaque bloc :
- ISIN = ISIN valide present (sinon fonds euros / especes -> pseudo-ISIN),
- Montant = plus grand montant en euros (la valorisation totale domine toujours
  le cours unitaire, le prix de revient et la +/- latente),
- parmi les euros, ceux situes AVANT le Montant donnent Cours puis Px.Revient,
  ceux situes APRES donnent la +/- latente,
- Quantite = premier nombre (hors €/%/date) du bloc.
PRU (cost_basis = cout total) = Px.Revient x Quantite si present, sinon deduit de
Montant - (+/- latentes).
"""
from __future__ import annotations
import re
import unicodedata
from typing import List, Optional

from .common import (DetectedLine, ISIN_RE, NUMBER_RE, parse_number,
                     isin_luhn_ok, line_has_isin)

_DATE_RE = re.compile(r'\b(\d{2})/(\d{2})/(\d{4})\b')
# Montant monetaire : milliers = groupes de 3 chiffres exactement (evite de fusionner
# deux nombres voisins separes par une espace, ex "3 200" + "5,75" -> "5,75").
_NUM = r'-?\d{1,3}(?: \d{3})*(?:[.,]\d+)?|-?\d+(?:[.,]\d+)?'
# Lookbehind : le montant ne doit pas demarrer au milieu d'un autre nombre
# (ex : la fin "744" de la quantite "53,3744" suivie de " 402,77" -> faux "744 402,77").
_EURO_RE = re.compile(r'(?<![\d.,])(' + _NUM + r')\s*€')
_CODE_RE = re.compile(r'^[A-Z0-9]{5,12}$')          # ISIN ou code interne (ex: FGPERIN)
_NO_LETTER_RE = re.compile(r'[A-Za-z]')
_CASH_RE = re.compile(r'esp[eè]ces|liquidit|\bcash\b|compte\s*esp', re.I)


def _normalize_ws(text: str) -> str:
    """Espaces insecables / fines / tabulations -> espace normal."""
    return text.replace(' ', ' ').replace(' ', ' ').replace('\t', ' ')


def looks_like_boursorama_paste(text: str) -> bool:
    """Empreinte : en-tete (Px. Revient + latentes) ou structure ISIN+montants.

    Cede la priorite au parser « Voir la fiche » si ses marqueurs sont presents.
    """
    low = _normalize_ws(text).lower()
    if 'voir la fiche' in low or 'code isin' in low or 'nombre de parts' in low:
        return False
    if ('px. revient' in low or 'px revient' in low) and 'latentes' in low:
        return True
    valid_isins = sum(1 for m in ISIN_RE.finditer(text) if isin_luhn_ok(m.group(1)))
    return valid_isins >= 2 and '€' in text


def _iso_date(s: str) -> Optional[str]:
    m = _DATE_RE.search(s)
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else None


def _slug(name: str) -> str:
    ascii_name = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode()
    s = re.sub(r'[^A-Za-z0-9]+', '_', ascii_name.upper()).strip('_')
    return s or 'SANS_NOM'


def _strip_trailing_date_dash(line: str) -> str:
    s = _DATE_RE.sub('', line).strip()
    return re.sub(r'[\s\-–—]+$', '', s).strip()


def _is_code_line(line: str) -> bool:
    """Ligne = un code unique (ISIN ou code interne), eventuellement suivi d'une date/tiret."""
    core = _strip_trailing_date_dash(line)
    if not core or ' ' in core:
        return False
    return bool(_CODE_RE.match(core))


def _is_header(line: str) -> bool:
    low = _normalize_ws(line).lower()
    if 'px. revient' in low or 'px revient' in low:
        return True
    return 'date de' in low and ('valorisation' in low or 'valeur' in low)


def _is_name_line(line: str, next_line: str = '') -> bool:
    """Ligne de nom de support : contient des lettres, sans etre un code ni un en-tete.

    Cas CTO : un nom d'action court en majuscules (ADOBE, TESLA...) ressemble a un
    code interne (`_CODE_RE`), mais il est TOUJOURS suivi de son ISIN sur la ligne
    d'apres. On le promeut alors en nom. Un vrai code interne de fonds (ex FGPERIN,
    fonds euro Lucya) n'est PAS suivi d'un ISIN -> reste un code.
    """
    s = line.strip()
    if not s or not _NO_LETTER_RE.search(s):
        return False
    if _is_header(s):
        return False
    # Colonne de boutons : le tableau Boursorama expose "A" / "V" (Acheter /
    # Vendre) et chaque libelle est colle sur sa propre ligne. Promu en nom, il
    # ouvrait un bloc et fabriquait un faux fonds euros par bouton, soit deux
    # lignes parasites par support. Aucun support ne se nomme sur un caractere.
    if len(re.sub(r'[^0-9A-Za-z]', '', s)) < 2:
        return False
    if _is_code_line(s):
        return ISIN_RE.search(s) is None and line_has_isin(next_line) is not None
    return True


def _build(name: str, rest: List[str]) -> Optional[DetectedLine]:
    # ISIN reel
    isin = None
    for l in rest:
        m = ISIN_RE.search(l)
        if m and isin_luhn_ok(m.group(1)):
            isin = m.group(1)
            break

    # Date de valorisation
    as_of_date = None
    for l in rest:
        d = _iso_date(l)
        if d:
            as_of_date = d
            break

    # Texte des valeurs : on exclut les lignes de code, on retire les dates.
    # On conserve les retours a la ligne d'origine : _EURO_RE utilise un espace
    # LITTERAL pour les milliers (pas \s), donc un \n empeche de fusionner deux
    # nombres voisins situes sur des lignes distinctes (layout CTO : la quantite
    # "10" et le Px.Revient "179,90 €" ne doivent pas donner "10 179,90 €").
    value_text = '\n'.join(l for l in rest if not _is_code_line(l))
    value_text = _DATE_RE.sub(' ', value_text)

    euros = [parse_number(m.group(1)) for m in _EURO_RE.finditer(value_text)]
    euros = [e for e in euros if e is not None]

    # Quantite : premier nombre du head (avant le premier €), scanne ligne par
    # ligne pour ne pas fusionner avec le Px.Revient de la ligne suivante
    # (NUMBER_RE, lui, considere \n comme un espace de milliers).
    head = value_text.split('€', 1)[0]
    qty = None
    for seg in head.split('\n'):
        for m in NUMBER_RE.finditer(seg):
            n = parse_number(m.group(0))
            if n is not None:
                qty = n
                break
        if qty is not None:
            break

    # Montant = plus grand €, puis Cours/Px avant, +/- latente apres
    montant = max(euros) if euros else None
    cours = px_revient = latentes = None
    if montant is not None:
        idx = euros.index(montant)
        before, after = euros[:idx], euros[idx + 1:]
        if before:
            cours = before[-1]
        if len(before) >= 2:
            px_revient = before[-2]
        if after:
            latentes = after[0]

    # Fonds euros / especes : pas d'ISIN -> pseudo-ISIN, valorisation manuelle
    no_isin = isin is None
    asset_class = None
    if no_isin:
        # Sans ISIN ET sans montant, le bloc ne porte aucune donnee : c'est un
        # artefact de collage, pas un support. On ne fabrique pas un fonds euros
        # a partir de rien — il faudrait ensuite l'expliquer a l'utilisateur.
        if montant is None:
            return None
        qty = 1.0
        cours = None
        if _CASH_RE.search(name):
            isin = 'CUSTOM_' + _slug(name)
            asset_class = 'cash'
        else:
            isin = 'FONDS_EUROS_' + _slug(name)
            asset_class = 'fonds_euros'

    if not isin:
        return None

    # PRU / cout total
    cost_basis = None
    if px_revient is not None and qty:
        cost_basis = round(px_revient * qty, 2)
    elif montant is not None and latentes is not None:
        cost_basis = round(montant - latentes, 2)

    # Confiance
    confidence = 0.5
    if no_isin and montant is not None:
        confidence = 0.9
    elif qty and cours and montant:
        err = abs(qty * cours - montant) / montant if montant else 1.0
        confidence = 0.95 if err < 0.02 else (0.7 if err < 0.1 else 0.5)
    elif montant is not None:
        confidence = 0.6

    return DetectedLine(
        isin=isin,
        name=(name or '')[:120] or None,
        quantity=qty,
        cost_basis=cost_basis,
        market_value=montant,
        unit_price=cours,
        raw=' '.join(rest)[:300],
        confidence=confidence,
        source='boursorama-paste',
        asset_class=asset_class,
        as_of_date=as_of_date,
    )


def parse_boursorama_paste(text: str) -> List[DetectedLine]:
    """Parse le tableau Boursorama colle (toutes mises en page)."""
    text = _normalize_ws(text)
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    results: List[DetectedLine] = []
    name: Optional[str] = None
    rest: List[str] = []
    n = len(lines)
    for i, l in enumerate(lines):
        if _is_header(l):
            name, rest = None, []
            continue
        next_line = lines[i + 1] if i + 1 < n else ''
        if _is_name_line(l, next_line):
            if name is not None:
                entry = _build(name, rest)
                if entry:
                    results.append(entry)
            name, rest = l, []
        elif name is not None:
            rest.append(l)
    if name is not None:
        entry = _build(name, rest)
        if entry:
            results.append(entry)
    return results
