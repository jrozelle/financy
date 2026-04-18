"""Routes du module de conseil patrimonial (phase 6 : profil, objectifs, allocation)."""
import logging
from datetime import datetime
from flask import Blueprint, jsonify, request
from models import (get_db, compute_position, get_entity_map, get_holdings_map,
                    load_referential,
                    validate_string, validate_number, validate_pct, validate_date)
from services.advisor.allocation import (target_allocation, compute_actual_allocation,
                                         compute_gap, load_matrix)
from auth import login_required, csrf_protect

logger = logging.getLogger('financy')
advisor_bp = Blueprint('advisor', __name__)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _owner_exists(conn, owner):
    ref = load_referential(conn)
    return owner in ref.get('owners', [])


def _get_profile_row(conn, owner):
    row = conn.execute(
        'SELECT * FROM owner_profiles WHERE owner=?', (owner,)
    ).fetchone()
    return dict(row) if row else None


def _normalize_profile_dict(d):
    """Convertit les booleans stockes en int vers bool pour l'UI."""
    if not d:
        return d
    out = dict(d)
    for k in ('has_lbo', 'main_residence_owned'):
        if k in out and out[k] is not None:
            out[k] = bool(out[k])
    return out


# ─── CRUD profil ─────────────────────────────────────────────────────────────

@advisor_bp.route('/api/advisor/profiles', methods=['GET'])
@login_required
def list_profiles():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM owner_profiles ORDER BY owner').fetchall()
    return jsonify([_normalize_profile_dict(dict(r)) for r in rows])


@advisor_bp.route('/api/advisor/profiles/<owner>', methods=['GET'])
@login_required
def get_profile(owner):
    with get_db() as conn:
        row = _get_profile_row(conn, owner)
    if not row:
        return jsonify({'error': 'Profil introuvable'}), 404
    return jsonify(_normalize_profile_dict(row))


VALID_EMPLOYMENTS = {'salarie', 'TNS', 'fonction_publique', 'retraite', 'autre', ''}


@advisor_bp.route('/api/advisor/profiles/<owner>', methods=['PUT'])
@login_required
@csrf_protect
def upsert_profile(owner):
    owner = (owner or '').strip()
    if not validate_string(owner, 100) or not owner:
        return jsonify({'error': 'Propriétaire invalide'}), 400
    with get_db() as conn:
        if not _owner_exists(conn, owner):
            return jsonify({'error': 'Propriétaire inconnu du referentiel'}), 400

    d = request.json or {}
    horizon = d.get('horizon_years')
    if horizon is not None and (not validate_number(horizon) or float(horizon) < 0 or float(horizon) > 100):
        return jsonify({'error': 'horizon_years invalide (0-100)'}), 400
    risk = d.get('risk_tolerance')
    if risk is not None:
        try:
            risk = int(risk)
        except (ValueError, TypeError):
            return jsonify({'error': 'risk_tolerance invalide'}), 400
        if risk < 1 or risk > 5:
            return jsonify({'error': 'risk_tolerance entre 1 et 5'}), 400
    employment = d.get('employment_type') or ''
    if employment not in VALID_EMPLOYMENTS:
        return jsonify({'error': f'employment_type invalide ({employment})'}), 400
    pension_age = d.get('pension_age')
    if pension_age is not None and (not validate_number(pension_age) or float(pension_age) < 18 or float(pension_age) > 120):
        return jsonify({'error': 'pension_age invalide'}), 400
    children = d.get('children_count')
    if children is not None:
        try:
            children = int(children)
        except (ValueError, TypeError):
            return jsonify({'error': 'children_count invalide'}), 400
        if children < 0 or children > 20:
            return jsonify({'error': 'children_count invalide'}), 400
    notes = d.get('notes')
    if not validate_string(notes, 2000):
        return jsonify({'error': 'Notes trop longues'}), 400

    with get_db() as conn:
        conn.execute(
            '''INSERT INTO owner_profiles (
                 owner, horizon_years, risk_tolerance, employment_type,
                 has_lbo, children_count, main_residence_owned,
                 pension_age, notes, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)
               ON CONFLICT(owner) DO UPDATE SET
                 horizon_years=excluded.horizon_years,
                 risk_tolerance=excluded.risk_tolerance,
                 employment_type=excluded.employment_type,
                 has_lbo=excluded.has_lbo,
                 children_count=excluded.children_count,
                 main_residence_owned=excluded.main_residence_owned,
                 pension_age=excluded.pension_age,
                 notes=excluded.notes,
                 updated_at=CURRENT_TIMESTAMP''',
            (owner,
             int(horizon) if horizon is not None else None,
             risk, employment or None,
             1 if d.get('has_lbo') else 0,
             children if children is not None else 0,
             1 if d.get('main_residence_owned') else 0,
             int(pension_age) if pension_age is not None else None,
             notes)
        )
        row = _get_profile_row(conn, owner)
    return jsonify(_normalize_profile_dict(row))


@advisor_bp.route('/api/advisor/profiles/<owner>', methods=['DELETE'])
@login_required
@csrf_protect
def delete_profile(owner):
    with get_db() as conn:
        cur = conn.execute('DELETE FROM owner_profiles WHERE owner=?', (owner,))
        conn.execute('DELETE FROM owner_objectives WHERE owner=?', (owner,))
    if cur.rowcount == 0:
        return jsonify({'error': 'Profil introuvable'}), 404
    return '', 204


