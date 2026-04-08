from flask import Blueprint, jsonify, request
from datetime import datetime
from models import (get_db, compute_position, get_entity_map, load_referential,
                    OWNERS)
from auth import login_required

synthese_bp = Blueprint('synthese', __name__)


@synthese_bp.route('/api/synthese')
@login_required
def get_synthese():
    date = request.args.get('date')
    with get_db() as conn:
        if not date:
            row = conn.execute('SELECT MAX(date) as d FROM positions').fetchone()
            date = row['d']
        if not date:
            return jsonify({'date': None})
        rows       = conn.execute('SELECT * FROM positions WHERE date=?', (date,)).fetchall()
        entity_map = get_entity_map(conn, date)
        ref        = load_referential(conn)
        linked     = conn.execute(
            '''SELECT entity,
                      SUM(ownership_pct) as total_own,
                      SUM(debt_pct)      as total_debt
               FROM positions WHERE date=? AND entity IS NOT NULL
               GROUP BY entity''', (date,)
        ).fetchall()

    positions = [compute_position(dict(r), entity_map, ref) for r in rows]

    totals_by_owner = {}
    for owner in ref['owners']:
        ops = [p for p in positions if p['owner'] == owner]
        totals_by_owner[owner] = {
            'gross':       sum(p['gross_attributed'] for p in ops),
            'debt':        sum(p['debt_attributed'] for p in ops),
            'net':         sum(p['net_attributed'] for p in ops),
            'mobilizable': sum(p['mobilizable_value'] for p in ops),
        }

    totals_by_category = {}
    for cat in ref['categories']:
        ops = [p for p in positions if p['category'] == cat]
        if ops:
            totals_by_category[cat] = {
                'net':      sum(p['net_attributed'] for p in ops),
                'by_owner': {o: sum(p['net_attributed'] for p in ops if p['owner'] == o)
                             for o in OWNERS},
            }

    mobilizable_by_liquidity = {
        liq: sum(p['mobilizable_value'] for p in positions if p['liquidity'] == liq)
        for liq in ref['liquidity_order']
    }

    family = {
        'gross': sum(t['gross'] for t in totals_by_owner.values()),
        'debt':  sum(t['debt']  for t in totals_by_owner.values()),
        'net':   sum(t['net']   for t in totals_by_owner.values()),
    }

    entity_warnings = []
    for r in linked:
        own  = r['total_own']  or 0
        debt = r['total_debt'] or 0
        if own > 1.02:
            entity_warnings.append({'entity': r['entity'], 'total_pct': round(own * 100),  'type': 'ownership'})
        if debt > 1.02:
            entity_warnings.append({'entity': r['entity'], 'total_pct': round(debt * 100), 'type': 'debt'})

    # ── Variation par rapport au snapshot précédent ──
    variation = None
    with get_db() as conn2:
        prev_row = conn2.execute(
            'SELECT DISTINCT date FROM positions WHERE date < ? ORDER BY date DESC LIMIT 1',
            (date,)
        ).fetchone()
    if prev_row:
        prev_date = prev_row['date']
        with get_db() as conn2:
            prev_rows      = conn2.execute('SELECT * FROM positions WHERE date=?', (prev_date,)).fetchall()
            prev_entity_map = get_entity_map(conn2, prev_date)
            prev_ref        = load_referential(conn2)
        prev_positions = [compute_position(dict(r), prev_entity_map, prev_ref) for r in prev_rows]
        prev_net   = sum(p['net_attributed'] for p in prev_positions)
        prev_gross = sum(p['gross_attributed'] for p in prev_positions)
        prev_debt  = sum(p['debt_attributed'] for p in prev_positions)
        prev_mob   = sum(p['mobilizable_value'] for p in prev_positions)
        variation = {
            'prev_date':  prev_date,
            'net_delta':   family['net'] - prev_net,
            'net_pct':     ((family['net'] - prev_net) / abs(prev_net) * 100) if prev_net != 0 else None,
            'gross_delta': family['gross'] - prev_gross,
            'debt_delta':  family['debt'] - prev_debt,
            'mob_delta':   sum(t['mobilizable'] for t in totals_by_owner.values()) - prev_mob,
        }

    return jsonify({
        'date':                    date,
        'family':                  family,
        'totals_by_owner':         totals_by_owner,
        'totals_by_category':      totals_by_category,
        'mobilizable_by_liquidity': mobilizable_by_liquidity,
        'entity_warnings':         entity_warnings,
        'variation':               variation,
    })


@synthese_bp.route('/api/historique')
@login_required
def get_historique():
    group_by = request.args.get('group_by')
    owner    = request.args.get('owner')
    with get_db() as conn:
        dates = [r['date'] for r in conn.execute(
            'SELECT DISTINCT date FROM positions ORDER BY date'
        ).fetchall()]
        ref = load_referential(conn)
        history = []
        for date in dates:
            rows       = conn.execute('SELECT * FROM positions WHERE date=?', (date,)).fetchall()
            entity_map = get_entity_map(conn, date)
            positions  = [compute_position(dict(r), entity_map, ref) for r in rows]
            if owner:
                positions = [p for p in positions if p['owner'] == owner]
            entry = {
                'date':       date,
                'family_net': sum(p['net_attributed'] for p in positions),
                'by_owner':   {o: sum(p['net_attributed'] for p in positions if p['owner'] == o)
                              for o in ref['owners']},
            }
            if group_by == 'envelope':
                by_env = {}
                for p in positions:
                    k = p.get('envelope') or 'Autre'
                    by_env[k] = by_env.get(k, 0) + (p['net_attributed'] or 0)
                entry['by_group'] = by_env
            elif group_by == 'category':
                by_cat = {}
                for p in positions:
                    k = p.get('category') or 'Autre'
                    by_cat[k] = by_cat.get(k, 0) + (p['net_attributed'] or 0)
                entry['by_group'] = by_cat
            history.append(entry)
    return jsonify(history)


