"""
Moteur d'allocation cible par profil (phase 6).

Logique deterministe (aucun appel reseau, 100% testable) :

1. Matrice de base
   horizon x risque → allocation cible par categorie.
   Les categories prises en compte sont celles du referentiel Financy
   (Cash, Obligations, Immobilier, Actions, Autres, Dette privee).

2. Ajustements contextuels
   has_lbo=true         → +8% Cash,        -8% Actions (concentration de risque)
   employment_type=TNS  → +5% Cash,        -5% Actions (pas de chomage ni de PEE)
   main_residence_owned=false & age<40 → +5% Immobilier pour objectif achat
   pension_age - age < 10 → shift progressif vers Obligations

3. Normalisation
   Apres ajustements on renormalise pour que la somme = 100%.

La matrice est chargee depuis le referentiel (config), ce qui la rend
editable par l'utilisateur sans redeploy. Un fallback inline est fourni.
"""
from __future__ import annotations
import json
import logging
from typing import Dict, List, Tuple, Optional

from services.categories import est_financier
from services import precaution as _precaution

logger = logging.getLogger('financy.advisor')


# ─── Matrice par defaut : 5 horizons x 5 niveaux de risque ──────────────────
# Cles horizon : <=1, 1-3, 3-8, 8-15, >15 (bornes haute exclues sauf la derniere)
# Cles risque  : 1 (prudent) → 5 (dynamique)
# Chaque cellule = {categorie: pct} dont la somme = 1.0.

DEFAULT_ALLOCATION_MATRIX: Dict[str, Dict[int, Dict[str, float]]] = {
    '<=1': {
        1: {'Cash': 0.85, 'Obligations': 0.15, 'Actions': 0.00, 'Immobilier': 0.00, 'Autres': 0.00},
        2: {'Cash': 0.75, 'Obligations': 0.20, 'Actions': 0.05, 'Immobilier': 0.00, 'Autres': 0.00},
        3: {'Cash': 0.65, 'Obligations': 0.25, 'Actions': 0.10, 'Immobilier': 0.00, 'Autres': 0.00},
        4: {'Cash': 0.55, 'Obligations': 0.30, 'Actions': 0.15, 'Immobilier': 0.00, 'Autres': 0.00},
        5: {'Cash': 0.45, 'Obligations': 0.35, 'Actions': 0.20, 'Immobilier': 0.00, 'Autres': 0.00},
    },
    '1-3': {
        1: {'Cash': 0.65, 'Obligations': 0.30, 'Actions': 0.05, 'Immobilier': 0.00, 'Autres': 0.00},
        2: {'Cash': 0.50, 'Obligations': 0.35, 'Actions': 0.15, 'Immobilier': 0.00, 'Autres': 0.00},
        3: {'Cash': 0.35, 'Obligations': 0.35, 'Actions': 0.25, 'Immobilier': 0.05, 'Autres': 0.00},
        4: {'Cash': 0.25, 'Obligations': 0.30, 'Actions': 0.40, 'Immobilier': 0.05, 'Autres': 0.00},
        5: {'Cash': 0.15, 'Obligations': 0.25, 'Actions': 0.55, 'Immobilier': 0.05, 'Autres': 0.00},
    },
    '3-8': {
        1: {'Cash': 0.40, 'Obligations': 0.40, 'Actions': 0.15, 'Immobilier': 0.05, 'Autres': 0.00},
        2: {'Cash': 0.25, 'Obligations': 0.40, 'Actions': 0.25, 'Immobilier': 0.10, 'Autres': 0.00},
        3: {'Cash': 0.15, 'Obligations': 0.30, 'Actions': 0.40, 'Immobilier': 0.15, 'Autres': 0.00},
        4: {'Cash': 0.10, 'Obligations': 0.20, 'Actions': 0.55, 'Immobilier': 0.15, 'Autres': 0.00},
        5: {'Cash': 0.05, 'Obligations': 0.10, 'Actions': 0.70, 'Immobilier': 0.15, 'Autres': 0.00},
    },
    '8-15': {
        1: {'Cash': 0.25, 'Obligations': 0.45, 'Actions': 0.20, 'Immobilier': 0.10, 'Autres': 0.00},
        2: {'Cash': 0.15, 'Obligations': 0.35, 'Actions': 0.35, 'Immobilier': 0.15, 'Autres': 0.00},
        3: {'Cash': 0.10, 'Obligations': 0.25, 'Actions': 0.45, 'Immobilier': 0.20, 'Autres': 0.00},
        4: {'Cash': 0.05, 'Obligations': 0.15, 'Actions': 0.60, 'Immobilier': 0.20, 'Autres': 0.00},
        5: {'Cash': 0.05, 'Obligations': 0.05, 'Actions': 0.70, 'Immobilier': 0.20, 'Autres': 0.00},
    },
    '>15': {
        1: {'Cash': 0.20, 'Obligations': 0.45, 'Actions': 0.20, 'Immobilier': 0.15, 'Autres': 0.00},
        2: {'Cash': 0.10, 'Obligations': 0.30, 'Actions': 0.40, 'Immobilier': 0.20, 'Autres': 0.00},
        3: {'Cash': 0.05, 'Obligations': 0.20, 'Actions': 0.50, 'Immobilier': 0.25, 'Autres': 0.00},
        4: {'Cash': 0.05, 'Obligations': 0.10, 'Actions': 0.60, 'Immobilier': 0.25, 'Autres': 0.00},
        5: {'Cash': 0.05, 'Obligations': 0.05, 'Actions': 0.70, 'Immobilier': 0.20, 'Autres': 0.00},
    },
}

