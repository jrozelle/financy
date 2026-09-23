"""Releves de compte bancaire d'une entite (SCI, holding) : Qonto, Credit Agricole.

Meme principe que les tableaux d'amortissement : un releve se VERIFIE avant
d'etre cru. Solde initial + credits - debits doit redonner le solde final
imprime, et les totaux lus doivent egaler ceux du releve. Une ligne mal lue
(un debit pris pour un credit, un montant coupe en deux mots) fait echouer la
verification au lieu de fausser la tresorerie en silence.

Chaque operation porte un montant SIGNE : positif a l'entree, negatif a la
sortie.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

MOIS = {m: i for i, m in enumerate(
    ['janvier', 'fevrier', 'mars', 'avril', 'mai', 'juin', 'juillet', 'aout',
     'septembre', 'octobre', 'novembre', 'decembre'], start=1)}


@dataclass
class Operation:
    date: str          # AAAA-MM-JJ
    libelle: str
    montant: float     # signe


@dataclass
class Releve:
    banque: str
    compte: str
    debut: str
    fin: str
    solde_initial: float
    solde_final: float
    operations: list = field(default_factory=list)
    entete: str = ''       # debut du texte : le titulaire du compte y figure


class ReleveIllisible(ValueError):
    pass


def _nombre_fr(s):
    return float(s.replace(' ', '').replace(' ', '').replace('.', '').replace(',', '.'))


def _sans_accents(s):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


# ─── Qonto ───────────────────────────────────────────────────────────────────

_Q_PERIODE = re.compile(r'Du (\d{2})/(\d{2})/(\d{4}) au (\d{2})/(\d{2})/(\d{4})')
_Q_SOLDE = re.compile(r'Solde au (\d{2})/(\d{2}) ([+-]) ([\d.]+) EUR')
_Q_TOTAL = re.compile(r'^(Entrées|Sorties) ([+-]) ([\d.]+) EUR')
_Q_LIGNE = re.compile(r'^(\d{2})/(\d{2}) (.+?) ([+-]) ([\d.]+) EUR$')
_Q_IBAN = re.compile(r'IBAN: ?(FR[\d ]+)')


def _qonto(texte):
    per = _Q_PERIODE.search(texte)
    if not per:
        raise ReleveIllisible('Période du relevé Qonto introuvable.')
    d0 = date(int(per[3]), int(per[2]), int(per[1]))
    d1 = date(int(per[6]), int(per[5]), int(per[4]))
    soldes = [(-1 if s[2] == '-' else 1) * float(s[3]) for s in _Q_SOLDE.findall(texte)]
    if len(soldes) < 2:
        raise ReleveIllisible('Soldes du relevé Qonto introuvables.')
    iban = _Q_IBAN.search(texte)
    rel = Releve('Qonto', (iban[1].replace(' ', '')[-4:] if iban else ''), d0.isoformat(), d1.isoformat(),
                 soldes[0], soldes[1])
    totaux = {}
    derniere = None
    en_tete = True
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if ligne.startswith('Toutes les cartes'):
            # Pied de page : plus aucune operation ni motif au-dela.
            en_tete = True
            derniere = None
            continue
        t = _Q_TOTAL.match(ligne)
        if t:
            totaux[t[1]] = float(t[3])
            continue
        if ligne.startswith('Date de valeur'):
            en_tete = False
            continue
        if en_tete:
            continue
        m = _Q_LIGNE.match(ligne)
        if m:
            annee = d1.year if int(m[2]) <= d1.month or d0.year == d1.year else d0.year
            derniere = Operation(date(annee, int(m[2]), int(m[1])).isoformat(), m[3].strip(),
                                 (-1 if m[4] == '-' else 1) * float(m[5]))
            rel.operations.append(derniere)
        elif derniere and ligne:
            # Ligne de detail : le motif du virement, precieux pour classer.
            if not re.match(r'^[A-Z0-9]{20,}$', ligne):
                derniere.libelle += ' — ' + ligne
            derniere = None if len(derniere.libelle) > 160 else derniere
    entrees = sum(o.montant for o in rel.operations if o.montant > 0)
    sorties = -sum(o.montant for o in rel.operations if o.montant < 0)
    if 'Entrées' in totaux and abs(entrees - totaux['Entrées']) > 0.005:
        raise ReleveIllisible(f'Qonto {rel.fin} : entrées lues {entrees:.2f}, relevé {totaux["Entrées"]:.2f}.')
    if 'Sorties' in totaux and abs(sorties - totaux['Sorties']) > 0.005:
        raise ReleveIllisible(f'Qonto {rel.fin} : sorties lues {sorties:.2f}, relevé {totaux["Sorties"]:.2f}.')
    return rel


# ─── Credit Agricole ─────────────────────────────────────────────────────────

_CA_ARRETE = re.compile(r"Date d['’]arrêté ?: ?(\d{1,2}) (\w+) (\d{4})")
_CA_COMPTE = re.compile(r'Compte Courant n° (\d+)')
_CA_LIGNE = re.compile(r'^(\d{2})\.(\d{2}) (\d{2})\.(\d{2}) (.+?) ((?:\d{1,3} )*\d{1,3},\d{2})$')
_CA_SOLDE = re.compile(r'(Ancien|Nouveau) solde (créditeur|débiteur) au (\d{2})\.(\d{2})\.(\d{4}) ((?:\d{1,3} )*\d{1,3},\d{2})')
_CA_TOTAL = re.compile(r'^Total des opérations ((?:\d{1,3} )*\d{1,3},\d{2})(?: ((?:\d{1,3} )*\d{1,3},\d{2}))?')
_PARASITES = '¨þ'


def _lignes_pdf(page):
    """Les lignes de la page, avec l'abscisse de fin de chacune : le debit et
    le credit ne se distinguent que par leur colonne."""
    # Regroupement a 2 points pres, pas par arrondi : un montant imprime un
    # point sous son libelle tombait sur une autre ligne des qu'un arrondi
    # les separait.
    mots = sorted((w for w in page.extract_words() if w['text'] not in _PARASITES),
                  key=lambda w: w['top'])
    rangs = []
    for w in mots:
        if rangs and w['top'] - rangs[-1][0] <= 2:
            rangs[-1][1].append(w)
        else:
            rangs.append((w['top'], [w]))
    lignes = []
    for _, ws in rangs:
        ws.sort(key=lambda w: w['x0'])
        lignes.append((' '.join(w['text'] for w in ws), ws[-1]['x1']))
    return lignes


def _credit_agricole(pages):
    lignes = [l for p in pages for l in _lignes_pdf(p)]
    texte = '\n'.join(t for t, _ in lignes)
    # L'arrete est imprime a cote de son libelle mais pas sur la meme ligne
    # de base : le texte brut de la page, lui, les accole.
    arr = _CA_ARRETE.search('\n'.join(p.extract_text() or '' for p in pages))
    if not arr:
        raise ReleveIllisible("Date d'arrêté du relevé Crédit Agricole introuvable.")
    fin = date(int(arr[3]), MOIS[_sans_accents(arr[2]).lower()], int(arr[1]))
    # La colonne Credit se repere a son en-tete ; les montants qui finissent
    # au-dela de son milieu sont des credits.
    seuil = None
    for p in pages:
        for w in p.extract_words():
            if w['text'] == 'Débit':
                seuil = w['x1'] + 30
                break
        if seuil:
            break
    if seuil is None:
        raise ReleveIllisible('Colonnes débit / crédit introuvables.')
    soldes = {}
    for m in _CA_SOLDE.finditer(texte):
        v = _nombre_fr(m[6]) * (-1 if m[2] == 'débiteur' else 1)
        soldes[m[1]] = (date(int(m[5]), int(m[4]), int(m[3])).isoformat(), v)
    if set(soldes) != {'Ancien', 'Nouveau'}:
        raise ReleveIllisible('Soldes du relevé Crédit Agricole introuvables.')
    compte = _CA_COMPTE.search(texte)
    rel = Releve('Crédit Agricole', compte[1][-4:] if compte else '', soldes['Ancien'][0],
                 soldes['Nouveau'][0], soldes['Ancien'][1], soldes['Nouveau'][1])
    derniere = None
    totaux = None
    for t, x1 in lignes:
        tot = _CA_TOTAL.match(t)
        if tot:
            totaux = [_nombre_fr(v) for v in tot.groups() if v]
            derniere = None
            continue
        m = _CA_LIGNE.match(t)
        if m:
            mois = int(m[2])
            annee = fin.year if mois <= fin.month else fin.year - 1
            montant = _nombre_fr(m[6]) * (1 if x1 > seuil else -1)
            derniere = Operation(date(annee, mois, int(m[1])).isoformat(), m[5].strip(), montant)
            rel.operations.append(derniere)
        elif derniere and re.search(r'[a-z]', t) and not t.startswith(('Nouveau solde', 'Les sommes')):
            # Motif sur la ligne suivante, precede d'une reference collee.
            # (« ALDE202412009119Activimmo ») : on coupe au dernier chiffre qui
            # precede une majuscule suivie d'une minuscule.
            derniere.libelle += ' — ' + re.sub(r'^[A-Z0-9]*\d(?=[A-Z][a-z])', '', t).strip()
            derniere = None
        else:
            derniere = None
    debits = -sum(o.montant for o in rel.operations if o.montant < 0)
    credits = sum(o.montant for o in rel.operations if o.montant > 0)
    if totaux is not None:
        attendus = sorted(totaux)
        lus = sorted(v for v in (debits, credits) if v)
        if len(attendus) != len(lus) or any(abs(a - b) > 0.005 for a, b in zip(attendus, lus)):
            raise ReleveIllisible(f'Crédit Agricole {rel.fin} : totaux lus {lus}, relevé {attendus}.')
    return rel


# ─── Point d'entree ──────────────────────────────────────────────────────────

def lire_releve(chemin_ou_flux) -> Releve:
    import pdfplumber
    with pdfplumber.open(chemin_ou_flux) as pdf:
        pages = pdf.pages
        texte = '\n'.join(p.extract_text() or '' for p in pages)
        if 'QNTOFRP' in texte or 'Qonto' in texte:
            rel = _qonto(texte)
        elif 'CREDIT AGRICOLE' in texte.upper():
            rel = _credit_agricole(pages)
        else:
            raise ReleveIllisible('Banque non reconnue : relevés Qonto et Crédit Agricole seulement.')
        rel.entete = texte[:1500]
    ecart = rel.solde_initial + sum(o.montant for o in rel.operations) - rel.solde_final
    if abs(ecart) > 0.005:
        raise ReleveIllisible(f'{rel.banque} {rel.fin} : solde initial + opérations ≠ solde final '
                              f'(écart {ecart:+.2f} €). Une ligne a été mal lue.')
    for o in rel.operations:
        o.montant = round(o.montant, 2)
    return rel
