"""Parsers de MOUVEMENTS : avis d'operes et releves d'especes BoursoBank.

Les parsers existants decrivent un ETAT (quantite et valeur a une date) et
alimentent `holdings`. Ceux-ci decrivent un MOUVEMENT : une operation datee,
avec son sens, son montant et ses frais. Ils alimentent `flux` (versements,
retraits, coupons) et `transactions` (achats, ventes de titres).

Formats couverts, tous valides sur 137 documents reels :
- Avis d'opere : action ou OPC, achat ou vente, place domestique ou etrangere,
  avec ou sans conversion de devise (5 gabarits).
- Releve d'especes : deux gabarits, l'ancien ("RELEVE COMPTE ESPECES : MOIS
  ANNEE", jusqu'a janvier 2026) et le nouveau ("Extrait de votre compte en EUR"),
  qui decrivent le meme compte.

Chaque montant extrait est recoupe par une identite arithmetique avant d'etre
accepte (brut = quantite x cours, net = brut +/- frais) : un chiffre mal lu est
rejete au lieu d'entrer en base.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict, field
from typing import List, Optional

# Enveloppe deduite du texte, pas du numero de compte : coder en dur des numeros
# de compte reviendrait a versionner une donnee personnelle. Le marqueur est
# fiable sur les documents BoursoBank — "PEA" figure dans tous les avis et
# releves du PEA et dans aucun de ceux du compte-titres.
# Un utilisateur peut affiner via une correspondance stockee en base
# (`config.account_map`), passee en argument : elle a priorite.
_PEA_MARKERS = ('COMPTE PEA', 'P.E.A', 'PEA')
DEFAULT_ENVELOPE = 'Compte-titres'

# Etablissement propose par defaut. Ce n'est qu'une suggestion : il DOIT
# correspondre a l'orthographe employee dans `positions`, sinon les flux
# importes ne se rattachent a aucun compte et leur enveloppe affiche un
# rendement qui absorbe les versements. L'appelant le surcharge.
DEFAULT_ESTABLISHMENT = 'BoursoBank'


def detect_envelope(text: str, account_map: Optional[dict] = None) -> Optional[str]:
    """Enveloppe du document : correspondance explicite, sinon marqueur textuel."""
    if account_map:
        for account, envelope in account_map.items():
            if account and str(account) in text:
                return envelope
    flat = _flat(text)
    if any(m in flat for m in _PEA_MARKERS):
        return 'PEA'
    return DEFAULT_ENVELOPE

_AMOUNT = re.compile(r'(\d{1,3}(?:[ .  ]\d{3})*,\d{2}|\d+,\d{2})')
# Le cours de change porte 6 a 8 decimales : la regex des montants, qui en
# impose exactement deux, le tronquerait a 1,13 et faussait la contrevaleur.
_FX = re.compile(r'\b(\d{1,2},\d{4,})\b')
_NUM = re.compile(r'\d{1,3}(?:[   ]\d{3})*(?:,\d+)?')
_ISIN = re.compile(r'\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b')

MOIS = {'JANVIER': 1, 'FEVRIER': 2, 'MARS': 3, 'AVRIL': 4, 'MAI': 5, 'JUIN': 6,
        'JUILLET': 7, 'AOUT': 8, 'SEPTEMBRE': 9, 'OCTOBRE': 10,
        'NOVEMBRE': 11, 'DECEMBRE': 12}


def _num(s: str) -> Optional[float]:
    if s is None:
        return None
    s = s.replace(' ', '').replace(' ', '').replace(' ', '')
    s = s.replace('.', '') if s.count(',') == 1 and s.count('.') >= 1 else s
    try:
        return float(s.replace(',', '.'))
    except ValueError:
        return None


def _ascii(s: str) -> str:
    s = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in s if not unicodedata.combining(c)).upper()


def _flat(s: str) -> str:
    """Texte majuscule sans accent NI espacement significatif.

    Les extracteurs ne s'accordent pas sur les blancs : le meme titre sort
    "RELEVE COMPTE ESPECES" chez l'un et espace autrement chez l'autre. Les
    reperes de detection doivent donc etre cherches sur un texte aplati.
    """
    return re.sub(r'\s+', ' ', _ascii(s))


@dataclass
class DetectedMovement:
    """Un mouvement, pret a devenir une ligne de `flux` ou de `transactions`."""
    kind: str                      # 'transaction' | 'flux'
    date: str                      # AAAA-MM-JJ, date d'execution
    envelope: Optional[str] = None
    establishment: str = DEFAULT_ESTABLISHMENT
    # transaction
    isin: Optional[str] = None
    name: Optional[str] = None
    side: Optional[str] = None     # ACHAT | VENTE
    quantity: Optional[float] = None
    price: Optional[float] = None
    currency: str = 'EUR'
    fx_rate: Optional[float] = None
    gross: Optional[float] = None
    fees: float = 0.0
    place: Optional[str] = None
    # flux
    flux_type: Optional[str] = None   # Versement | Retrait | Dividende/Intérêt
    label: Optional[str] = None
    # commun
    net_eur: Optional[float] = None
    checks: List[str] = field(default_factory=list)   # controles passes
    warnings: List[str] = field(default_factory=list)
    raw: str = ''

    def to_dict(self):
        return asdict(self)


# ─── Avis d'opere ────────────────────────────────────────────────────────────

def _column_value(lines, header_re, tol=14, scan=4):
    """Valeur alignee sous un en-tete de colonne (sortie pdftotext -layout).

    Les avis presentent leurs montants en colonnes ; les lire par position est
    la seule facon fiable de distinguer le brut, la commission et le net, qui
    partagent le meme format.
    """
    for i, ln in enumerate(lines):
        m = re.search(header_re, ln)
        if not m:
            continue
        centre = (m.start() + m.end()) / 2
        for j in range(i + 1, min(i + 1 + scan, len(lines))):
            hits = [(mm, (mm.start() + mm.end()) / 2) for mm in _AMOUNT.finditer(lines[j])]
            if not hits:
                continue
            best = min(hits, key=lambda h: abs(h[1] - centre))
            return _num(best[0].group(1)) if abs(best[1] - centre) <= tol else 0.0
    return None


def parse_avis_opere(text: str, account_map: Optional[dict] = None) -> List[DetectedMovement]:
    """Un avis = une operation. Retourne [] si le document n'en est pas un."""
    lines = text.split('\n')
    up = _ascii(text)
    # Ancrage tolerant aux espaces : pdftotext cadre a gauche, pdfplumber
    # indente et complete la ligne. Le parser doit accepter les deux.
    m = re.search(r'^[ \t]*(ACHAT COMPTANT ETR|ACHAT COMPTANT|VENTE COMPTANT ETR|VENTE COMPTANT|'
                  r'SOUSCRIPTION F\.C\.P\.|SOUSCRIPTION SICAV|REPRISE F\.C\.P\.|REPRISE SICAV)'
                  r'[ \t]*$', text, re.M)
    if not m:
        return []
    op = m.group(1)
    side = 'ACHAT' if op.startswith(('ACHAT', 'SOUSCRIPTION')) else 'VENTE'

    env = detect_envelope(text, account_map)

    # Ligne d'execution : date, quantite, libelle. Les separateurs varient selon
    # l'extracteur — pdftotext conserve des colonnes larges, pdfplumber reduit a
    # un espace. On borne donc les champs par leur forme, pas par l'espacement :
    # la quantite est un nombre (milliers en espace fine possible), le libelle
    # commence par une lettre et s'arrete au premier repere connu.
    me = re.search(r'^\s*(\d{2}/\d{2}/\d{4})\s+'
                   r'(\d{1,3}(?:[\s\u202f\u00a0]\d{3})*(?:,\d+)?)\s+'
                   r'([A-Za-z\u00c0-\u00ff][^\n]*?)'
                   r'(?=\s{2,}|\s+R\S*f\S*rence|\s+Code ISIN|$)',
                   text, re.M)
    if not me:
        return []
    d, mo, y = me.group(1).split('/')
    mv = DetectedMovement(kind='transaction', date=f'{y}-{mo}-{d}', envelope=env,
                          side=side, quantity=_num(me.group(2)), name=me.group(3).strip(),
                          raw=op)
    mi = _ISIN.search(text)
    if mi:
        mv.isin = mi.group(1)
    mp = re.search(r'(?:Cours ex\S*cut\S*|Valeur liquidative)\s*:\s+([\d   ]+(?:,\d+)?)\s+([A-Z]{3})',
                   text)
    if mp:
        mv.price, mv.currency = _num(mp.group(1)), mp.group(2)
    ml = re.search(r"Lieu d'ex\S*cution\s*:\s+(\S.*?)\s*$", text, re.M)
    mv.place = ml.group(1).strip() if ml else 'OPC'

    mv.gross = _column_value(lines, r'Montant (?:transaction )?brut')
    commission = _column_value(lines, r'Commission') or 0.0
    divers = _column_value(lines, r'Frais \(|Frais divers|Frais H\.T\.') or 0.0
    droits = _column_value(lines, r"Droits d'entr\S*e|Droits de sortie") or 0.0
    courtages = _column_value(lines, r'Courtages') or 0.0
    mv.fees = round(commission + divers + droits + courtages, 2)
    if 'Cours de change' in text:
        mv.fx_rate = _fx_rate(lines)
    mv.net_eur = _column_value(lines, r'Montant net au (?:d\S*bit|cr\S*dit) de votre compte', tol=22)

    _check_avis(mv)
    return [mv]