CONFIG_KEY = 'advisor_allocation_matrix'


def _horizon_bucket(years: Optional[int]) -> str:
    """Mappe un horizon en annees sur une cle de matrice."""
    if years is None:
        return '3-8'
    y = int(years)
    if y <= 1:
        return '<=1'
    if y <= 3:
        return '1-3'
    if y <= 8:
        return '3-8'
    if y <= 15:
        return '8-15'
    return '>15'


def _clamp_risk(r: Optional[int]) -> int:
    if r is None:
        return 3
    return max(1, min(5, int(r)))


def _normalize(alloc: Dict[str, float]) -> Dict[str, float]:
    s = sum(alloc.values())
    if s <= 0:
        return alloc
    return {k: round(v / s, 4) for k, v in alloc.items()}


def load_matrix(conn) -> Dict[str, Dict[int, Dict[str, float]]]:
    """Charge la matrice depuis config (JSON) ou renvoie la default."""
    try:
        row = conn.execute(
            "SELECT value FROM config WHERE key=?", (CONFIG_KEY,)
        ).fetchone()
    except Exception:
        row = None
    if not row:
        return DEFAULT_ALLOCATION_MATRIX
    try:
        data = json.loads(row['value'])
        # Cast des cles risque en int
        return {
            h: {int(k): v for k, v in m.items()}
            for h, m in data.items()
        }
    except Exception:
        logger.warning('advisor_allocation_matrix config JSON invalide, fallback default')
        return DEFAULT_ALLOCATION_MATRIX


# ─── Calcul de l'allocation cible ────────────────────────────────────────────

