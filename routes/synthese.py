import json
from flask import Blueprint, jsonify, request
from datetime import datetime
from models import (get_db, compute_position, get_entity_map, load_referential)
from auth import login_required, csrf_protect

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

    # Derive owners from actual data, preserving ref order for known ones
    ref_owners = ref['owners']
    data_owners = sorted(set(p['owner'] for p in positions))
    owners = [o for o in ref_owners if o in data_owners] + \
             [o for o in data_owners if o not in ref_owners]

    totals_by_owner = {}
    for owner in owners:
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
                             for o in owners},
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

    # ── Helper : calculer les totaux d'un snapshot ──
    def _snapshot_totals(snap_date):
        with get_db() as c:
            snap_rows      = c.execute('SELECT * FROM positions WHERE date=?', (snap_date,)).fetchall()
            snap_entity_map = get_entity_map(c, snap_date)
            snap_ref        = load_referential(c)
        snap_positions = [compute_position(dict(r), snap_entity_map, snap_ref) for r in snap_rows]
        return {
            'net':   sum(p['net_attributed'] for p in snap_positions),
            'gross': sum(p['gross_attributed'] for p in snap_positions),
            'debt':  sum(p['debt_attributed'] for p in snap_positions),
            'mob':   sum(p['mobilizable_value'] for p in snap_positions),
        }

    def _build_variation(totals, prev_date_str):
        cur_mob = sum(t['mobilizable'] for t in totals_by_owner.values())
        return {
            'prev_date':   prev_date_str,
            'net_delta':   family['net'] - totals['net'],
            'net_pct':     ((family['net'] - totals['net']) / abs(totals['net']) * 100) if totals['net'] != 0 else None,
            'gross_delta': family['gross'] - totals['gross'],
            'debt_delta':  family['debt'] - totals['debt'],
            'mob_delta':   cur_mob - totals['mob'],
        }

    # ── Variation vs snapshot précédent ──
    variation = None
    with get_db() as conn2:
        prev_row = conn2.execute(
            'SELECT DISTINCT date FROM positions WHERE date < ? ORDER BY date DESC LIMIT 1',
            (date,)
        ).fetchone()
    if prev_row:
        variation = _build_variation(_snapshot_totals(prev_row['date']), prev_row['date'])

    # ── Variation N / N-1 (Year-over-Year) ──
    yoy_variation = None
    try:
        from datetime import date as _date
        d = _date.fromisoformat(date)
        # Handle leap year: 2024-02-29 → 2023-02-28
        try:
            year_ago = d.replace(year=d.year - 1).isoformat()
        except ValueError:
            year_ago = d.replace(year=d.year - 1, day=d.day - 1).isoformat()
        with get_db() as conn2:
            yoy_row = conn2.execute(
                'SELECT DISTINCT date FROM positions WHERE date <= ? ORDER BY date DESC LIMIT 1',
                (year_ago,)
            ).fetchone()
        if yoy_row and yoy_row['date'] != date:
            yoy_variation = _build_variation(_snapshot_totals(yoy_row['date']), yoy_row['date'])
    except Exception:
        pass

    # ── Note du snapshot ──
    snapshot_note = None
    with get_db() as conn2:
        note_row = conn2.execute('SELECT notes FROM snapshot_notes WHERE date=?', (date,)).fetchone()
        if note_row:
            snapshot_note = note_row['notes']

    return jsonify({
        'date':                    date,
        'family':                  family,
        'totals_by_owner':         totals_by_owner,
        'totals_by_category':      totals_by_category,
        'mobilizable_by_liquidity': mobilizable_by_liquidity,
        'entity_warnings':         entity_warnings,
        'variation':               variation,
        'yoy_variation':           yoy_variation,
        'snapshot_note':           snapshot_note,
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
            snap_owners = sorted(set(p['owner'] for p in positions))
            entry = {
                'date':       date,
                'family_net': sum(p['net_attributed'] for p in positions),
                'by_owner':   {o: sum(p['net_attributed'] for p in positions if p['owner'] == o)
                              for o in snap_owners},
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
    Calcule le XIRR (taux de rendement interne annualisé).
    cashflows : liste de (date_str 'YYYY-MM-DD', montant)
    Retourne le taux annuel en % ou None si non convergent.
    Utilise Newton-Raphson avec plusieurs estimations initiales,
    puis bisection en fallback.
    """
    if len(cashflows) < 2:
        return None
    dates = [datetime.strptime(d, '%Y-%m-%d') for d, _ in cashflows]
    amounts = [a for _, a in cashflows]
    if all(a >= 0 for a in amounts) or all(a <= 0 for a in amounts):
        return None  # pas de signe mixte → pas de TRI
    d0 = dates[0]
    years = [(d - d0).days / 365.25 for d in dates]
    total = sum(abs(a) for a in amounts)

    def npv_at(rate):
        return sum(a / (1 + rate) ** t for a, t in zip(amounts, years))

    def dnpv_at(rate):
        return sum(-t * a / (1 + rate) ** (t + 1) for a, t in zip(amounts, years))

    def newton(guess):
        rate = guess
        for _ in range(300):
            npv = npv_at(rate)
            dnpv = dnpv_at(rate)
            if abs(dnpv) < 1e-14:
                break
            new_rate = rate - npv / dnpv
            if new_rate < -0.99:
                new_rate = -0.99
            if new_rate > 10:
                new_rate = 10
            if abs(new_rate - rate) < 1e-9:
                if total > 0 and abs(npv_at(new_rate)) / total < 1e-6:
                    return new_rate
                return None
            rate = new_rate
        if total > 0 and abs(npv_at(rate)) / total < 1e-6:
            return rate
        return None

    # Essayer plusieurs estimations initiales
    for guess in [0.1, 0.0, -0.5, 0.5, -0.9, 1.0, 5.0]:
        result = newton(guess)
        if result is not None:
            return round(result * 100, 2)

    # Fallback : bisection entre -0.99 et 10
    lo, hi = -0.99, 10.0
    npv_lo, npv_hi = npv_at(lo), npv_at(hi)
    if npv_lo * npv_hi > 0:
        return None  # pas de racine dans l'intervalle
    for _ in range(1000):
        mid = (lo + hi) / 2
        npv_mid = npv_at(mid)
        if total > 0 and abs(npv_mid) / total < 1e-8:
            return round(mid * 100, 2)
        if npv_mid * npv_lo < 0:
            hi = mid
        else:
            lo = mid
            npv_lo = npv_mid
    return None


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

        # Flux hors plage — avertissement
        excluded_query = 'SELECT COUNT(*) as cnt FROM flux WHERE date <= ? OR date > ?'
        excluded_params = [first_date, last_date]
        if owner:
            excluded_query += ' AND owner = ?'
            excluded_params.append(owner)
        excluded_count = conn.execute(excluded_query, excluded_params).fetchone()['cnt']

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

    resp = {'date': last_date, 'first_date': first_date, 'tri': result}
    if excluded_count > 0:
        resp['excluded_flux'] = excluded_count
    return jsonify(resp)


# ─── Notes de snapshot ────────────────────────────────────────────────────

@synthese_bp.route('/api/snapshot-notes', methods=['GET'])
@login_required
def get_snapshot_notes():
    date = request.args.get('date')
    with get_db() as conn:
        if date:
            row = conn.execute('SELECT notes FROM snapshot_notes WHERE date=?', (date,)).fetchone()
            return jsonify({'date': date, 'notes': row['notes'] if row else None})
        rows = conn.execute('SELECT date, notes FROM snapshot_notes ORDER BY date DESC').fetchall()
        return jsonify({r['date']: r['notes'] for r in rows})


@synthese_bp.route('/api/snapshot-notes', methods=['PUT'])
@login_required
@csrf_protect
def save_snapshot_note():
    d = request.json
    date = d.get('date')
    notes = (d.get('notes') or '').strip()
    if not date:
        return jsonify({'error': 'Date requise'}), 400
    with get_db() as conn:
        if notes:
            conn.execute(
                'INSERT OR REPLACE INTO snapshot_notes (date, notes) VALUES (?, ?)',
                (date, notes)
            )
        else:
            conn.execute('DELETE FROM snapshot_notes WHERE date=?', (date,))
    return jsonify({'ok': True})


# ─── Objectif patrimoine ──────────────────────────────────────────────────

@synthese_bp.route('/api/wealth-target', methods=['GET'])
@login_required
def get_wealth_target():
    with get_db() as conn:
        row = conn.execute("SELECT value FROM config WHERE key='wealth_target'").fetchone()
    if row:
        try:
            return jsonify(json.loads(row['value']))
        except Exception:
            pass
    return jsonify({'target': None})


@synthese_bp.route('/api/wealth-target', methods=['PUT'])
@login_required
@csrf_protect
def save_wealth_target():
    d = request.json
    if not isinstance(d, dict):
        return jsonify({'error': 'Objet JSON attendu'}), 400
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES ('wealth_target', ?)",
            (json.dumps(d),)
        )
    return jsonify({'ok': True})
