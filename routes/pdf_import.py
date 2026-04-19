"""Route d'import de holdings via PDF ou CSV (phase 4).

Flux en 2 temps :
1. POST /api/envelope/<position_id>/import-pdf?step=preview
   - Upload du PDF ou CSV, parsing, renvoie les lignes detectees + warnings.
   - Ne modifie rien en base. L'utilisateur corrige dans la modale UI.
2. POST /api/envelope/<position_id>/import-pdf?step=commit
   - Recoit la liste des lignes validees/corrigees (JSON),
     fait un full replace des holdings de la position.
"""
import logging
from flask import Blueprint, jsonify, request
from models import get_db, validate_isin, validate_number, validate_date
from services.parsers import parse_pdf, parse_csv, parse_pasted_text
from services.parsers.common import PdfEncryptedError, PdfImageScanError
from services.securities import upsert_security
from auth import login_required, csrf_protect

logger = logging.getLogger('financy')
pdf_import_bp = Blueprint('pdf_import', __name__)

MAX_PDF_SIZE = 5 * 1024 * 1024  # 5 MB


def _enrich_with_prices(result):
    """Lookup live prices for lines missing market_value."""
    try:
        from services.prices import get_provider
        provider = get_provider()
    except Exception:
        result.warnings.append('Impossible de charger le provider de cours.')
        return

    enriched = 0
    for line in result.lines:
        if line.market_value is not None or not line.quantity:
            continue
        try:
            ticker, _ = provider.resolve_ticker(line.isin, name=line.name)
            if not ticker:
                result.warnings.append(f'{line.isin} : ticker non trouve.')
                continue
            price_data = provider.fetch_last_price(ticker)
            if not price_data:
                result.warnings.append(f'{line.isin} : cours indisponible.')
                continue
            price, price_date = price_data
            line.unit_price = round(price, 4)
            line.market_value = round(line.quantity * price, 2)
            line.confidence = min(line.confidence + 0.1, 1.0)
            enriched += 1
        except Exception as e:
            logger.debug('Price lookup failed for %s: %s', line.isin, e)

    result.total_market_value = sum(l.market_value or 0 for l in result.lines)
    if enriched:
        logger.info('Price lookup: enriched %d/%d lines', enriched, len(result.lines))