def target_allocation(profile: dict, matrix=None) -> Tuple[Dict[str, float], List[str]]:
    """Calcule l'allocation cible par categorie.

    Retourne (allocation en pct 0-1, liste d'ajustements appliques).
    """
    matrix = matrix or DEFAULT_ALLOCATION_MATRIX
    h = _horizon_bucket(profile.get('horizon_years'))
    r = _clamp_risk(profile.get('risk_tolerance'))
    base = dict(matrix.get(h, {}).get(r, DEFAULT_ALLOCATION_MATRIX['3-8'][3]))

    adjustments = []

    if profile.get('has_lbo'):
        # LBO = concentration de risque pro, on compense
        base['Cash']    = base.get('Cash', 0) + 0.08
        base['Actions'] = max(0, base.get('Actions', 0) - 0.08)
        adjustments.append('LBO en cours : +8 % de liquidités, −8 % d’actions, pour ne pas ajouter du risque de marché au risque professionnel.')

    if profile.get('employment_type') == 'TNS':
        base['Cash']    = base.get('Cash', 0) + 0.05
        base['Actions'] = max(0, base.get('Actions', 0) - 0.05)
        adjustments.append('Travailleur non salarié : +5 % de liquidités, −5 % d’actions (ni chômage ni abondement employeur).')

    # Approche retraite : shift progressif vers obligations
    horizon = profile.get('horizon_years')
    if horizon is not None and horizon <= 5:
        shift = min(0.10, max(0, (6 - horizon) * 0.02))
        if shift > 0:
            base['Obligations'] = base.get('Obligations', 0) + shift
            base['Actions']     = max(0, base.get('Actions', 0) - shift)
            adjustments.append(f'Horizon court ({horizon} ans) : +{shift*100:.0f} % d’obligations, −{shift*100:.0f} % d’actions.')

    # Pas de RP, horizon > 5 : reserver un peu d'immobilier
    if profile.get('main_residence_owned') is False and (horizon is None or horizon >= 3):
        base['Immobilier'] = base.get('Immobilier', 0) + 0.05
        base['Actions']    = max(0, base.get('Actions', 0) - 0.05)
        adjustments.append('Sans résidence principale : 5 % réservés à un projet d’acquisition, pris sur les actions.')

    # Clamp negatifs + normalise
    base = {k: max(0, v) for k, v in base.items()}
    return _normalize(base), adjustments


# ─── Comparaison cible vs actuel ─────────────────────────────────────────────

def compute_actual_allocation(positions: List[dict]) -> Dict[str, float]:
    """Calcule l'allocation actuelle (en % net_attributed) par categorie."""
    total = sum(max(0, p.get('net_attributed') or 0) for p in positions)
    if total <= 0:
        return {}
    actual = {}
    for p in positions:
        cat = p.get('category') or 'Autres'
        v = max(0, p.get('net_attributed') or 0)
        actual[cat] = actual.get(cat, 0) + v
    return {k: round(v / total, 4) for k, v in actual.items()}


def compute_gap(target: Dict[str, float], actual: Dict[str, float],
                total_eur: float) -> List[dict]:
    """Compare cible vs actuel et retourne les ecarts par categorie.

    Chaque entree : {category, target_pct, actual_pct, delta_pct, delta_eur}
    """
    keys = set(target.keys()) | set(actual.keys())
    rows = []
    for cat in sorted(keys):
        t = target.get(cat, 0)
        a = actual.get(cat, 0)
        delta_pct = t - a
        delta_eur = delta_pct * total_eur
        rows.append({
            'category':   cat,
            'target_pct': round(t, 4),
            'actual_pct': round(a, 4),
            'delta_pct':  round(delta_pct, 4),
            'delta_eur':  round(delta_eur, 2),
        })
    rows.sort(key=lambda r: abs(r['delta_eur']), reverse=True)
    return rows


# ─── Perimetre financier ─────────────────────────────────────────────────────
#
# La matrice raisonne en classes (Cash, Obligations, Actions...), les positions
# en categories du referentiel (Cash & dépôts, Fond Euro, Produits Structurés...).
# Comparer les deux sans table de passage produisait des absurdites : « alleger
# Cash / Fond Euro vers Cash », un fonds euros vise a 0 % faute de cle.

CLASSE_DE = {
    'Cash & dépôts': 'Cash', 'Monétaire': 'Cash',
    # Capital garanti, rendement de portefeuille obligataire : c'est ainsi qu'un
    # conseiller le range.
    'Fond Euro': 'Obligations', 'Obligations': 'Obligations',
    'Actions': 'Actions', 'Produits Structurés': 'Actions', 'Crypto': 'Actions',
}