# ─── CRUD objectifs ──────────────────────────────────────────────────────────

@advisor_bp.route('/api/advisor/profiles/<owner>/objectives', methods=['GET'])
@login_required
def list_objectives(owner):
    with get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM owner_objectives WHERE owner=? ORDER BY priority DESC, id',
            (owner,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


def _validate_objective(d):
    if not validate_string(d.get('label'), 200) or not d.get('label'):
        return 'Libelle requis'
    if d.get('target_amount') is not None and not validate_number(d.get('target_amount')):
        return 'target_amount invalide'
    if d.get('horizon_years') is not None and not validate_number(d.get('horizon_years')):
        return 'horizon_years invalide'
    p = d.get('priority')
    if p is not None:
        try:
            p = int(p)
        except (ValueError, TypeError):
            return 'priority invalide'
        if p < 1 or p > 5:
            return 'priority entre 1 et 5'
    return None


@advisor_bp.route('/api/advisor/profiles/<owner>/objectives', methods=['POST'])
@login_required
@csrf_protect
def add_objective(owner):
    d = request.json or {}
    err = _validate_objective(d)
    if err:
        return jsonify({'error': err}), 400
    with get_db() as conn:
        if not _owner_exists(conn, owner):
            return jsonify({'error': 'Propriétaire inconnu'}), 400
        cur = conn.execute(
            '''INSERT INTO owner_objectives (owner, label, target_amount, horizon_years, priority)
               VALUES (?,?,?,?,?)''',
            (owner, d['label'].strip(),
             float(d['target_amount']) if d.get('target_amount') is not None else None,
             int(d['horizon_years']) if d.get('horizon_years') is not None else None,
             int(d.get('priority')) if d.get('priority') is not None else 3)
        )
        row = conn.execute('SELECT * FROM owner_objectives WHERE id=?', (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@advisor_bp.route('/api/advisor/objectives/<int:oid>', methods=['PATCH'])
@login_required
@csrf_protect
def update_objective(oid):
    d = request.json or {}
    err = _validate_objective(d) if ('label' in d or 'target_amount' in d
                                     or 'horizon_years' in d or 'priority' in d) else None
    if 'label' in d and (not d.get('label') or not validate_string(d['label'], 200)):
        return jsonify({'error': 'Libelle requis'}), 400
    with get_db() as conn:
        row = conn.execute('SELECT * FROM owner_objectives WHERE id=?', (oid,)).fetchone()
        if not row:
            return jsonify({'error': 'Objectif introuvable'}), 404
        fields, params = [], []
        for key, cast in (('label', str), ('target_amount', float),
                          ('horizon_years', int), ('priority', int)):
            if key in d:
                val = d[key]
                if val is not None:
                    try:
                        val = cast(val)
                    except (ValueError, TypeError):
                        return jsonify({'error': f'{key} invalide'}), 400
                fields.append(f'{key}=?'); params.append(val)
        if not fields:
            return jsonify({'error': 'Aucun champ a mettre a jour'}), 400
        params.append(oid)
        conn.execute(f'UPDATE owner_objectives SET {", ".join(fields)} WHERE id=?', params)
        row = conn.execute('SELECT * FROM owner_objectives WHERE id=?', (oid,)).fetchone()
    return jsonify(dict(row))


@advisor_bp.route('/api/advisor/objectives/<int:oid>', methods=['DELETE'])
@login_required
@csrf_protect
def delete_objective(oid):
    with get_db() as conn:
        cur = conn.execute('DELETE FROM owner_objectives WHERE id=?', (oid,))
    if cur.rowcount == 0:
        return jsonify({'error': 'Objectif introuvable'}), 404
    return '', 204


# ─── Allocation cible vs actuelle ────────────────────────────────────────────

@advisor_bp.route('/api/advisor/profiles/<owner>/allocation', methods=['GET'])
@login_required
def get_allocation(owner):
    """Retourne l'allocation cible (derivee du profil) + actuelle + ecarts.

    Query params :
    - date : snapshot a utiliser (defaut : dernier)
    """
    date = request.args.get('date')
    with get_db() as conn:
        profile = _get_profile_row(conn, owner)
        if not profile:
            return jsonify({'error': 'Profil introuvable'}), 404
        matrix = load_matrix(conn)

        if not date:
            r = conn.execute(
                'SELECT MAX(date) AS d FROM positions WHERE owner=?', (owner,)
            ).fetchone()
            date = r['d']
        rows = conn.execute(
            'SELECT * FROM positions WHERE owner=? AND date=?', (owner, date)
        ).fetchall() if date else []

        entity_map   = get_entity_map(conn, date) if date else {}
        ref          = load_referential(conn)
        holdings_map = get_holdings_map(conn, [r['id'] for r in rows]) if rows else {}
        positions = [compute_position(dict(r), entity_map, ref, holdings_map) for r in rows]

    target, adjustments = target_allocation(_normalize_profile_dict(profile), matrix)
    actual = compute_actual_allocation(positions)
    total_eur = sum(max(0, p.get('net_attributed') or 0) for p in positions)
    gap = compute_gap(target, actual, total_eur)

    return jsonify({
        'owner':        owner,
        'snapshot_date': date,
        'profile':      _normalize_profile_dict(profile),
        'target':       target,
        'actual':       actual,
        'total_eur':    round(total_eur, 2),
        'gap':          gap,
        'adjustments':  adjustments,
    })
