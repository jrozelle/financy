"""
Parser PDF generique pour imports de positions (PEA / AV / CTO).

Approche SANS template : heuristique auto-detectante en 3 couches.

1. Couche TABLEAUX (la plus fiable)
   pdfplumber.extract_tables() renvoie les tableaux structures du PDF.
   Si une cellule contient un ISIN, la ligne entiere est exploitable :
   on detecte les colonnes numeriques (qty, prix, valo) par leur magnitude
   et par la contrainte qty * prix ~= valo.

2. Couche LIGNES DE TEXTE (fallback)
   Si pas de tableau extrait, on tombe sur les lignes de texte. Pour chaque
   ligne contenant un ISIN valide, on isole les nombres et on applique la
   meme heuristique de cohérence.

3. Couche FINGERPRINT (enrichissement)
   On detecte l'origine probable (Boursorama / Linxea / Fortuneo / etc.)
   par empreintes textuelles. Cela sert a afficher le format reconnu
   a l'utilisateur et a biaiser l'ordre des colonnes si besoin.

Sortie : liste de DetectedLine avec score de confiance. L'utilisateur
valide et corrige dans une modale avant commit.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field, asdict
from io import BytesIO
from typing import List, Optional, Tuple

logger = logging.getLogger('financy.pdf_parser')

# ISIN standard : 2 lettres + 9 alphanum + 1 digit
ISIN_RE = re.compile(r'\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b')

# Nombres en format FR (1 234,56) ou EN (1,234.56) ou brut (1234.56)
# On capture aussi l'optionnel signe negatif et le pourcentage
NUMBER_RE = re.compile(
    r'-?\d{1,3}(?:[\s\u202f\u00a0]?\d{3})*(?:[.,]\d+)?|-?\d+(?:[.,]\d+)?'
)

# Empreintes de formats connus — utilisees pour afficher l'origine
# et pour moduler la confiance
# Chaque entree : (code, must_have_keywords, optional_keywords_for_disambiguation)
# Ordre d'evaluation : les entrees les plus specifiques en premier.
FORMAT_FINGERPRINTS = [
    ('boursorama_pea',      ['BOURSORAMA'],                ['PEA']),
    ('boursorama_cto',      ['BOURSORAMA'],                ['CTO', 'COMPTE TITRES', 'COMPTE-TITRES']),
    ('boursorama',          ['BOURSORAMA'],                []),
    ('fortuneo_pea',        ['FORTUNEO'],                  ['PEA']),
    ('fortuneo',            ['FORTUNEO'],                  []),
    ('bourse_direct',       ['BOURSE DIRECT'],             []),
    ('binck',               ['BINCK'],                     []),
    ('linxea_av',           ['LINXEA'],                    []),
    ('spirica_av',          ['SPIRICA'],                   []),
    ('suravenir_av',        ['SURAVENIR'],                 []),
    ('generali_av',         ['GENERALI'],                  []),
    ('yomoni_av',           ['YOMONI'],                    []),
    ('nalo_av',             ['NALO'],                      []),
    ('swisslife_av',        ['SWISSLIFE'],                 []),
    ('swisslife_av',        ['SWISS LIFE'],                []),
    ('credit_agricole',     ['CREDIT AGRICOLE'],           []),
    ('credit_agricole',     ['CRÉDIT AGRICOLE'],           []),
    ('bnp',                 ['BNP PARIBAS'],               []),
    ('societe_generale',    ['SOCIETE GENERALE'],          []),
    ('societe_generale',    ['SOCIÉTÉ GÉNÉRALE'],          []),
]


# ─── Validation ISIN (checksum Luhn) ─────────────────────────────────────────

def _isin_luhn_ok(isin: str) -> bool:
    expanded = ''.join(
        str(ord(c) - ord('A') + 10) if c.isalpha() else c for c in isin
    )
    total = 0
    for i, d in enumerate(reversed(expanded)):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _parse_number(s: str) -> Optional[float]:
    """Convertit un nombre au format FR/EN en float, ou None si impossible."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    # Retire espaces ordinaires + insecables + fines (U+00A0, U+202F)
    cleaned = s.replace(' ', '').replace('\u00a0', '').replace('\u202f', '')
    # Si virgule + point : le dernier separe decimal
    if ',' in cleaned and '.' in cleaned:
        if cleaned.rfind(',') > cleaned.rfind('.'):
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        # Heuristique : si 3 chiffres apres la virgule et pas d'autres virgules
        # avant, c'est un separateur de milliers rare ; sinon c'est la decimale.
        if re.search(r',\d{3}(?:\D|$)', cleaned) and cleaned.count(',') == 1 \
                and not re.search(r',\d{1,2}$', cleaned):
            cleaned = cleaned.replace(',', '')
        else:
            cleaned = cleaned.replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_numbers(text: str) -> List[float]:
    """Extrait tous les nombres valides d'un bout de texte."""
    out = []
    for m in NUMBER_RE.finditer(text):
        n = _parse_number(m.group(0))
        if n is not None and not _looks_like_date_fragment(m.group(0)):
            out.append(n)
    return out


