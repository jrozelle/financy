"""Route d'import de holdings via PDF (phase 4).

Flux en 2 temps :
1. POST /api/envelope/<position_id>/import-pdf?step=preview
   - Upload du PDF, parsing, renvoie les lignes detectees + warnings.
   - Ne modifie rien en base. L'utilisateur corrige dans la modale UI.
2. POST /api/envelope/<position_id>/import-pdf?step=commit
   - Recoit la liste des lignes validees/corrigees (JSON),
     fait un full replace des holdings de la position.
"""
import logging
from flask import Blueprint, jsonify, request
from models import get_db, validate_isin, validate_number, validate_date
from services.pdf_parser import parse_pdf
from auth import login_required, csrf_protect

logger = logging.getLogger('financy')
pdf_import_bp = Blueprint('pdf_import', __name__)

MAX_PDF_SIZE = 5 * 1024 * 1024  # 5 MB


@pdf_import_bp.route('/api/envelope/<int:position_id>/import-pdf', methods=['POST'])
@login_required
@csrf_protect
def import_pdf(position_id):
    step = (request.args.get('step') or 'preview').lower()
    if step not in ('preview', 'commit'):
        return jsonify({'error': 'step doit etre preview ou commit'}), 400

    with get_db() as conn:
        pos = conn.execute('SELECT id FROM positions WHERE id=?', (position_id,)).fetchone()
    if not pos:
        return jsonify({'error': 'Position introuvable'}), 404

    if step == 'preview':
        return _preview(position_id)
    return _commit(position_id)


def _preview(position_id):
    """Upload du PDF + parsing, renvoie lignes detectees."""
    if 'file' not in request.files:
        return jsonify({'error': 'Aucun fichier recu'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Nom de fichier vide'}), 400
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Seuls les fichiers .pdf sont acceptes'}), 400
    # MIME check (best effort : les navigateurs mentent parfois)
    mime = (file.mimetype or '').lower()
    if mime and mime != 'application/pdf':
        return jsonify({'error': f'Type MIME invalide : {mime}'}), 400

    data = file.read(MAX_PDF_SIZE + 1)
    if len(data) > MAX_PDF_SIZE:
        return jsonify({'error': f'Fichier trop volumineux (>{MAX_PDF_SIZE // 1024 // 1024} Mo)'}), 413
    if not data:
        return jsonify({'error': 'Fichier vide'}), 400

    try:
        result = parse_pdf(data)
    except Exception as e:
        logger.warning('parse_pdf failed: %s', e, exc_info=True)
        return jsonify({'error': "Echec du parsing — le PDF est peut-etre un scan image ou un format inattendu."}), 400

    return jsonify({
        'position_id': position_id,
        **result.to_dict(),
    })


def _commit(position_id):
    """Valide et insere (full replace) les holdings corriges."""
    d = request.json or {}
    items = d.get('holdings')
    if not isinstance(items, list):
        return jsonify({'error': 'Format attendu : {"holdings": [...]}'}), 400
    if len(items) > 500:
        return jsonify({'error': 'Trop de lignes (500 max)'}), 400

    # Validation + normalisation
    validated = []
    for idx, item in enumerate(items, 1):
        raw_isin = (item.get('isin') or '').strip().upper()
        if not validate_isin(raw_isin):
            return jsonify({'error': f'Ligne {idx} : ISIN invalide ({raw_isin!r})'}), 400
        try:
            qty = float(item.get('quantity') or 0)
        except (ValueError, TypeError):
            return jsonify({'error': f'Ligne {idx} : quantite invalide'}), 400
        if qty <= 0:
            return jsonify({'error': f'Ligne {idx} : quantite doit etre > 0'}), 400
        cost = item.get('cost_basis')
        mv = item.get('market_value')
        if cost is not None and not validate_number(cost):
            return jsonify({'error': f'Ligne {idx} : cost_basis invalide'}), 400
        if mv is not None and not validate_number(mv):
            return jsonify({'error': f'Ligne {idx} : market_value invalide'}), 400
        as_of = item.get('as_of_date')
        if as_of and not validate_date(as_of):
            return jsonify({'error': f'Ligne {idx} : as_of_date invalide'}), 400
        validated.append({
            'isin':         raw_isin,
            'name':         (item.get('name') or '').strip()[:200] or None,
            'quantity':     qty,
            'cost_basis':   float(cost) if cost is not None else None,
            'market_value': float(mv) if mv is not None else None,
            'as_of_date':   as_of,
            'is_priceable': item.get('is_priceable'),
        })

    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM holdings WHERE position_id=?', (position_id,))
        for item in validated:
            isin = item['isin']
            existing = conn.execute('SELECT isin FROM securities WHERE isin=?', (isin,)).fetchone()
            is_pseudo = isin.startswith(('FONDS_EUROS_', 'CUSTOM_'))
            is_priceable = item['is_priceable']
            if is_priceable is None:
                is_priceable = 0 if is_pseudo else 1
            else:
                is_priceable = 0 if not is_priceable else 1
            if not existing:
                conn.execute(
                    '''INSERT INTO securities
                       (isin, name, currency, is_priceable, data_source)
                       VALUES (?,?,'EUR',?,'pdf-import')''',
                    (isin, item['name'], is_priceable)
                )
            elif item['name']:
                # Renseigne le nom si on l'a extrait du PDF et qu'il etait vide
                conn.execute(
                    '''UPDATE securities SET name=COALESCE(NULLIF(name,''), ?),
                       updated_at=CURRENT_TIMESTAMP WHERE isin=?''',
                    (item['name'], isin)
                )
            conn.execute(
                '''INSERT INTO holdings
                   (position_id, isin, quantity, cost_basis, market_value, as_of_date)
                   VALUES (?,?,?,?,?,?)''',
                (position_id, isin, item['quantity'],
                 item['cost_basis'], item['market_value'], item['as_of_date'])
            )

        holdings = conn.execute(
            '''SELECT h.*, s.name AS sec_name, s.ticker AS sec_ticker,
                      s.currency AS sec_currency, s.is_priceable AS sec_is_priceable
               FROM holdings h LEFT JOIN securities s ON s.isin = h.isin
               WHERE h.position_id=? ORDER BY h.id''',
            (position_id,)
        ).fetchall()

    logger.info('PDF import commit: position_id=%d, %d holdings',
                position_id, len(validated))
    return jsonify({
        'position_id': position_id,
        'count': len(validated),
        'holdings': [dict(r) for r in holdings],
    })