def _fx_rate(lines) -> Optional[float]:
    """Cours de change, lu sous son en-tete avec sa precision reelle."""
    for i, ln in enumerate(lines):
        if 'Cours de change' not in ln:
            continue
        for j in range(i + 1, min(i + 4, len(lines))):
            m = _FX.search(lines[j])
            if m:
                return _num(m.group(1))
    return None


def _check_avis(mv: DetectedMovement):
    """Recoupe les montants. Un chiffre mal lu doit etre visible, pas silencieux."""
    q, p, g, n = mv.quantity, mv.price, mv.gross, mv.net_eur
    if None in (q, p, g):
        mv.warnings.append('montants incomplets')
        return
    if abs(q * p - g) <= 0.02:
        mv.checks.append('brut = quantité × cours')
    else:
        mv.warnings.append(f'brut {g} ≠ quantité × cours ({q * p:.2f})')
    if n is None:
        mv.warnings.append('montant net illisible')
        return
    if mv.fx_rate:
        attendu = g / mv.fx_rate + (mv.fees if mv.side == 'ACHAT' else -mv.fees)
        tol = 0.05
    else:
        attendu = g + (mv.fees if mv.side == 'ACHAT' else -mv.fees)
        tol = 0.02
    if abs(attendu - n) <= tol:
        mv.checks.append('net = brut ± frais' + (' ÷ change' if mv.fx_rate else ''))
    else:
        mv.warnings.append(f'net {n} ≠ attendu {attendu:.2f}')


