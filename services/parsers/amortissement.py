"""Tableaux d'amortissement de pret : une ligne par echeance.

Deux gabarits reconnus :

- Caisse d'Epargne (« PRET HABITAT », « P.H PRIMO ») : RANG | DATE |
  MONTANT A RECOUVRER | CAPITAL AMORTI | PART INTERETS | PART ACCESSOIRES |
  CAPITAL RESTANT DU | REPORT ECHEANCES | INTERETS REPORTES. L'extraction
  coupe les nombres d'espaces parasites (« 1 254,9 2 ») : les colonnes se
  lisent a la POSITION des mots, qu'on recolle par colonne.
- Arkea Banque Privee : N | DATE | AMORTISSEMENTS | INTERETS NORMAUX |
  INTERETS DIFFERES | ASSURANCES | TOTAL | RESTANT DU, milliers a point.

Le tableau se verifie lui-meme : d'une echeance a la suivante, le capital
restant du baisse exactement du capital amorti. Un tableau qui ne tombe pas
juste est refuse — un echeancier faux projetterait une dette fausse pendant
vingt ans, sans rien signaler.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional

_DATE = re.compile(r'(\d{2})/(\d{2})/(\d{4})')
TOLERANCE = 0.05          # arrondis au centime d'une ligne a l'autre


@dataclass
class Echeance:
    rang: int
    date: str                  # AAAA-MM-JJ
    capital: float             # capital amorti a cette echeance
    interets: float
    assurance: float
    crd: float                 # capital restant du APRES l'echeance


@dataclass
class Tableau:
    preteur: str
    libelle: str
    emprunteur: Optional[str]
    montant: Optional[float]
    taux: Optional[float]
    echeances: List[Echeance] = field(default_factory=list)
    controles: List[str] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d['debut'] = self.echeances[0].date if self.echeances else None
        d['fin'] = self.echeances[-1].date if self.echeances else None
        return d


def _num(txt):
    """'1.788,90' / '1 788,90' / '1788,9 0' -> 1788.9"""
    t = re.sub(r'[\s  ]', '', txt).replace('.', '').replace(',', '.')
    return float(t) if re.fullmatch(r'-?\d+(\.\d+)?', t) else None


def _iso(m):
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}'


def _lignes(page, tol=3.5):
    """Mots regroupes en lignes, a `tol` points pres : chez la Caisse
    d'Epargne, la date est imprimee un peu plus haut que les montants."""
    mots = sorted(page.extract_words(), key=lambda w: (w['top'], w['x0']))
    lignes = []
    for w in mots:
        if lignes and abs(w['top'] - lignes[-1][0]) <= tol:
            lignes[-1][1].append(w)
        else:
            lignes.append([w['top'], [w]])
    return [sorted(l, key=lambda w: w['x0']) for _, l in lignes]


# Caisse d'Epargne : bornes gauches des colonnes (points), mesurees sur les
# tableaux de 2022. Un montant appartient a la colonne dont il tombe entre
# les bornes ; les morceaux d'un nombre coupe tombent dans la meme.
_CE_COLONNES = [('montant', 90), ('capital', 190), ('interets', 262), ('accessoires', 315),
                ('crd', 355), ('report', 445), ('interets_reportes', 510)]


def _ce(pdf, texte):
    lib = re.search(r'(PRET HABITAT[^\n]*|P\.H\s*PRIMO[^\n]*)', texte)
    noms = {'PRET HABITAT LISSE 2 PHASES': 'Prêt habitat lissé 2 phases', 'P.H PRIMO': 'Prêt habitat Primo'}
    brut = lib.group(1).strip(' .') if lib else ''
    t = Tableau(preteur="Caisse d'Épargne", libelle=noms.get(brut, brut.capitalize() or 'Prêt'),
                emprunteur=None, montant=None, taux=None)
    for page in pdf.pages:
        for l in _lignes(page):
            # Le rang est le mot qui PRECEDE la date : un code de marge imprime
            # a la verticale tombe parfois sur la ligne, devant lui.
            i = next((k for k, w in enumerate(l) if _DATE.fullmatch(w['text'])), None)
            if i is None or i == 0 or not re.fullmatch(r'\d{1,3}', l[i - 1]['text']):
                continue
            date, rang = _DATE.fullmatch(l[i]['text']), int(l[i - 1]['text'])
            cols = {}
            for w in l[i + 1:]:
                nom = None
                for n, borne in _CE_COLONNES:
                    if w['x0'] >= borne:
                        nom = n
                if nom:
                    cols[nom] = cols.get(nom, '') + w['text']
            v = {k: _num(x) for k, x in cols.items()}
            if v.get('crd') is None or v.get('capital') is None:
                continue
            t.echeances.append(Echeance(rang=rang, date=_iso(date), capital=v['capital'],
                                        interets=v.get('interets') or 0.0,
                                        assurance=v.get('accessoires') or 0.0, crd=v['crd']))
    return t