def _looks_like_date_fragment(s: str) -> bool:
    """Filtre les fragments qui ressemblent a une date (01/02/2024, 2024)."""
    return '/' in s or bool(re.match(r'^(19|20)\d{2}$', s.strip()))


# ─── Detection du format ─────────────────────────────────────────────────────

def detect_format(text: str) -> str:
    """Renvoie le code du format detecte ou 'generic' si inconnu.

    Les variantes specifiques (boursorama_pea) sont testees avant les
    generiques (boursorama), ce qui permet de choisir la bonne variante
    si les mots-cles optionnels sont presents.
    """
    upper = text.upper()
    for code, must_have, optionals in FORMAT_FINGERPRINTS:
        if not all(kw.upper() in upper for kw in must_have):
            continue
        if optionals and not any(kw.upper() in upper for kw in optionals):
            continue
        return code
    return 'generic'


# ─── Structures ──────────────────────────────────────────────────────────────

@dataclass
class DetectedLine:
    isin: str
    name: Optional[str] = None
    quantity: Optional[float] = None
    cost_basis: Optional[float] = None
    market_value: Optional[float] = None
    unit_price: Optional[float] = None
    raw: str = ''
    confidence: float = 0.0
    source: str = ''   # 'table' | 'text'

    def to_dict(self):
        return asdict(self)


@dataclass
class ParseResult:
    format: str
    source_label: str
    lines: List[DetectedLine] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    total_market_value: float = 0.0

    def to_dict(self):
        return {
            'format': self.format,
            'source_label': self.source_label,
            'lines': [l.to_dict() for l in self.lines],
            'warnings': self.warnings,
            'total_market_value': self.total_market_value,
        }


# ─── Heuristique par ligne ───────────────────────────────────────────────────

def _heuristic_map_numbers(numbers: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float], float]:
    """A partir d'une liste de nombres extraits autour d'un ISIN, tente de
    mapper (quantity, unit_price, market_value) par coherence qty*prix~=valo.

    Retourne (qty, unit_price, market_value, confidence 0-1).

    Strategie :
    - Filtre les valeurs absurdes (<1e-6 ou >1e12).
    - La market_value est typiquement le nombre le plus grand.
    - Quantity est un petit entier (1-10000 en general).
    - Unit_price est intermediaire.
    - On teste plusieurs triplets et on prend celui qui minimise
      |qty * unit_price - market_value| / market_value.
    """
    clean = sorted((n for n in numbers if 1e-6 < abs(n) < 1e12), reverse=True)
    if not clean:
        return None, None, None, 0.0

    if len(clean) == 1:
        # Un seul nombre : probablement la valorisation
        return None, None, clean[0], 0.2

    best = None
    best_err = float('inf')
    # Essaie tous les triplets (mv, prix, qty) ordonnes de maniere decroissante
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
                # Privilegie qty raisonnable, price raisonnable
                if 0.01 <= qty <= 1e7 and 0.01 <= price <= 1e6 and err < best_err:
                    best_err = err
                    best = (qty, price, mv)

    if best and best_err < 0.03:
        # Tolerance 3% : ajuste pour arrondis et frais
        return best[0], best[1], best[2], max(0.5, 1.0 - best_err * 10)

    # Fallback : deux nombres → (qty, valo) ou (prix, valo)
    if len(clean) >= 2:
        mv = clean[0]
        other = clean[1]
        # Si l'autre nombre divise bien mv, c'est la qty
        if 1e-6 < other < 1e7 and mv > 0:
            return None, None, mv, 0.3
    return None, None, clean[0] if clean else None, 0.2


def _line_has_isin(s: str) -> Optional[str]:
    m = ISIN_RE.search(s)
    if not m:
        return None
    isin = m.group(1)
    return isin if _isin_luhn_ok(isin) else None