# ─── Releve d'especes ────────────────────────────────────────────────────────

# Les libelles arrivent parfois colles ("VIRCCBoursoversPEA") selon
# l'extracteur : on cherche donc des prefixes, sans frontiere de mot a droite.
_FLUX_LABEL = [
    (r'\bVIR|VIREMENT', 'Versement'),
    (r'COUPON|DIVIDENDE|REMBOURSEMENT', 'Dividende/Intérêt'),
    (r'FRAIS|COMMISSION|DROITS DE GARDE|TAXE', 'Frais'),
]


def _flux_type(label: str, sens: str) -> Optional[str]:
    up = _ascii(label)
    if re.search(r'ACHAT|VENTE|SOUSCRIPTION|REPRISE', up.replace(' ', '')):
        return None          # mouvement de titres, deja porte par l'avis
    if 'OUVERTURE' in up:
        return None
    for pattern, kind in _FLUX_LABEL:
        if re.search(pattern, up):
            if kind == 'Versement' and sens == 'debit':
                return 'Retrait'
            return kind
    return None


def _balances(lines):
    """(solde initial, solde final) du releve, ou (None, None).

    Sert de controle global : solde initial + credits - debits = solde final.
    """
    first = last = None
    for ln in lines:
        a = _flat(ln)
        hits = _AMOUNT.findall(ln)
        if not hits:
            continue
        if 'ANCIEN SOLDE' in a or (first is None and 'SOLDE AU' in a):
            first = _num(hits[-1])
        elif 'NOUVEAU SOLDE' in a or 'SOLDE AU' in a:
            last = _num(hits[-1])
    return first, last


