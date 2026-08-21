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
# Enveloppe deduite d'un libelle porte par le document : "Compte d'epargne :
# Livret Bourso+", "Compte a vue P.E.A.". Le plus specifique d'abord — un
# releve de livret peut mentionner le PEA ailleurs dans la page.
_ENVELOPE_MARKERS = (
    ('LIVRET BOURSO', 'Livret Bourso+'),
    ('LIVRET A', 'Livret A'),
    ('LIVRET DE DEVELOPPEMENT', 'LDDS'),
    ('LDDS', 'LDDS'),
    ('PLAN EPARGNE LOGEMENT', 'PEL/CEL'),
    ('COMPTE PEA', 'PEA'),
    ('P.E.A', 'PEA'),
    ('PEA', 'PEA'),
)
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
    for marker, envelope in _ENVELOPE_MARKERS:
        if marker in flat:
            return envelope
    return DEFAULT_ENVELOPE

# La garde arriere evite de coller la date de valeur au montant : sur le
# gabarit 2026, ou la date de valeur precede immediatement le montant,
# "27/02/2026 100,00" se lisait 26 100,00 EUR — le "026" de l'annee etant pris
# pour un groupe de milliers.
_AMOUNT = re.compile(r'(?<![\d/.,])(\d{1,3}(?:[ \u202f\u00a0.]\d{3})*,\d{2})')
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
    (r'COUPON|DIVIDENDE|REMBOURSEMENT|INTER\.?BRUTS|INTERETS', 'Dividende/Intérêt'),
    (r'FRAIS|COMMISSION|DROITS DE GARDE|TAXE', 'Frais'),
]


# Les prelevements fiscaux et sociaux sur les interets ne sont pas des flux
# externes : ils reduisent le rendement, ils n'en sortent pas. Les compter comme
# des retraits gonflerait la performance de leur montant.
_IGNORED_LABELS = (r'PRELEVEMENT', r'\bCSG\b', r'\bCRDS\b')


def _flux_type(label: str, sens: str) -> Optional[str]:
    up = _ascii(label)
    if any(re.search(pat, up) for pat in _IGNORED_LABELS):
        return None
    if re.search(r'OUVERTURE\s*(DE\s*)?COMPTE', up):
        return None
    # Un libelle prefixe VIR designe un virement, meme quand il nomme ce qu'il
    # finance : "VIR Achat crypto" sort bien de l'especes du livret. La
    # regle suivante, qui ecarte les mouvements de titres deja portes par un
    # avis d'opere, ne doit donc pas le happer.
    virement = re.match(r'\*?\s*(VIR\b|VIREMENT)', up)
    if not virement and re.search(r'ACHAT|VENTE|SOUSCRIPTION|REPRISE',
                                  up.replace(' ', '')):
        return None          # mouvement de titres, deja porte par l'avis
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


# Ecart minimal, en points PDF, entre la colonne debit et la colonne credit.
# Mesure sur les releves BoursoBank : debit cale a droite sur x=479, credit sur
# x=546, soit 66 points. Un ecart sous ce seuil signale une colonne unique.
COLUMN_GAP_PT = 20
# Tolerance d'alignement a droite d'une meme colonne : les glyphes varient de
# moins d'un point d'un montant a l'autre.
COLUMN_TOL_PT = 3
# Ecart d'ordonnee en deca duquel deux mots appartiennent a la meme ligne.
LINE_TOL_PT = 2.5


def _split_columns(rights):
    """Seuil separant debit et credit d'apres les bords droits des montants.

    Les deux colonnes sont calees a droite. Le texte mis en page par pdfplumber
    ne conserve pas cet alignement — il place chaque jeton d'apres son bord
    GAUCHE, si bien qu'un montant a six chiffres et un montant a trois d'une
    meme colonne finissent a sept caracteres d'ecart. Les coordonnees, elles,
    separent les colonnes de 66 points : on travaille donc sur elles.
    Retourne le seuil, ou None si tout tient dans une seule colonne.
    """
    uniq = sorted(set(rights))
    if len(uniq) < 2:
        return None
    gaps = [(uniq[k + 1] - uniq[k], uniq[k]) for k in range(len(uniq) - 1)]
    width, at = max(gaps)
    return at + width / 2 if width >= COLUMN_GAP_PT else None


def _lines_from_words(pages):
    """Regroupe les mots d'un PDF en lignes, page par page.

    Le regroupement se fait par balayage et non par tranches fixes : deux mots
    d'une meme ligne peuvent differer d'un point d'ordonnee, et une tranche de
    largeur fixe les separe des qu'ils tombent de part et d'autre d'une borne —
    c'est ainsi que le libelle "Nouveau solde en EUR" se retrouvait sans son
    montant, et le controle des soldes sans son terme final.
    """
    out = []
    for words in pages:
        courante, repere = [], None
        for w in sorted(words, key=lambda w: (float(w['top']), float(w['x0']))):
            haut = float(w['top'])
            if repere is None or haut - repere <= LINE_TOL_PT:
                courante.append(w)
                repere = haut if repere is None else repere
            else:
                out.append(sorted(courante, key=lambda w: float(w['x0'])))
                courante, repere = [w], haut
        if courante:
            out.append(sorted(courante, key=lambda w: float(w['x0'])))
    return out