# Ni la residence, ni une SCPI a credit, ni un tableau, ni les parts de sa
# propre societe ne s'arbitrent contre un ETF. Les compter faussait toutes les
# proportions : la cible s'applique au seul patrimoine financier, celui de la
# synthese (services/categories.py) — tout le reste est decompte a part.

LIVRETS_REGLEMENTES = {'Livret A', 'LDDS', 'LEP'}


def _libelle(p):
    # « Livret Bourso+ BoursoBank », pas « Cash & dépôts Livret Bourso+ » :
    # la categorie est deja celle de la classe. Seul le fonds euros se nomme,
    # l'enveloppe (« Assurance-vie ») ne le distinguant pas des unites de compte.
    tete = p.get('label') or ('Fonds euros' if p.get('category') == 'Fond Euro' else None)
    return ' '.join(x for x in (tete, p.get('envelope'), p.get('establishment')) if x)


def allocation_financiere(profile: dict, positions: List[dict], matrix=None, entites=(), rendements=None) -> dict:
    """Cible, reel et ecarts par classe, sur le patrimoine financier ARBITRABLE.

    La precaution passe d'abord : la part gardee (services/precaution.py —
    livrets reglementes entiers, puis les supports les plus rentables jusqu'a
    la cible) sort du calcul, comme les comptes courants (l'argent qui tourne)
    et la tresorerie des societes. La matrice de risque se repartit sur ce qui
    reste, sans part de liquidites propre : les liquidites sont la precaution.
    Seuls les supplements de liquidites (LBO, TNS) restent a la cible.

    Chaque classe distingue ce qui peut bouger (`libre_eur`) de ce qui compte
    dans l'exposition sans pouvoir bouger (`bloque_eur` : contrat nanti, PER,
    produit structure). Rien ne disparait : tout ce qui est ecarte est
    decompte dans `exclus`.
    """
    target, adjustments = target_allocation(profile, matrix)
    # La part de liquidites de la matrice est la precaution, gardee a part :
    # ne restent que les supplements des ajustements (LBO, TNS).
    base_cash = (matrix or DEFAULT_ALLOCATION_MATRIX).get(_horizon_bucket(profile.get('horizon_years')), {}) \
        .get(_clamp_risk(profile.get('risk_tolerance')), DEFAULT_ALLOCATION_MATRIX['3-8'][3]).get('Cash', 0)
    target = dict(target)
    target['Cash'] = max(0.0, target.get('Cash', 0) - base_cash)
    # Avec une cible de precaution, les supplements de liquidites (LBO, TNS)
    # feraient double emploi : les mois de charges choisis couvrent deja ce
    # risque. Ils vont aux obligations — la prudence voulue reste, en moins
    # d'actions, sans gonfler les liquidites.
    if target['Cash'] > 0 and _precaution.cible(profile) is not None:
        supplement = target['Cash']
        target['Obligations'] = target.get('Obligations', 0) + supplement
        target['Cash'] = 0.0
        adjustments = adjustments + [
            f'Cible de précaution renseignée ({profile.get("mois_precaution")} mois de charges) : les '
            f'{supplement * 100:.0f} points de liquidités de ces ajustements vont aux obligations, la réserve '
            'étant déjà gardée à part.']
    cible = _normalize({k: v for k, v in target.items() if k != 'Immobilier'})

    rep = _precaution.repartition(positions, profile, entites, rendements)
    gardee = {id(p): k for p, k in rep['gardees']}

    classes: Dict[str, dict] = {}
    exclus: Dict[str, float] = {}
    reglementes = 0.0
    for p in positions:
        cat = p.get('category') or 'Autres'
        net = max(0.0, p.get('net_attributed') or 0)
        if not net:
            continue
        if not est_financier(cat):
            exclus[cat] = exclus.get(cat, 0) + net
            continue
        # Un compte au nom d'une entite declaree est la tresorerie de la
        # societe, pas l'epargne du titulaire (meme regle que les constats).
        if {p.get('label'), p.get('entity')} & set(entites):
            exclus['Trésorerie de société'] = exclus.get('Trésorerie de société', 0) + net
            continue
        if cat == 'Cash & dépôts' and (p.get('envelope') or '') == _precaution.COMPTE_COURANT:
            exclus['Comptes courants'] = exclus.get('Comptes courants', 0) + net
            continue
        if p.get('envelope') in LIVRETS_REGLEMENTES:
            reglementes += net
        k = gardee.get(id(p), 0.0)
        if k:
            exclus['Épargne de précaution'] = exclus.get('Épargne de précaution', 0) + k
            net -= k
            if net <= 0.005:
                continue
        c = classes.setdefault(CLASSE_DE.get(cat, 'Autres'),
                               {'actual_eur': 0.0, 'libre_eur': 0.0, 'bloque_eur': 0.0,
                                'lignes_libres': [], 'lignes_bloquees': []})
        mobilisable = (p.get('mobilizable_value') or 0) - k
        libre = 0.0 if p.get('liquidity') == 'Bloqué' else max(0.0, min(net, mobilisable))
        c['actual_eur'] += net
        c['libre_eur'] += libre
        if libre <= 0:
            c['bloque_eur'] += net
        ligne = {'libelle': _libelle(p) + (' (au-delà de la précaution)' if k else ''), 'montant': round(net, 2)}
        (c['lignes_libres'] if libre > 0 else c['lignes_bloquees']).append(ligne)

    total = sum(c['actual_eur'] for c in classes.values())
    # Le financier de la synthese, pour que l'ecran raccorde les deux montants :
    # l'arbitrable plus ce qui en est ecarte sans quitter le financier.
    financier = total + sum(exclus.get(k, 0) for k in ('Trésorerie de société', 'Comptes courants', 'Épargne de précaution'))
    gap = []
    for cle in sorted(set(cible) | set(classes)):
        c = classes.get(cle, {'actual_eur': 0.0, 'libre_eur': 0.0, 'bloque_eur': 0.0,
                              'lignes_libres': [], 'lignes_bloquees': []})
        t = cible.get(cle, 0.0)
        a = c['actual_eur'] / total if total else 0.0
        if not t and not c['actual_eur']:
            continue
        gap.append({
            'category': cle,
            'target_pct': round(t, 4), 'actual_pct': round(a, 4), 'delta_pct': round(t - a, 4),
            'delta_eur': round((t - a) * total, 2),
            'actual_eur': round(c['actual_eur'], 2), 'target_eur': round(t * total, 2),
            'libre_eur': round(c['libre_eur'], 2),
            'bloque_eur': round(c['bloque_eur'], 2),
            'lignes_libres': sorted(c['lignes_libres'], key=lambda l: -l['montant']),
            'lignes_bloquees': sorted(c['lignes_bloquees'], key=lambda l: -l['montant']),
        })
    gap.sort(key=lambda r: abs(r['delta_eur']), reverse=True)
    return {
        'target': cible,
        'actual': {g['category']: g['actual_pct'] for g in gap if g['actual_eur']},
        'gap': gap,
        'total_eur': round(total, 2),
        'financier_eur': round(financier, 2),
        'bloque_eur': round(sum(g['bloque_eur'] for g in gap), 2),
        'exclus': [{'category': k, 'montant': round(v, 2)} for k, v in sorted(exclus.items(), key=lambda kv: -kv[1])],
        'reglementes_eur': round(reglementes, 2),
        # Epargne de precaution : montant, cible du profil, ecart ; et sa part
        # dans chaque classe, pour que les propositions la gardent.
        'precaution': _precaution.bilan(positions, profile, entites, rendements),
        'adjustments': adjustments,
    }