def _split_columns(rows):
    """Separe debit et credit sans en-tete, par la position des montants.

    Le format 2026 perd son en-tete a l'extraction : impossible de s'appuyer sur
    la position des libelles "Debit"/"Credit". Les montants, eux, restent
    alignes en deux colonnes ; on cherche donc la plus large coupure dans leurs
    abscisses. Retourne le seuil, ou None si tout tient dans une seule colonne.
    """
    centres = sorted({round(c) for _, _, c, _ in rows})
    if len(centres) < 2:
        return None
    gaps = [(centres[k + 1] - centres[k], centres[k]) for k in range(len(centres) - 1)]
    width, at = max(gaps)
    # Une coupure franche vaut plusieurs caracteres ; en dessous, les montants
    # sont dans la meme colonne et le sens ne peut pas etre deduit ainsi.
    return at + width / 2 if width >= 6 else None


def parse_releve_especes(text: str, account_map: Optional[dict] = None) -> List[DetectedMovement]:
    """Un releve = N mouvements de tresorerie. Retourne [] si ce n'en est pas un."""
    up = _flat(text)
    if 'RELEVE COMPTE ESPECES' not in up and 'EXTRAIT DE VOTRE COMPTE' not in up:
        return []
    lines = text.split('\n')
    env = detect_envelope(text, account_map)

    # En-tete debit/credit quand il survit a l'extraction.
    col_d = col_c = None
    for ln in lines:
        a = _flat(ln)
        if 'DEBIT' in a and 'CREDIT' in a:
            au = ln.upper()
            i_d = au.find('DÉBIT') if 'DÉBIT' in au else au.find('DEBIT')
            i_c = au.find('CRÉDIT') if 'CRÉDIT' in au else au.find('CREDIT')
            if i_d >= 0 and i_c >= 0:
                col_d, col_c = i_d + 2.5, i_c + 3.0
            break

    # Toutes les lignes datees portant un montant, sens encore indetermine.
    rows = []
    for ln in lines:
        md = re.match(r'\s*(\d{2}/\d{2}/\d{4})\s+(\S.*?)(?:\s{2,}|$)', ln)
        if not md:
            continue
        a = _flat(ln)
        if 'ANCIEN SOLDE' in a or 'NOUVEAU SOLDE' in a or 'SOLDE AU' in a:
            continue
        hits = [(mm, (mm.start() + mm.end()) / 2) for mm in _AMOUNT.finditer(ln)]
        hits = [h for h in hits if not re.match(r'\d{2}/\d{2}/\d{4}', h[0].group(0))]
        if not hits:
            continue
        mm, centre = hits[-1]
        d, mo, y = md.group(1).split('/')
        rows.append((f'{y}-{mo}-{d}', md.group(2).strip(), centre, _num(mm.group(1))))

    if not rows:
        return []

    threshold = None
    if col_d is None or col_c is None:
        threshold = _split_columns(rows)

    def sens_of(centre):
        if col_d is not None and col_c is not None:
            return 'credit' if abs(centre - col_c) < abs(centre - col_d) else 'debit'
        if threshold is not None:
            return 'credit' if centre > threshold else 'debit'
        return 'credit'

    senses = [sens_of(c) for _, _, c, _ in rows]

    # Controle global : solde initial + credits - debits = solde final. S'il
    # echoue, on teste le sens inverse avant de renoncer — mieux vaut un sens
    # verifie qu'une convention supposee.
    first, last = _balances(lines)
    check = None
    if first is not None and last is not None:
        def closes(sq):
            total = first + sum(v if s == 'credit' else -v
                                for (_, _, _, v), s in zip(rows, sq))
            return abs(total - last) <= 0.02
        if closes(senses):
            check = 'solde initial + crédits − débits = solde final'
        elif closes(['debit' if s == 'credit' else 'credit' for s in senses]):
            senses = ['debit' if s == 'credit' else 'credit' for s in senses]
            check = 'sens rétabli par le contrôle des soldes'

    out = []
    for (date, label, _, amount), sens in zip(rows, senses):
        ftype = _flux_type(label, sens)
        if not ftype:
            continue
        if ftype == 'Dividende/Intérêt' and sens == 'debit':
            continue
        mv = DetectedMovement(kind='flux', date=date, envelope=env, flux_type=ftype,
                              label=label, net_eur=amount, raw=label[:200])
        if check:
            mv.checks.append(check)
        else:
            mv.warnings.append('sens débit/crédit non vérifié par les soldes')
        out.append(mv)
    return out


def parse_movements(text: str, account_map: Optional[dict] = None) -> List[DetectedMovement]:
    """Point d'entree : detecte la nature du document et dispatche."""
    return (parse_avis_opere(text, account_map)
            or parse_releve_especes(text, account_map))