# ─── TRI (XIRR) ──────────────────────────────────────────────────────────────

def _xirr(cashflows):
    """
    Calcule le XIRR (taux de rendement interne annualisé) par Newton-Raphson.
    cashflows : liste de (date_str 'YYYY-MM-DD', montant)
    Retourne le taux annuel en % ou None si non convergent.
    """
    if len(cashflows) < 2:
        return None
    dates = [datetime.strptime(d, '%Y-%m-%d') for d, _ in cashflows]
    amounts = [a for _, a in cashflows]
    if all(a >= 0 for a in amounts) or all(a <= 0 for a in amounts):
        return None  # pas de signe mixte → pas de TRI
    d0 = dates[0]
    days = [(d - d0).days / 365.25 for d in dates]

    rate = 0.1  # estimation initiale
    for _ in range(200):
        npv = sum(a / (1 + rate) ** t for a, t in zip(amounts, days))
        dnpv = sum(-t * a / (1 + rate) ** (t + 1) for a, t in zip(amounts, days))
        if abs(dnpv) < 1e-14:
            break
        new_rate = rate - npv / dnpv
        if abs(new_rate - rate) < 1e-9:
            return round(new_rate * 100, 2)
        rate = new_rate
        if rate < -0.99:
            rate = -0.99  # borne basse
    return round(rate * 100, 2) if abs(npv) < 1 else None


def _flux_to_cashflow(f):
    """Convertit un flux en cashflow signé pour le XIRR."""
    ftype = f.get('type', '')
    amount = f.get('amount', 0)
    if ftype == 'Versement':
        return (f['date'], -abs(amount))
    elif ftype in ('Retrait', 'Dividende/Intérêt'):
        return (f['date'], abs(amount))
    elif ftype == 'Frais':
        return (f['date'], -abs(amount))
    return (f['date'], amount)


@synthese_bp.route('/api/tri')
@login_required
def get_tri():
    """
    Calcule le TRI par enveloppe (et global).
    Cashflows : valeur initiale (négatif) + flux intermédiaires + valeur finale (positif).
    """
    owner = request.args.get('owner')
    with get_db() as conn:
        dates = [r['date'] for r in conn.execute(
            'SELECT DISTINCT date FROM positions ORDER BY date'
        ).fetchall()]
        if len(dates) < 2:
            return jsonify({})

        first_date = dates[0]
        last_date  = dates[-1]
        ref = load_referential(conn)

        # Valeur initiale par enveloppe (1er snapshot)
        first_rows = conn.execute('SELECT * FROM positions WHERE date=?', (first_date,)).fetchall()
        first_entity_map = get_entity_map(conn, first_date)
        first_positions = [compute_position(dict(r), first_entity_map, ref) for r in first_rows]
        if owner:
            first_positions = [p for p in first_positions if p['owner'] == owner]

        initial_by_env = {}
        total_initial = 0
        for p in first_positions:
            env = p.get('envelope') or 'Autre'
            initial_by_env[env] = initial_by_env.get(env, 0) + (p['net_attributed'] or 0)
            total_initial += (p['net_attributed'] or 0)

        # Valeur finale par enveloppe (dernier snapshot)
        last_rows = conn.execute('SELECT * FROM positions WHERE date=?', (last_date,)).fetchall()
        last_entity_map = get_entity_map(conn, last_date)
        last_positions = [compute_position(dict(r), last_entity_map, ref) for r in last_rows]
        if owner:
            last_positions = [p for p in last_positions if p['owner'] == owner]

        current_by_env = {}
        total_current = 0
        for p in last_positions:
            env = p.get('envelope') or 'Autre'
            current_by_env[env] = current_by_env.get(env, 0) + (p['net_attributed'] or 0)
            total_current += (p['net_attributed'] or 0)

        # Flux entre les deux dates
        flux_rows = conn.execute(
            'SELECT * FROM flux WHERE date > ? AND date <= ? ORDER BY date',
            (first_date, last_date)
        ).fetchall()
        flux_list = [dict(r) for r in flux_rows]
        if owner:
            flux_list = [f for f in flux_list if f['owner'] == owner]

    all_envs = set(initial_by_env.keys()) | set(current_by_env.keys())

    result = {}
    for env in all_envs:
        init_val = initial_by_env.get(env, 0)
        final_val = current_by_env.get(env, 0)
        env_flux = [f for f in flux_list if (f.get('envelope') or 'Autre') == env]
        cashflows = []
        if init_val != 0:
            cashflows.append((first_date, -init_val))
        for f in env_flux:
            cashflows.append(_flux_to_cashflow(f))
        cashflows.append((last_date, final_val))
        tri = _xirr(cashflows)
        if tri is not None:
            result[env] = tri

    # TRI global
    all_cashflows = []
    if total_initial != 0:
        all_cashflows.append((first_date, -total_initial))
    for f in flux_list:
        all_cashflows.append(_flux_to_cashflow(f))
    all_cashflows.append((last_date, total_current))
    tri_global = _xirr(all_cashflows)
    if tri_global is not None:
        result['_global'] = tri_global

    return jsonify({'date': last_date, 'first_date': first_date, 'tri': result})
