from flask import Blueprint, jsonify, request
from datetime import datetime
import sqlite3
from models import get_entity_map, get_db, validate_number, validate_string, parse_number
from auth import login_required, csrf_protect
from services.snapshot import ecrire_entity_snapshot
from services.montants import centimes, ligne_en_euros, lignes_en_euros

MAX_COMMENT_LENGTH = 2000
MAX_NAME_LENGTH = 200

# Tables qui designent une entite par son nom. Renommer l'entite les suit
# toutes ; en oublier une detachait prets, releves et parts de leur entite.
_TABLES_ENTITE = (
    ('entity_snapshots', 'entity_name'),
    ('positions', 'entity'),
    ('prets', 'entity'),
    ('entite_operations', 'entity'),
    ('entite_parts', 'entity'),
    ('entite_exercices', 'entity'),
    ('entite_soldes_initiaux', 'entity'),
)
# Donnees propres a l'entite qu'une suppression effacerait : on la refuse
# tant qu'il en reste, en disant lesquelles.
_DEPENDANCES = (
    ('prets', 'prêt(s) — rattachez-les à une autre entité ou supprimez-les'),
    ('entite_operations', 'opération(s) bancaire(s) importée(s) — supprimez ses relevés dans « Trésorerie et levier »'),
    ('entite_parts', 'ligne(s) de parts détenues'),
    ('entite_exercices', 'exercice(s) clos'),
)


def _compter(conn, table, nom):
    try:
        return conn.execute(f'SELECT COUNT(*) AS c FROM {table} WHERE entity=?', (nom,)).fetchone()['c']
    except sqlite3.OperationalError:
        return 0                  # table absente (base non migree)

entities_bp = Blueprint('entities', __name__)


@entities_bp.route('/api/entities', methods=['GET'])
@login_required
def get_entities():
    limit  = request.args.get('limit', type=int)
    offset = request.args.get('offset', 0, type=int)
    with get_db() as conn:
        query = 'SELECT * FROM entities ORDER BY name'
        params = []
        if limit is not None:
            query += ' LIMIT ? OFFSET ?'
            params = [limit, offset]
        rows = conn.execute(query, params).fetchall()
    result = []
    for r in rows:
        e = ligne_en_euros('entities', r)
        e['net_assets'] = (e['gross_assets'] or 0) - (e['debt'] or 0)
        result.append(e)
    return jsonify(result)


@entities_bp.route('/api/entities', methods=['POST'])
@login_required
@csrf_protect
def add_entity():
    d = request.get_json(silent=True)
    if not isinstance(d, dict) or not d.get('name') or not isinstance(d.get('name'), str):
        return jsonify({'error': 'Nom requis'}), 400
    if not validate_string(d['name'], MAX_NAME_LENGTH):
        return jsonify({'error': f'Nom trop long ({MAX_NAME_LENGTH} car. max)'}), 400
    if not validate_number(d.get('gross_assets')) or not validate_number(d.get('debt')):
        return jsonify({'error': 'Valeurs numériques invalides'}), 400
    if not validate_string(d.get('comment'), MAX_COMMENT_LENGTH):
        return jsonify({'error': f'Commentaire trop long ({MAX_COMMENT_LENGTH} car. max)'}), 400
    today = datetime.now().strftime('%Y-%m-%d')
    gross = parse_number(d.get('gross_assets'), 0)
    debt  = parse_number(d.get('debt'), 0)
    with get_db() as conn:
        if conn.execute('SELECT 1 FROM entities WHERE name=?', (d['name'],)).fetchone():
            return jsonify({'error': f'Une entité « {d["name"]} » existe déjà'}), 409
        cur = conn.execute(
            '''INSERT INTO entities (name, type, valuation_mode, gross_assets, debt, comment)
               VALUES (?,?,?,?,?,?)''',
            (d['name'], d.get('type'), d.get('valuation_mode'), centimes(gross), centimes(debt), d.get('comment'))
        )
        ecrire_entity_snapshot(conn, d['name'], today, gross, debt)
        row = conn.execute('SELECT * FROM entities WHERE id=?', (cur.lastrowid,)).fetchone()
    e = ligne_en_euros('entities', row)
    e['net_assets'] = (e['gross_assets'] or 0) - (e['debt'] or 0)
    e['snapshot_date'] = today
    return jsonify(e), 201


