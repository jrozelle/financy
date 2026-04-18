import logging
from flask import Blueprint, jsonify, request
from datetime import datetime
from models import (get_db, compute_position, get_entity_map, get_holdings_map,
                    load_referential, snapshot_holdings_to_date)
from auth import login_required, csrf_protect

logger = logging.getLogger('financy')
tools_bp = Blueprint('tools', __name__)


@tools_bp.route('/api/timeline')
@login_required
def get_timeline():
    """
    Retourne une frise chronologique des événements patrimoniaux :
    - snapshots (positions) avec net total
    - flux importants
    - changements d'entités
    """
    with get_db() as conn:
        ref = load_referential(conn)
        events = []

        # Snapshots
        dates = conn.execute(
            'SELECT DISTINCT date, COUNT(*) as cnt FROM positions GROUP BY date ORDER BY date'
        ).fetchall()
        for row in dates:
            d = row['date']
            pos_rows     = conn.execute('SELECT * FROM positions WHERE date=?', (d,)).fetchall()
            entity_map   = get_entity_map(conn, d)
            holdings_map = get_holdings_map(conn, [r['id'] for r in pos_rows])
            positions    = [compute_position(dict(r), entity_map, ref, holdings_map) for r in pos_rows]
            net = sum(p['net_attributed'] for p in positions)
            events.append({
                'date': d,
                'type': 'snapshot',
                'label': f'{row["cnt"]} positions',
                'value': round(net, 2),
            })

        # Notes de snapshot
        notes = conn.execute('SELECT date, notes FROM snapshot_notes').fetchall()
        for n in notes:
            events.append({
                'date': n['date'],
                'type': 'note',
                'label': n['notes'],
            })

        # Flux (regroupés par mois)
        flux_rows = conn.execute(
            '''SELECT SUBSTR(date, 1, 7) as month, SUM(amount) as total, COUNT(*) as cnt
               FROM flux GROUP BY SUBSTR(date, 1, 7) ORDER BY month'''
        ).fetchall()
        for f in flux_rows:
            events.append({
                'date': f['month'] + '-15',
                'type': 'flux',
                'label': f'{f["cnt"]} flux',
                'value': round(f['total'], 2),
            })

    events.sort(key=lambda e: e['date'])
    return jsonify(events)


@tools_bp.route('/api/position-history')
@login_required
def get_position_history():
    """
    Retourne l'évolution d'un sous-ensemble de positions à travers tous les snapshots.
    Filtres : owner, establishment, envelope, entity, category, position_id.
    """
    filters = {
        'owner': request.args.get('owner'),
        'establishment': request.args.get('establishment'),
        'envelope': request.args.get('envelope'),
        'entity': request.args.get('entity'),
        'category': request.args.get('category'),
    }
    pos_id = request.args.get('position_id')

    with get_db() as conn:
        dates = [r['date'] for r in conn.execute(
            'SELECT DISTINCT date FROM positions ORDER BY date'
        ).fetchall()]
        ref = load_referential(conn)
        history = []

        for date in dates:
            rows         = conn.execute('SELECT * FROM positions WHERE date=?', (date,)).fetchall()
            entity_map   = get_entity_map(conn, date)
            holdings_map = get_holdings_map(conn, [r['id'] for r in rows])
            positions    = [compute_position(dict(r), entity_map, ref, holdings_map) for r in rows]

            if pos_id:
                # Recherche par correspondance : même owner/category/envelope/establishment/entity
                ref_pos = None
                for r in rows:
                    if str(r['id']) == str(pos_id):
                        ref_pos = dict(r)
                        break
                if not ref_pos and not history:
                    # Trouver la position de référence dans n'importe quel snapshot
                    ref_row = conn.execute('SELECT * FROM positions WHERE id=?', (pos_id,)).fetchone()
                    if ref_row:
                        ref_pos = dict(ref_row)
                if ref_pos or history:
                    # Matcher par clé métier
                    rp = ref_pos or history[0].get('_ref', {})
                    matched = [p for p in positions
                               if p['owner'] == rp.get('owner')
                               and p['category'] == rp.get('category')
                               and (p.get('envelope') or '') == (rp.get('envelope') or '')
                               and (p.get('establishment') or '') == (rp.get('establishment') or '')
                               and (p.get('entity') or '') == (rp.get('entity') or '')]
                    net = sum(p['net_attributed'] for p in matched)
                    gross = sum(p['gross_attributed'] for p in matched)
                    entry = {'date': date, 'net': round(net, 2), 'gross': round(gross, 2), 'count': len(matched)}
                    if ref_pos:
                        entry['_ref'] = ref_pos
                    history.append(entry)
                continue

            # Filtrage par critères
            filtered = positions
            for key, val in filters.items():
                if val:
                    filtered = [p for p in filtered if str(p.get(key) or '') == val]

            if not any(filters.values()):
                continue

            net = sum(p['net_attributed'] for p in filtered)
            gross = sum(p['gross_attributed'] for p in filtered)
            history.append({
                'date': date,
                'net': round(net, 2),
                'gross': round(gross, 2),
                'count': len(filtered),
            })

    # Nettoyer les clés internes
    for h in history:
        h.pop('_ref', None)

    return jsonify(history)


