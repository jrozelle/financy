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
        adjustments.append('LBO detecte : +8% Cash / -8% Actions pour diluer la concentration de risque professionnelle.')

    if profile.get('employment_type') == 'TNS':
        base['Cash']    = base.get('Cash', 0) + 0.05
        base['Actions'] = max(0, base.get('Actions', 0) - 0.05)
        adjustments.append('TNS : +5% Cash / -5% Actions (pas de chomage, pas d\'abondement employeur).')

    # Approche retraite : shift progressif vers obligations
    horizon = profile.get('horizon_years')
    if horizon is not None and horizon <= 5:
        shift = min(0.10, max(0, (6 - horizon) * 0.02))
        if shift > 0:
            base['Obligations'] = base.get('Obligations', 0) + shift
            base['Actions']     = max(0, base.get('Actions', 0) - shift)
            adjustments.append(f'Horizon court ({horizon} ans) : +{shift*100:.0f}% Obligations / -{shift*100:.0f}% Actions.')

    # Pas de RP, horizon > 5 : reserver un peu d'immobilier
    if profile.get('main_residence_owned') is False and (horizon is None or horizon >= 3):
        base['Immobilier'] = base.get('Immobilier', 0) + 0.05
        base['Actions']    = max(0, base.get('Actions', 0) - 0.05)
        adjustments.append('Sans residence principale : +5% Immobilier (projet d\'acquisition).')

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