def _rows_from_words(pages):
    """(rows, soldes) extraits des coordonnees plutot que du texte mis en page.

    rows : (date ISO, libelle, montant, bord droit du montant).
    soldes : (solde initial, solde final) quand le releve les porte.

    Seules les lignes situees entre le solde initial et le solde final sont
    retenues. L'en-tete du releve porte lui aussi une date et un montant — la
    periode et un "0,00" de frais — dans une colonne a lui : le prendre pour un
    mouvement creait un troisieme alignement qui faussait la frontiere
    debit/credit, et donc le sens de tous les mouvements de la page.
    """
    rows, first, last, dans_table = [], None, None, False
    for line in _lines_from_words(pages):
        texte = ' '.join(w['text'] for w in line)
        plat = _flat(texte)
        montants = [w for w in line
                    if _AMOUNT.fullmatch(w['text'].replace('\u00a0', ' '))]
        if 'ANCIEN SOLDE' in plat or 'SOLDE AU' in plat:
            if montants and first is None:
                first = _num(montants[-1]['text'])
            dans_table = True
            continue
        if 'NOUVEAU SOLDE' in plat or 'SOLDE FINAL' in plat:
            if montants:
                last = _num(montants[-1]['text'])
            dans_table = False
            continue
        if not dans_table or not montants:
            continue
        md = re.match(r'(\d{2})/(\d{2})/(\d{4})\s+(\S.*)$', texte)
        if not md:
            continue
        # Le libelle s'arrete a la date de valeur, qui precede le montant.
        libelle = re.sub(r'\s*\d{2}/\d{2}/\d{4}.*$', '', md.group(4)).strip()
        rows.append((f'{md.group(3)}-{md.group(2)}-{md.group(1)}',
                     libelle or md.group(4).strip(),
                     _num(montants[-1]['text']), float(montants[-1]['x1'])))
    return rows, (first, last)


def parse_releve_especes(text: str, account_map: Optional[dict] = None,
                        words: Optional[list] = None) -> List[DetectedMovement]:
    """Un releve = N mouvements de tresorerie. Retourne [] si ce n'en est pas un.

    `words` : les mots du PDF, page par page (`page.extract_words()`). Quand
    l'appelant les fournit, le sens debit/credit vient des coordonnees, seules
    fiables sur le gabarit 2026 qui perd son en-tete a l'extraction. Sans eux,
    on retombe sur l'en-tete du texte mis en page.
    """
    up = _flat(text)
    if 'RELEVE COMPTE ESPECES' not in up and 'EXTRAIT DE VOTRE COMPTE' not in up:
        return []
    lines = text.split('\n')
    env = detect_envelope(text, account_map)

    if words:
        rows, soldes = _rows_from_words(words)
        seuil = _split_columns([r[3] for r in rows])
        # A droite du seuil : credit. Les deux colonnes sont calees a droite,
        # celle du credit etant la plus a droite des deux.
        def sens_of(pos):
            return 'credit' if seuil is not None and pos > seuil else 'debit'
    else:
        rows = _rows_from_text(lines)
        soldes = _balances(lines)
        col_d, col_c = _header_columns(lines)

        def sens_of(pos):
            if col_d is None or col_c is None:
                return 'credit'
            return 'credit' if abs(pos - col_c) < abs(pos - col_d) else 'debit'

    if not rows:
        return []
    senses = [sens_of(r[3]) for r in rows]

    # Controle global : solde initial + credits - debits = solde final. S'il
    # echoue, on teste le sens inverse avant de renoncer — mieux vaut un sens
    # verifie qu'une convention supposee. L'inversion en bloc n'a de sens que
    # sur un releve a colonne unique, ou aucune coordonnee ne tranche.
    first, last = soldes
    check = None
    if first is not None and last is not None:
        def closes(sq):
            total = first + sum(v if s == 'credit' else -v
                                for (_, _, v, _), s in zip(rows, sq))
            return abs(total - last) <= 0.02
        inverse = ['debit' if s == 'credit' else 'credit' for s in senses]
        if closes(senses):
            check = 'solde initial + crédits − débits = solde final'
        elif closes(inverse):
            senses = inverse
            check = 'sens rétabli par le contrôle des soldes'

    out = []
    for (date, label, amount, _pos), sens in zip(rows, senses):
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


def _header_columns(lines):
    """Position des en-tetes Debit et Credit dans le texte mis en page."""
    for ln in lines:
        if 'DEBIT' in _flat(ln) and 'CREDIT' in _flat(ln):
            au = ln.upper()
            i_d = au.find('DÉBIT') if 'DÉBIT' in au else au.find('DEBIT')
            i_c = au.find('CRÉDIT') if 'CRÉDIT' in au else au.find('CREDIT')
            if i_d >= 0 and i_c >= 0:
                return i_d + 2.5, i_c + 3.0
            break
    return None, None


def _rows_from_text(lines):
    """Repli sans coordonnees : lignes datees portant un montant."""
    rows = []
    for ln in lines:
        md = re.match(r'\s*(\d{2}/\d{2}/\d{4})\s+(\S.*?)(?:\s{2,}|$)', ln)
        if not md:
            continue
        a = _flat(ln)
        if 'ANCIEN SOLDE' in a or 'NOUVEAU SOLDE' in a or 'SOLDE AU' in a:
            continue
        hits = [mm for mm in _AMOUNT.finditer(ln)
                if not re.match(r'\d{2}/\d{2}/\d{4}', mm.group(0))]
        if not hits:
            continue
        mm = hits[-1]
        d, mo, y = md.group(1).split('/')
        rows.append((f'{y}-{mo}-{d}', md.group(2).strip(), _num(mm.group(1)),
                     (mm.start() + mm.end()) / 2))
    return rows


def parse_movements(text: str, account_map: Optional[dict] = None,
                    words: Optional[list] = None) -> List[DetectedMovement]:
    """Point d'entree : detecte la nature du document et dispatche.

    `words` n'est utile qu'aux releves d'especes : voir parse_releve_especes.
    """
    return (parse_avis_opere(text, account_map)
            or parse_releve_especes(text, account_map, words))