_ARKEA_LIGNE = re.compile(r'^(\d{1,3})\s+(\d{2}/\d{2}/\d{4})\s+((?:[\d.]+,\d{2}\s+){5}[\d.]+,\d{2})\s*$')
# Echeance de franchise : trois zeros puis le restant du, qui AUGMENTE des
# interets stockes (imprimes sur la ligne suivante, marques (*)).
_ARKEA_FRANCHISE = re.compile(r'^(\d{1,3})\s+(\d{2}/\d{2}/\d{4})\s+((?:[\d.]+,\d{2}\s+){3}[\d.]+,\d{2})\s*$')


def _arkea(pdf, texte):
    montant = re.search(r'Montantdupr[eê]t\s*:\s*([\d\s.,]+)€', texte)
    taux = re.search(r'Taux\s*hors\s*assurance[^:]*:\s*([\d,]+)\s*%', texte)
    emp = re.search(r'Emprunteur\s*:\s*([^\n]+)', texte)
    obj = re.search(r'Objet\s*:\s*([^\n]+)', texte)
    # L'objet s'imprime sans espaces (« ACHATPARTSSCPI ») : on le nomme.
    objet = (obj.group(1) if obj else '').upper().replace(' ', '')
    libelle = ('Achat de parts de SCPI' if 'SCPI' in objet else
               'Prêt immobilier' if 'IMMO' in objet or 'ACQUISITION' in objet else 'Prêt')
    t = Tableau(preteur='Arkéa Banque Privée', libelle=libelle,
                emprunteur=emp.group(1).strip() if emp else None,
                montant=_num(montant.group(1)) if montant else None,
                taux=_num(taux.group(1)) if taux else None)
    # Pendant la franchise, les interets s'ajoutent au restant du ; ils se
    # remboursent ensuite par la colonne « interets differes ». La baisse du
    # restant du vaut donc amortissement + interets differes : c'est ce qu'on
    # appelle ici le capital rembourse. En franchise, il est negatif.
    precedent = t.montant
    for ligne in texte.split('\n'):
        ligne = ligne.strip()
        m = _ARKEA_LIGNE.match(ligne)
        if m:
            amort, int_n, int_d, assur, _total, crd = [_num(x) for x in m.group(3).split()]
            capital, interets = amort + int_d, int_n
        else:
            m = _ARKEA_FRANCHISE.match(ligne)
            if not m:
                continue
            *_zeros, crd = [_num(x) for x in m.group(3).split()]
            capital = round((precedent or crd) - crd, 2)
            interets, assur = 0.0, 0.0
        t.echeances.append(Echeance(rang=int(m.group(1)), date=_iso(_DATE.match(m.group(2))),
                                    capital=round(capital, 2), interets=interets, assurance=assur, crd=crd))
        precedent = crd
    return t


def _verifier(t):
    """Le capital restant du doit baisser du capital amorti, echeance par
    echeance. Tout ecart au-dela du centime fait refuser le tableau."""
    e = t.echeances
    if len(e) < 2:
        raise ValueError('Aucune échéance lue dans ce document')
    rangs = [x.rang for x in e]
    if len(set(rangs)) != len(rangs):
        raise ValueError('Échéances en double : lecture du tableau incertaine')
    for a, b in zip(e, e[1:]):
        if abs((a.crd - b.capital) - b.crd) > TOLERANCE:
            raise ValueError(f'Échéance {b.rang} du {b.date} : le capital restant dû ne suit pas '
                             f'le capital amorti ({a.crd:.2f} − {b.capital:.2f} ≠ {b.crd:.2f})')
    if abs(e[-1].crd) > TOLERANCE:
        raise ValueError('La dernière échéance ne solde pas le prêt')
    if t.montant is None:
        t.montant = round(e[0].crd + e[0].capital, 2)
    elif abs(t.montant - (e[0].crd + e[0].capital)) > TOLERANCE:
        raise ValueError(f'La première échéance ne part pas du montant emprunté ({t.montant:.2f})')
    t.controles.append(f'{len(e)} échéances ; capital restant dû cohérent à chaque ligne, soldé au {e[-1].date}')
    return t


def lire_tableau(chemin_ou_flux) -> Tableau:
    import pdfplumber
    with pdfplumber.open(chemin_ou_flux) as pdf:
        texte = '\n'.join((p.extract_text() or '') for p in pdf.pages)
        if 'ARKEA' in texte.upper() and 'TABLEAU D' in texte.upper():
            t = _arkea(pdf, texte)
        elif 'CAPITAL' in texte.upper() and ('PRET HABITAT' in texte.upper() or 'P.H PRIMO' in texte.upper()
                                              or "CAISSE D'EPARGNE" in texte.upper()):
            t = _ce(pdf, texte)
        else:
            raise ValueError("Gabarit de tableau d'amortissement non reconnu (Caisse d'Épargne ou Arkéa attendus)")
    return _verifier(t)