@pdf_import_bp.route('/api/envelope/<int:position_id>/import-paste', methods=['POST'])
@login_required
@csrf_protect
def import_paste(position_id):
    """Parse du texte colle depuis le navigateur."""
    with get_db() as conn:
        pos = conn.execute('SELECT id FROM positions WHERE id=?', (position_id,)).fetchone()
    if not pos:
        return jsonify({'error': 'Position introuvable'}), 404
    d = request.json or {}
    text = d.get('text', '')
    if not text or len(text) < 20:
        return jsonify({'error': 'Texte trop court ou vide.'}), 400
    try:
        result = parse_pasted_text(text)
    except Exception as e:
        return jsonify({'error': f'Echec du parsing : {e}'}), 400
    return jsonify({'position_id': position_id, **result.to_dict()})


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
    """Upload du PDF ou CSV + parsing, renvoie lignes detectees."""
    if 'file' not in request.files:
        return jsonify({'error': 'Aucun fichier recu'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Nom de fichier vide'}), 400

    filename_lower = file.filename.lower()
    is_csv = filename_lower.endswith('.csv')
    is_pdf = filename_lower.endswith('.pdf')
    if not is_csv and not is_pdf:
        return jsonify({'error': 'Formats acceptes : .pdf ou .csv'}), 400

    data = file.read(MAX_PDF_SIZE + 1)
    if len(data) > MAX_PDF_SIZE:
        return jsonify({'error': f'Fichier trop volumineux (>{MAX_PDF_SIZE // 1024 // 1024} Mo)'}), 413
    if not data:
        return jsonify({'error': 'Fichier vide'}), 400

    try:
        if is_csv:
            result = parse_csv(data)
        else:
            result = parse_pdf(data)
    except PdfEncryptedError as e:
        return jsonify({'error': str(e)}), 400
    except PdfImageScanError as e:
        return jsonify({'error': str(e)}), 422
    except Exception as e:
        logger.warning('parse failed: %s', e, exc_info=True)
        kind = 'CSV' if is_csv else 'PDF'
        return jsonify({'error': f"Echec du parsing {kind} — verifiez le format du fichier."}), 400

    # Price lookup for formats without prices (e.g. attestation de detention)
    if result.needs_price_lookup:
        _enrich_with_prices(result)

    return jsonify({
        'position_id': position_id,
        **result.to_dict(),
    })


# Mapping asset_class → categorie position pour l'auto-split
_ASSET_CLASS_TO_CATEGORY = {
    'etf':         'Actions',
    'action':      'Actions',
    'opcvm':       'Actions',
    'obligation':  'Obligations',
    'fonds_euros': 'Fond Euro',
    'scpi':        'Immobilier',
    'sci':         'Immobilier',
    'cash':        'Cash & dépôts',
}


def _infer_category(isin, name):
    """Infere la categorie position depuis l'ISIN/nom du holding."""
    from services.securities import _infer_asset_class
    ac = _infer_asset_class(name)
    return _ASSET_CLASS_TO_CATEGORY.get(ac, 'Actions')


def _find_or_create_position(conn, base_pos, category):
    """Trouve une position compagnon (meme date/owner/envelope/etablissement)
    avec la bonne categorie, ou en cree une."""
    row = conn.execute(
        '''SELECT id FROM positions
           WHERE date=? AND owner=? AND envelope=? AND category=?
                 AND COALESCE(establishment,'')=?''',
        (base_pos['date'], base_pos['owner'], base_pos['envelope'],
         category, base_pos['establishment'] or '')
    ).fetchone()
    if row:
        return row['id']
    cur = conn.execute(
        '''INSERT INTO positions (date, owner, category, envelope, establishment, value, debt)
           VALUES (?,?,?,?,?,0,0)''',
        (base_pos['date'], base_pos['owner'], category,
         base_pos['envelope'], base_pos['establishment'])
    )
    logger.info('Auto-split: created position %s/%s/%s (id=%d)',
                base_pos['owner'], base_pos['envelope'], category, cur.lastrowid)
    return cur.lastrowid


def _commit(position_id):
    """Valide et insere (full replace) les holdings corriges.

    Auto-split : si les holdings ont des asset_classes mixtes (ex: ETF + fonds euro),
    les lignes sont reparties dans des positions compagnons par categorie.
    """
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

        # Upsert toutes les securities
        for item in validated:
            upsert_security(
                conn, item['isin'],
                name=item.get('name') or None,
                is_priceable=item.get('is_priceable'),
                data_source='pdf-import',
            )

        # Lire la position de base
        base_pos = conn.execute(
            'SELECT * FROM positions WHERE id=?', (position_id,)
        ).fetchone()
        base_pos = dict(base_pos)

        # Grouper les holdings par categorie inferee
        by_category = {}
        for item in validated:
            cat = _infer_category(item['isin'], item['name'])
            by_category.setdefault(cat, []).append(item)

        categories = list(by_category.keys())
        touched_positions = []

        if len(categories) == 1:
            # Pas de split — import simple dans la position d'origine
            conn.execute('DELETE FROM holdings WHERE position_id=?', (position_id,))
            for item in validated:
                conn.execute(
                    '''INSERT INTO holdings
                       (position_id, isin, quantity, cost_basis, market_value, as_of_date)
                       VALUES (?,?,?,?,?,?)''',
                    (position_id, item['isin'], item['quantity'],
                     item['cost_basis'], item['market_value'], item['as_of_date'])
                )
            touched_positions.append(position_id)
        else:
            # Auto-split : repartir dans des positions par categorie
            for cat, cat_items in by_category.items():
                if cat == base_pos['category']:
                    pid = position_id
                else:
                    pid = _find_or_create_position(conn, base_pos, cat)
                conn.execute('DELETE FROM holdings WHERE position_id=?', (pid,))
                for item in cat_items:
                    conn.execute(
                        '''INSERT INTO holdings
                           (position_id, isin, quantity, cost_basis, market_value, as_of_date)
                           VALUES (?,?,?,?,?,?)''',
                        (pid, item['isin'], item['quantity'],
                         item['cost_basis'], item['market_value'], item['as_of_date'])
                    )
                touched_positions.append(pid)

        # Retourner les holdings de la position principale
        holdings = conn.execute(
            '''SELECT h.*, s.name AS sec_name, s.ticker AS sec_ticker,
                      s.currency AS sec_currency, s.is_priceable AS sec_is_priceable
               FROM holdings h LEFT JOIN securities s ON s.isin = h.isin
               WHERE h.position_id=? ORDER BY h.id''',
            (position_id,)
        ).fetchall()

    split_msg = ''
    if len(categories) > 1:
        split_msg = f' (auto-split en {len(categories)} categories : {", ".join(categories)})'
    logger.info('Import commit: position_id=%d, %d holdings%s',
                position_id, len(validated), split_msg)
    return jsonify({
        'position_id': position_id,
        'count': len(validated),
        'holdings': [dict(r) for r in holdings],
        'split_categories': categories if len(categories) > 1 else None,
    })
