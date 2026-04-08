from flask import Blueprint, jsonify, request
from datetime import datetime
from io import BytesIO
from models import get_db
from auth import login_required, csrf_protect

import_export_bp = Blueprint('import_export', __name__)


@import_export_bp.route('/api/import', methods=['POST'])
@login_required
@csrf_protect
def import_xlsx():
    if 'file' not in request.files:
        return jsonify({'error': 'Aucun fichier reçu'}), 400
    file = request.files['file']
    if not file.filename.endswith('.xlsx'):
        return jsonify({'error': 'Seuls les fichiers .xlsx sont acceptés'}), 400

    try:
        import openpyxl
        wb = openpyxl.load_workbook(BytesIO(file.read()), data_only=True)
        imported = 0

        with get_db() as conn:
            # Positions
            ws = wb['Positions']
            for row in ws.iter_rows(min_row=2, values_only=True):
                if len(row) < 7:
                    continue
                date_val, owner, category = row[0], row[1], row[2]
                envelope, establishment   = row[3], row[4]
                value, debt               = row[5], row[6]
                notes                     = row[8] if len(row) > 8 else None
                entity                    = row[9] if len(row) > 9 else None
                ownership_pct_raw = row[10] if len(row) > 10 else None
                debt_pct_raw      = row[11] if len(row) > 11 else None

                if not date_val or not owner:
                    continue
                if value is None and debt is None and envelope is None and not entity:
                    continue

                if entity:
                    value = 0
                    debt  = 0
                    ownership_pct = ownership_pct_raw if ownership_pct_raw is not None else 1.0
                    debt_pct = debt_pct_raw if debt_pct_raw is not None else ownership_pct
                else:
                    ownership_pct = ownership_pct_raw if ownership_pct_raw is not None else 1.0
                    debt_pct      = debt_pct_raw      if debt_pct_raw      is not None else 1.0

                if isinstance(date_val, datetime):
                    date_str = date_val.strftime('%Y-%m-%d')
                else:
                    date_str = str(date_val)[:10]

                existing = conn.execute(
                    '''SELECT id FROM positions
                       WHERE date=? AND owner=? AND category=?
                         AND COALESCE(envelope,'')=? AND COALESCE(entity,'')=?''',
                    (date_str, owner, category or '', envelope or '', entity or '')
                ).fetchone()
                if existing:
                    continue

                conn.execute(
                    '''INSERT INTO positions
                       (date, owner, category, envelope, establishment,
                        value, debt, notes, entity, ownership_pct, debt_pct)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (date_str, owner, category or '',
                     envelope, establishment,
                     value or 0, debt or 0,
                     notes, entity,
                     ownership_pct, debt_pct)
                )
                imported += 1

            # Flux
            if 'Flux' in wb.sheetnames:
                wf = wb['Flux']
                flux_imported = 0
                for row in wf.iter_rows(min_row=2, values_only=True):
                    if len(row) < 5:
                        continue
                    date_val, owner, envelope, ftype, amount = row[0], row[1], row[2], row[3], row[4]
                    notes = row[5] if len(row) > 5 else None
                    if not date_val or not owner or amount is None:
                        continue
                    if isinstance(date_val, datetime):
                        date_str = date_val.strftime('%Y-%m-%d')
                    else:
                        date_str = str(date_val)[:10]
                    conn.execute(
                        'INSERT INTO flux (date, owner, envelope, type, amount, notes) VALUES (?,?,?,?,?,?)',
                        (date_str, owner, envelope, ftype, amount, notes)
                    )
                    flux_imported += 1

            # Entités
            entities_imported = 0
            if 'Entites' in wb.sheetnames:
                we = wb['Entites']
                for row in we.iter_rows(min_row=2, values_only=True):
                    if len(row) < 2:
                        continue
                    name = row[0]
                    if not name:
                        continue
                    etype          = row[1] if len(row) > 1 else None
                    valuation_mode = row[2] if len(row) > 2 else None
                    gross_assets   = row[3] if len(row) > 3 else 0
                    debt           = row[4] if len(row) > 4 else 0
                    comment        = row[6] if len(row) > 6 else None
                    existing = conn.execute(
                        'SELECT id FROM entities WHERE name=?', (name,)
                    ).fetchone()
                    if existing:
                        conn.execute(
                            '''UPDATE entities SET type=?, valuation_mode=?,
                               gross_assets=?, debt=?, comment=? WHERE name=?''',
                            (etype, valuation_mode, gross_assets or 0, debt or 0, comment, name)
                        )
                    else:
                        conn.execute(
                            '''INSERT INTO entities (name, type, valuation_mode, gross_assets, debt, comment)
                               VALUES (?,?,?,?,?,?)''',
                            (name, etype, valuation_mode, gross_assets or 0, debt or 0, comment)
                        )
                    today = datetime.now().strftime('%Y-%m-%d')
                    conn.execute(
                        '''INSERT OR REPLACE INTO entity_snapshots (entity_name, date, gross_assets, debt)
                           VALUES (?,?,?,?)''',
                        (name, today, gross_assets or 0, debt or 0)
                    )
                    entities_imported += 1

        return jsonify({'imported': imported, 'entities': entities_imported})

    except Exception as e:
        return jsonify({'error': str(e)}), 400


@import_export_bp.route('/api/import-json', methods=['POST'])
@login_required
@csrf_protect
def import_json():
    data = request.json
    if not data:
        return jsonify({'error': 'Corps JSON manquant'}), 400

    imported = {'positions': 0, 'flux': 0, 'entities': 0, 'entity_snapshots': 0}

    with get_db() as conn:
        for e in data.get('entities', []):
            name = e.get('name')
            if not name:
                continue
            existing = conn.execute('SELECT id FROM entities WHERE name=?', (name,)).fetchone()
            if existing:
                conn.execute(
                    'UPDATE entities SET type=?, valuation_mode=?, gross_assets=?, debt=?, comment=? WHERE name=?',
                    (e.get('type'), e.get('valuation_mode'), e.get('gross_assets', 0), e.get('debt', 0), e.get('comment'), name)
                )
            else:
                conn.execute(
                    'INSERT INTO entities (name, type, valuation_mode, gross_assets, debt, comment) VALUES (?,?,?,?,?,?)',
                    (name, e.get('type'), e.get('valuation_mode'), e.get('gross_assets', 0), e.get('debt', 0), e.get('comment'))
                )
            imported['entities'] += 1

        for s in data.get('entity_snapshots', []):
            if not s.get('entity_name') or not s.get('date'):
                continue
            conn.execute(
                'INSERT OR REPLACE INTO entity_snapshots (entity_name, date, gross_assets, debt) VALUES (?,?,?,?)',
                (s['entity_name'], s['date'], s.get('gross_assets', 0), s.get('debt', 0))
            )
            imported['entity_snapshots'] += 1

        for p in data.get('positions', []):
            if not p.get('date') or not p.get('owner'):
                continue
            existing = conn.execute(
                '''SELECT id FROM positions WHERE date=? AND owner=? AND category=?
                   AND COALESCE(envelope,'')=? AND COALESCE(entity,'')=?''',
                (p['date'], p['owner'], p.get('category', ''), p.get('envelope') or '', p.get('entity') or '')
            ).fetchone()
            if existing:
                continue
            conn.execute(
                '''INSERT INTO positions (date, owner, category, envelope, establishment,
                   value, debt, notes, entity, ownership_pct, debt_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (p['date'], p['owner'], p.get('category', ''), p.get('envelope'), p.get('establishment'),
                 p.get('value', 0), p.get('debt', 0), p.get('notes'), p.get('entity'),
                 p.get('ownership_pct', 1.0), p.get('debt_pct', 1.0))
            )
            imported['positions'] += 1

        for f in data.get('flux', []):
            if not f.get('date') or not f.get('owner') or f.get('amount') is None:
                continue
            conn.execute(
                'INSERT INTO flux (date, owner, envelope, type, amount, notes) VALUES (?,?,?,?,?,?)',
                (f['date'], f['owner'], f.get('envelope'), f.get('type'), f['amount'], f.get('notes'))
            )
            imported['flux'] += 1

    return jsonify(imported)


@import_export_bp.route('/api/export')
@login_required
def export_data():
    with get_db() as conn:
        positions = [dict(r) for r in conn.execute(
            'SELECT * FROM positions ORDER BY date, owner'
        ).fetchall()]
        flux = [dict(r) for r in conn.execute(
            'SELECT * FROM flux ORDER BY date'
        ).fetchall()]
        entities = [dict(r) for r in conn.execute(
            'SELECT * FROM entities ORDER BY name'
        ).fetchall()]
        entity_snapshots = [dict(r) for r in conn.execute(
            'SELECT * FROM entity_snapshots ORDER BY entity_name, date'
        ).fetchall()]
    return jsonify({
        'positions': positions,
        'flux': flux,
        'entities': entities,
        'entity_snapshots': entity_snapshots,
    })


@import_export_bp.route('/api/reset', methods=['POST'])
@login_required
@csrf_protect
def reset_db():
    with get_db() as conn:
        conn.executescript(
            'DELETE FROM positions; DELETE FROM flux; '
            'DELETE FROM entities; DELETE FROM entity_snapshots;'
        )
    return jsonify({'ok': True})
