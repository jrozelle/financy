"""
Types et utilitaires partages par tous les parsers (PDF, CSV).
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional

# ISIN standard : 2 lettres + 9 alphanum + 1 digit
ISIN_RE = re.compile(r'\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b')

# Nombres en format FR (1 234,56) ou EN (1,234.56) ou brut (1234.56)
NUMBER_RE = re.compile(
    r'-?\d{1,3}(?:[\s\u202f\u00a0]?\d{3})*(?:[.,]\d+)?|-?\d+(?:[.,]\d+)?'
)

# Empreintes de formats connus
# Ordre : les entrees les plus specifiques en premier.
FORMAT_FINGERPRINTS = [
    ('boursobank_attestation', ['ATTESTATION DE DETENTION'], ['BOURSOBANK', 'BOURSORAMA']),
    ('predica_detail',         ['ANAÉ'],                     ['DÉTAIL', 'DETAIL']),
    ('boursorama_pea',         ['BOURSORAMA'],               ['PEA']),
    ('boursorama_cto',         ['BOURSORAMA'],               ['CTO', 'COMPTE TITRES', 'COMPTE-TITRES']),
    ('boursorama',             ['BOURSORAMA'],               []),
    ('fortuneo_pea',           ['FORTUNEO'],                 ['PEA']),
    ('fortuneo',               ['FORTUNEO'],                 []),
    ('bourse_direct',          ['BOURSE DIRECT'],            []),
    ('binck',                  ['BINCK'],                    []),
    ('linxea_av',              ['LINXEA'],                   []),
    ('spirica_av',             ['SPIRICA'],                  []),
    ('suravenir_av',           ['SURAVENIR'],                []),
    ('generali_av',            ['GENERALI'],                 []),
    ('yomoni_av',              ['YOMONI'],                   []),
    ('nalo_av',                ['NALO'],                     []),
    ('swisslife_av',           ['SWISSLIFE'],                []),
    ('swisslife_av',           ['SWISS LIFE'],               []),
    ('credit_agricole',        ['CREDIT AGRICOLE'],          []),
    ('credit_agricole',        ['CRÉDIT AGRICOLE'],          []),
    ('bnp',                    ['BNP PARIBAS'],              []),
    ('societe_generale',       ['SOCIETE GENERALE'],         []),
    ('societe_generale',       ['SOCIÉTÉ GÉNÉRALE'],         []),
]

FORMAT_LABELS = {
    'boursobank_attestation': 'BoursoBank — Attestation PEA',
    'predica_detail':   'Crédit Agricole — Anaé (détail)',
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


# ─── Exceptions ──────────────────────────────────────────────────────────────

class PdfEncryptedError(RuntimeError):
    """PDF protege par mot de passe."""
    pass


class PdfImageScanError(RuntimeError):
    """PDF qui semble etre un scan image sans couche texte."""
    pass


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
    source: str = ''
    asset_class: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class ParseResult:
    format: str
    source_label: str
    lines: List[DetectedLine] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    total_market_value: float = 0.0
    needs_price_lookup: bool = False

    def to_dict(self):
        return {
            'format': self.format,
            'source_label': self.source_label,
            'lines': [l.to_dict() for l in self.lines],
            'warnings': self.warnings,
            'total_market_value': self.total_market_value,
            'needs_price_lookup': self.needs_price_lookup,
        }


# ─── Utilitaires ─────────────────────────────────────────────────────────────

def isin_luhn_ok(isin: str) -> bool:
    """Validation checksum Luhn d'un ISIN."""
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


def parse_number(s: str) -> Optional[float]:
    """Convertit un nombre au format FR/EN en float, ou None si impossible."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    cleaned = s.replace(' ', '').replace('\u00a0', '').replace('\u202f', '')
    if ',' in cleaned and '.' in cleaned:
        if cleaned.rfind(',') > cleaned.rfind('.'):
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        if re.search(r',\d{3}(?:\D|$)', cleaned) and cleaned.count(',') == 1 \
                and not re.search(r',\d{1,2}$', cleaned):
            cleaned = cleaned.replace(',', '')
        else:
            cleaned = cleaned.replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return None


def detect_format(text: str) -> str:
    """Renvoie le code du format detecte ou 'generic' si inconnu."""
    upper = text.upper()
    for code, must_have, optionals in FORMAT_FINGERPRINTS:
        if not all(kw.upper() in upper for kw in must_have):
            continue
        if optionals and not any(kw.upper() in upper for kw in optionals):
            continue
        return code
    return 'generic'


def format_label(code: str) -> str:
    return FORMAT_LABELS.get(code, 'Format inconnu')


def extract_numbers(text: str) -> List[float]:
    """Extrait tous les nombres valides d'un bout de texte."""
    out = []
    for m in NUMBER_RE.finditer(text):
        n = parse_number(m.group(0))
        if n is not None and not _looks_like_date_fragment(m.group(0)):
            out.append(n)
    return out


def line_has_isin(s: str) -> Optional[str]:
    """Retourne l'ISIN si la string en contient un valide, sinon None."""
    m = ISIN_RE.search(s)
    if not m:
        return None
    isin = m.group(1)
    return isin if isin_luhn_ok(isin) else None


def deduplicate(lines: List[DetectedLine]) -> List[DetectedLine]:
    """Fusionne les lignes dupliquees (meme ISIN), garde la plus confiante."""
    best = {}
    for l in lines:
        if l.isin not in best or l.confidence > best[l.isin].confidence:
            best[l.isin] = l
    return list(best.values())


def _looks_like_date_fragment(s: str) -> bool:
    return '/' in s or bool(re.match(r'^(19|20)\d{2}$', s.strip()))