def _guess_name(text: str, isin: str) -> Optional[str]:
    """Extrait un libelle probable autour de l'ISIN (reste avant ISIN, nettoye)."""
    before = text.split(isin)[0].strip()
    # Enleve les nombres de fin de libelle
    while before and NUMBER_RE.fullmatch(before.split()[-1] if before.split() else ''):
        before = ' '.join(before.split()[:-1]).strip()
    # Trim, deduplique espaces, max 120 chars
    name = re.sub(r'\s+', ' ', before).strip(' -|:;')
    return name[:120] if len(name) > 2 else None


# ─── Parsers ─────────────────────────────────────────────────────────────────

def _parse_tables(pdf) -> List[DetectedLine]:
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
                isin = _line_has_isin(joined)
                if not isin:
                    continue
                # Extrait les nombres de toutes les cellules non-ISIN
                numbers = []
                name_parts = []
                for c in cells:
                    if isin in c:
                        continue
                    if ISIN_RE.search(c):
                        continue
                    nums = _extract_numbers(c)
                    if nums:
                        numbers.extend(nums)
                    else:
                        name_parts.append(c)
                qty, price, mv, conf = _heuristic_map_numbers(numbers)
                name = ' '.join(p for p in name_parts if len(p) > 1)[:120] or None
                results.append(DetectedLine(
                    isin=isin, name=name, quantity=qty, unit_price=price,
                    market_value=mv,
                    raw=joined, confidence=conf + 0.1,  # bonus : source tableau
                    source='table',
                ))
    return results


def _parse_text_lines(pdf) -> List[DetectedLine]:
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
            isin = _line_has_isin(line)
            if not isin:
                continue
            # Context : ligne + ligne suivante (certains exports mettent qty/valo en dessous)
            numbers = _extract_numbers(line.replace(isin, ''))
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


def _deduplicate(lines: List[DetectedLine]) -> List[DetectedLine]:
    """Fusionne les lignes dupliquees (meme ISIN), garde la plus confiante."""
    best = {}
    for l in lines:
        k = l.isin
        if k not in best or l.confidence > best[k].confidence:
            best[k] = l
    return list(best.values())


# ─── API publique ────────────────────────────────────────────────────────────

def parse_pdf(file_bytes: bytes) -> ParseResult:
    """Point d'entree : renvoie un ParseResult pret a afficher en preview."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError('pdfplumber non installé')

    result = ParseResult(format='generic', source_label='Format inconnu')

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        # Extraction texte global pour fingerprint
        global_text = ''
        for page in pdf.pages[:3]:  # les 3 premieres pages suffisent pour fingerprinting
            try:
                global_text += (page.extract_text() or '') + '\n'
            except Exception:
                pass
        fmt = detect_format(global_text)
        result.format = fmt
        result.source_label = _format_label(fmt)

        # 1. Couche tableaux
        table_lines = _parse_tables(pdf)
        # 2. Couche texte (fallback et complement)
        text_lines = _parse_text_lines(pdf)

    # Fusion + deduplication
    merged = _deduplicate(table_lines + text_lines)
    # Tri par confiance decroissante pour afficher les plus sures en haut
    merged.sort(key=lambda l: (-l.confidence, l.isin))

    result.lines = merged
    result.total_market_value = sum(l.market_value or 0 for l in merged)

    if not merged:
        result.warnings.append('Aucune ligne détectée. Vérifiez que le PDF n\'est pas un scan image, ou saisissez manuellement.')
    else:
        low_conf = sum(1 for l in merged if l.confidence < 0.5)
        if low_conf:
            result.warnings.append(f'{low_conf} ligne(s) avec faible confiance : vérifiez les quantités et valorisations.')

    return result


def _format_label(code: str) -> str:
    labels = {
        'boursorama_pea':   'Boursorama — PEA',
        'boursorama_cto':   'Boursorama — CTO',
        'fortuneo_pea':     'Fortuneo — PEA',
        'bourse_direct':    'Bourse Direct',
        'binck':            'Binck / Saxo',
        'linxea_av':        'Linxea — Assurance-vie',
        'spirica_av':       'Spirica — Assurance-vie',
        'suravenir_av':     'Suravenir — Assurance-vie',
        'generali_av':      'Generali — Assurance-vie',
        'yomoni_av':        'Yomoni',
        'nalo_av':          'Nalo',
        'swisslife_av':     'SwissLife',
        'credit_agricole':  'Crédit Agricole',
        'bnp':              'BNP Paribas',
        'societe_generale': 'Société Générale',
        'generic':          'Format non reconnu — parser générique',
    }
    return labels.get(code, 'Format inconnu')
