"""Releve de compte titres BoursoBank (« RELEVE COMPTE TITRES »), PEA ou CTO.

Une ligne par titre :

    1 000 ETF MONDE ACC (FR0010315770) * 10,125 10 125,00 50,00 9,500
    quantite, nom (ISIN), [MiFID], cours, valorisation EUR, % du portefeuille,
    prix de revient fiscal unitaire EUR

Les nombres sont toujours au format francais : espace pour les milliers,
virgule decimale. « 10,125 » est un cours a trois decimales, jamais 10 125 —
le lecteur generique, qui doit deviner entre les formats, s'y trompait.

Le releve se verifie lui-meme : la somme des lignes doit redonner le « TOTAL DU
PORTEFEUILLE » imprime, au centime. Sinon il est refuse, avec les deux montants :
une ligne mal lue fausserait en silence la valorisation de tout le compte.
"""
from __future__ import annotations
import re
from typing import List, Tuple

from .common import DetectedLine, ReleveIncoherentError, isin_luhn_ok, montant_fr as _eur

_MILLIERS = r'\d{1,3}(?:[   ]\d{3})*'
LIGNE_RE = re.compile(
    rf'^(?P<qte>{_MILLIERS}(?:,\d+)?)\s+(?P<nom>.+?)\s+\((?P<isin>[A-Z]{{2}}[A-Z0-9]{{9}}\d)\)(?:\s+\*)?'
    rf'\s+(?P<cours>{_MILLIERS},\d+)\s+(?P<valo>{_MILLIERS},\d{{2}})\s+(?P<pct>\d{{1,3}},\d{{2}})'
    rf'\s+(?P<pru>{_MILLIERS},\d+)$')
# « VALEURS ETRANGERES 1 EUR = 1,100 USD USD EUR EUR » : la devise des cours est
# la premiere des trois colonnes monetaires de l'en-tete de section.
SECTION_RE = re.compile(r'^VALEURS\b.*\b([A-Z]{3}) EUR EUR$')
TOTAL_RE = re.compile(rf'TOTAL DU PORTEFEUILLE\s+({_MILLIERS},\d{{2}})\s*EUR')
TOTAL_EUR_RE = re.compile(rf'^TOTAL EUR\s+({_MILLIERS},\d{{2}})\b', re.M)
DATE_RE = re.compile(r'Valoris[ée] au (\d{2})/(\d{2})/(\d{4})')
ESPECES_RE = re.compile(rf'SOLDE ESPECES \(EUR\)\s+(-?{_MILLIERS},\d{{2}})\s*EUR')


def est_releve_titres(texte: str) -> bool:
    haut = texte.upper()
    return 'RELEVE COMPTE TITRES' in haut and ('BOURSOBANK' in haut or 'BOURSORAMA' in haut)


def fr(s: str) -> float:
    """Nombre au format francais : espaces de milliers, virgule decimale."""
    return float(re.sub(r'[   ]', '', s).replace(',', '.'))


def lire_texte(texte: str) -> Tuple[List[DetectedLine], List[str]]:
    """Lignes et avertissements d'un releve, verifies contre son total.

    Leve ReleveIncoherentError si aucune ligne n'est lue, si le total est
    introuvable, ou si la somme des lignes ne le redonne pas."""
    m = DATE_RE.search(texte)
    date = f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else None
    lignes: List[DetectedLine] = []
    devise = 'EUR'
    for brute in texte.splitlines():
        brute = brute.strip()
        s = SECTION_RE.match(brute)
        if s:
            devise = s.group(1)
            continue
        m = LIGNE_RE.match(brute)
        if not m:
            continue
        isin = m.group('isin')
        if not isin_luhn_ok(isin):
            raise ReleveIncoherentError(f'ISIN invalide lu sur le relevé : {isin}.')
        quantite, valo, pru = fr(m.group('qte')), fr(m.group('valo')), fr(m.group('pru'))
        lignes.append(DetectedLine(
            isin=isin, name=m.group('nom').strip(), quantity=quantite,
            market_value=valo, cost_basis=round(pru * quantite, 2),
            # Le cours est dans la devise de negociation : en euros seulement s'il l'est.
            unit_price=fr(m.group('cours')) if devise == 'EUR' else None,
            raw=brute, confidence=0.95, source='boursobank_releve_titres', as_of_date=date))
    if not lignes:
        raise ReleveIncoherentError("Relevé de titres BoursoBank : aucune ligne lue, le format a peut-être changé.")
    m = TOTAL_RE.search(texte) or TOTAL_EUR_RE.search(texte)
    if not m:
        raise ReleveIncoherentError("Relevé de titres BoursoBank : total du portefeuille introuvable, "
                                    "impossible de vérifier les lignes lues.")
    total, somme = fr(m.group(1)), round(sum(l.market_value for l in lignes), 2)
    if abs(total - somme) > 0.02:
        raise ReleveIncoherentError(
            f"Relevé de titres BoursoBank incohérent : les {len(lignes)} lignes lues totalisent "
            f"{_eur(somme)}, le relevé indique {_eur(total)}. Rien n'est importé.")
    avert = []
    e = ESPECES_RE.search(texte)
    if e and fr(e.group(1)):
        # Ecarte des lignes de titres, il est dit : il se saisit sur la position.
        avert.append(f"Solde espèces de {_eur(fr(e.group(1)))} au relevé, non repris dans les lignes de titres.")
    return lignes, avert


def lire(pdf) -> Tuple[List[DetectedLine], List[str]]:
    texte = '\n'.join((page.extract_text() or '') for page in pdf.pages)
    return lire_texte(texte)