@entities_bp.route('/api/entities/<int:eid>', methods=['PUT'])
@login_required
@csrf_protect
def update_entity(eid):
    d = request.get_json(silent=True)
    if not isinstance(d, dict) or not d.get('name') or not isinstance(d.get('name'), str):
        return jsonify({'error': 'Nom requis'}), 400
    if not validate_string(d['name'], MAX_NAME_LENGTH):
        return jsonify({'error': f'Nom trop long ({MAX_NAME_LENGTH} car. max)'}), 400
    if not validate_number(d.get('gross_assets')) or not validate_number(d.get('debt')):
        return jsonify({'error': 'Valeurs numériques invalides'}), 400
    if not validate_string(d.get('comment'), MAX_COMMENT_LENGTH):
        return jsonify({'error': f'Commentaire trop long ({MAX_COMMENT_LENGTH} car. max)'}), 400
    today = datetime.now().strftime('%Y-%m-%d')
    gross = parse_number(d.get('gross_assets'), 0)
    debt  = parse_number(d.get('debt'), 0)
    new_name = d['name']
    with get_db() as conn:
        # Fetch old name to cascade rename if changed
        old_row = conn.execute('SELECT name FROM entities WHERE id=?', (eid,)).fetchone()
        if not old_row:
            return jsonify({'error': 'Entité introuvable'}), 404
        old_name = old_row['name']
        if new_name != old_name and conn.execute(
                'SELECT 1 FROM entities WHERE name=? AND id<>?', (new_name, eid)).fetchone():
            return jsonify({'error': f'Une entité « {new_name} » existe déjà'}), 409

        conn.execute(
            '''UPDATE entities SET name=?, type=?, valuation_mode=?,
               gross_assets=?, debt=?, comment=? WHERE id=?''',
            (new_name, d.get('type'), d.get('valuation_mode'), centimes(gross), centimes(debt), d.get('comment'), eid)
        )

        # Le nouveau nom suit dans toutes les tables qui designent l'entite.
        if new_name != old_name:
            for table, col in _TABLES_ENTITE:
                try:
                    conn.execute(f'UPDATE {table} SET {col}=? WHERE {col}=?', (new_name, old_name))
                except sqlite3.OperationalError:
                    pass          # table absente (base non migree)

        ecrire_entity_snapshot(conn, new_name, today, gross, debt)
        row = conn.execute('SELECT * FROM entities WHERE id=?', (eid,)).fetchone()
    e = ligne_en_euros('entities', row)
    e['net_assets'] = (e['gross_assets'] or 0) - (e['debt'] or 0)
    e['snapshot_date'] = today
    return jsonify(e)


@entities_bp.route('/api/entities/<int:eid>', methods=['DELETE'])
@login_required
@csrf_protect
def delete_entity(eid):
    force = request.args.get('force') == '1'
    with get_db() as conn:
        row = conn.execute('SELECT name FROM entities WHERE id=?', (eid,)).fetchone()
        if not row:
            return jsonify({'error': 'Entité introuvable'}), 404
        name = row['name']

        # Prets, releves, parts, exercices : les effacer avec l'entite serait
        # une perte muette. La suppression attend qu'ils soient traites.
        restants = [(n, libelle) for table, libelle in _DEPENDANCES
                    if (n := _compter(conn, table, name))]
        if restants:
            detail = ', '.join(f'{n} {libelle}' for n, libelle in restants)
            return jsonify({
                'error': f'Suppression impossible : {detail} rattaché(s) à « {name} ».',
                'dependances': {table: _compter(conn, table, name) for table, _ in _DEPENDANCES},
                'confirm_required': False,
            }), 409

        # Check for linked positions
        linked = conn.execute(
            'SELECT COUNT(*) as cnt FROM positions WHERE entity=?', (name,)
        ).fetchone()['cnt']

        if linked > 0 and not force:
            return jsonify({
                'error': f'{linked} position(s) liée(s) à cette entité',
                'linked_positions': linked,
                'confirm_required': True,
            }), 409

        # Chaque position liee devient une saisie directe, a la valeur et a la
        # dette de l'entite A SA DATE, quotes-parts conservees. Delier sans plus
        # la laissait a 0 € (sa valeur en base) sur tout l'historique.
        if linked > 0:
            for r in conn.execute('SELECT id, date FROM positions WHERE entity=?', (name,)).fetchall():
                e = get_entity_map(conn, r['date']).get(name) or {'gross_assets': 0, 'debt': 0}
                conn.execute('UPDATE positions SET entity=NULL, value=?, debt=? WHERE id=?',
                             (centimes(e['gross_assets']), centimes(e['debt']), r['id']))

        conn.execute('DELETE FROM entity_snapshots WHERE entity_name=?', (name,))
        conn.execute('DELETE FROM entities WHERE id=?', (eid,))
    return '', 204


@entities_bp.route('/api/entity-snapshots')
@login_required
def get_entity_snapshots():
    entity_name = request.args.get('entity')
    with get_db() as conn:
        if entity_name:
            rows = conn.execute(
                'SELECT * FROM entity_snapshots WHERE entity_name=? ORDER BY date DESC',
                (entity_name,)
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM entity_snapshots ORDER BY entity_name, date DESC'
            ).fetchall()
    return jsonify(lignes_en_euros('entity_snapshots', rows))


@entities_bp.route('/api/entity-snapshots/<int:sid>', methods=['DELETE'])
@login_required
@csrf_protect
def delete_entity_snapshot(sid):
    with get_db() as conn:
        conn.execute('DELETE FROM entity_snapshots WHERE id=?', (sid,))
    return '', 204