@tools_bp.route('/api/simulate', methods=['POST'])
@login_required
@csrf_protect
def simulate():
    """
    Projection simple : montant initial + versement mensuel, rendement annuel, sur N années.
    Retourne la courbe mois par mois.
    """
    d = request.json or {}
    try:
        initial = float(d.get('initial', 0))
        monthly = float(d.get('monthly', 0))
        annual_rate_pct = float(d.get('annual_rate', 5))
        years = int(d.get('years', 10))
    except (ValueError, TypeError):
        return jsonify({'error': 'Paramètres numériques invalides'}), 400
    if years < 1 or years > 50:
        return jsonify({'error': 'Durée entre 1 et 50 ans'}), 400
    if annual_rate_pct < -50 or annual_rate_pct > 100:
        return jsonify({'error': 'Taux annuel entre -50% et 100%'}), 400
    if initial < 0 or initial > 1e12:
        return jsonify({'error': 'Montant initial hors limites'}), 400
    if abs(monthly) > 1e9:
        return jsonify({'error': 'Versement mensuel hors limites'}), 400
    annual_rate = annual_rate_pct / 100

    monthly_rate = (1 + annual_rate) ** (1 / 12) - 1
    points = []
    balance = initial
    total_invested = initial

    for month in range(years * 12 + 1):
        points.append({
            'month': month,
            'balance': round(balance, 2),
            'invested': round(total_invested, 2),
        })
        if month < years * 12:
            balance = balance * (1 + monthly_rate) + monthly
            total_invested += monthly

    return jsonify({
        'points': points,
        'final_balance': points[-1]['balance'],
        'total_invested': points[-1]['invested'],
        'gains': round(points[-1]['balance'] - points[-1]['invested'], 2),
    })


@tools_bp.route('/api/auto-snapshot', methods=['POST'])
@login_required
@csrf_protect
def auto_snapshot():
    """
    Duplique le dernier snapshot à la date du jour (ou une date cible).
    Utilisé pour la création automatique de snapshots périodiques.
    """
    d = request.json or {}
    target_date = d.get('date') or datetime.now().strftime('%Y-%m-%d')

    with get_db() as conn:
        # Acquire write lock before existence check to prevent race condition
        conn.execute('BEGIN IMMEDIATE')

        last = conn.execute(
            'SELECT DISTINCT date FROM positions ORDER BY date DESC LIMIT 1'
        ).fetchone()
        if not last:
            return jsonify({'error': 'Aucun snapshot existant'}), 400

        last_date = last['date']
        if last_date == target_date:
            return jsonify({'error': 'Un snapshot existe déjà à cette date', 'skipped': True}), 200

        existing = conn.execute(
            'SELECT COUNT(*) as cnt FROM positions WHERE date=?', (target_date,)
        ).fetchone()
        if existing['cnt'] > 0:
            return jsonify({'error': 'Un snapshot existe déjà à cette date', 'skipped': True}), 200

        # Copier toutes les positions — pour chaque source on recalcule la valeur
        # effective (incluant les holdings) pour la figer au moment du snapshot.
        source_rows  = conn.execute('SELECT * FROM positions WHERE date=?', (last_date,)).fetchall()
        holdings_map = get_holdings_map(conn, [r['id'] for r in source_rows])
        ref          = load_referential(conn)
        entity_map   = get_entity_map(conn, last_date)
        count = 0
        for r in source_rows:
            p = compute_position(dict(r), entity_map, ref, holdings_map)
            # Si la position a des holdings et pas d'entité, on fige la valeur calculée
            frozen_value = p['value'] if p.get('has_holdings') and not p.get('entity') else r['value']
            conn.execute(
                '''INSERT INTO positions (date, owner, category, envelope, establishment,
                   value, debt, notes, entity, ownership_pct, debt_pct, mobilizable_pct_override)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (target_date, r['owner'], r['category'], r['envelope'], r['establishment'],
                 frozen_value, r['debt'], r['notes'], r['entity'],
                 r['ownership_pct'], r['debt_pct'], r['mobilizable_pct_override'])
            )
            count += 1

        snap_count = snapshot_holdings_to_date(conn, target_date)

    logger.info('Auto-snapshot: %d positions + %d holdings copied from %s to %s',
                count, snap_count, last_date, target_date)
    return jsonify({'ok': True, 'copied': count, 'holdings_snapshots': snap_count,
                    'from_date': last_date, 'to_date': target_date})
