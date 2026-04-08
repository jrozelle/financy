from flask import Blueprint, jsonify, request
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
