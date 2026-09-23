import logging
from flask import Blueprint, jsonify, request
from datetime import datetime
from io import BytesIO
from models import get_db, validate_date, validate_isin, parse_number, get_db_path
from auth import login_required, csrf_protect
from services.backups import create_db_backup
from services.montants import ligne_en_centimes, ligne_en_euros
from services.snapshot import ecrire_entity_snapshot

MAX_IMPORT_ROWS = 10000
MAX_NOTE_LENGTH = 2000
RESET_CONFIRMATION = 'VIDER'

logger = logging.getLogger('financy')

import_export_bp = Blueprint('import_export', __name__)


_ENTETES_ETABLISSEMENT = {'establishment', 'etablissement', 'pos_establishment'}


def _normaliser_entete(v):
    import unicodedata
    t = unicodedata.normalize('NFD', str(v or '')).strip().lower()
    return ''.join(c for c in t if unicodedata.category(c) != 'Mn')


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
        backup = create_db_backup(get_db_path())
    except Exception:
        logger.exception('Import XLSX annule : copie prealable impossible')
        return jsonify({'error': 'Copie préalable de la base impossible, import annulé'}), 500

    try:
        import openpyxl
        wb = openpyxl.load_workbook(BytesIO(file.read()), data_only=True)
        imported = 0
        skipped = 0
        # Positions creees par cet import : seules elles recoivent des lignes
        # de titres. Sous une position deja presente, elles doublaient sa valeur.
        creees = set()

        def _parse_date(val):
            if isinstance(val, datetime):
                return val.strftime('%Y-%m-%d')
            s = str(val)[:10] if val else None
            return s if s and validate_date(s) else None

        def _safe_float(val, default=0):
            return parse_number(val, default)

        def _safe_pct(val, default=1.0):
            f = _safe_float(val, default)
            return max(0.0, min(f, 1.0))

        def _safe_str(val, max_len=500):
            if val is None:
                return None
            s = str(val)[:max_len]
            return s

        with get_db() as conn:
            # Positions
            ws = wb['Positions']
            for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True)):
                if i >= MAX_IMPORT_ROWS:
                    break
                if len(row) < 7:
                    continue
                date_val, owner, category = row[0], row[1], row[2]
                envelope, establishment   = row[3], row[4]
                value, debt               = row[5], row[6]
                notes                     = row[8] if len(row) > 8 else None
                entity                    = row[9] if len(row) > 9 else None
                ownership_pct_raw = row[10] if len(row) > 10 else None
                debt_pct_raw      = row[11] if len(row) > 11 else None

                date_str = _parse_date(date_val)
                if not date_str or not owner:
                    skipped += 1
                    continue
                if value is None and debt is None and envelope is None and not entity:
                    continue

                owner    = _safe_str(owner, 100)
                category = _safe_str(category, 100) or ''
                envelope = _safe_str(envelope, 100)
                establishment = _safe_str(establishment, 200)
                notes    = _safe_str(notes, MAX_NOTE_LENGTH)
                entity   = _safe_str(entity, 200)

                if entity:
                    value = 0
                    debt  = 0
                    ownership_pct = _safe_pct(ownership_pct_raw, 1.0)
                    debt_pct = _safe_pct(debt_pct_raw, ownership_pct)
                else:
                    value = _safe_float(value, 0)
                    debt  = _safe_float(debt, 0)
                    ownership_pct = _safe_pct(ownership_pct_raw, 1.0)
                    debt_pct      = _safe_pct(debt_pct_raw, 1.0)

                # L'etablissement fait partie de l'identite : deux contrats d'un
                # titulaire chez deux assureurs ne sont pas un doublon.
                existing = conn.execute(
                    '''SELECT id FROM positions
                       WHERE date=? AND owner=? AND category=?
                         AND COALESCE(envelope,'')=? AND COALESCE(entity,'')=?
                         AND COALESCE(establishment,'')=?''',
                    (date_str, owner, category, envelope or '', entity or '', establishment or '')
                ).fetchone()
                if existing:
                    continue

                cur = conn.execute(
                    '''INSERT INTO positions
                       (date, owner, category, envelope, establishment,
                        value, debt, notes, entity, ownership_pct, debt_pct)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (date_str, owner, category,
                     envelope, establishment,
                     value, debt,
                     notes, entity,
                     ownership_pct, debt_pct)
                )
                creees.add(cur.lastrowid)
                imported += 1

            # Flux
            if 'Flux' in wb.sheetnames:
                wf = wb['Flux']
                flux_imported = 0
                flux_vus = set()
                for i, row in enumerate(wf.iter_rows(min_row=2, values_only=True)):
                    if i >= MAX_IMPORT_ROWS:
                        break
                    if len(row) < 5:
                        continue
                    date_val, owner, envelope, ftype, amount = row[0], row[1], row[2], row[3], row[4]
                    notes = row[5] if len(row) > 5 else None
                    date_str = _parse_date(date_val)
                    if not date_str or not owner or amount is None:
                        continue
                    ligne = {'date': date_str, 'owner': _safe_str(owner, 100), 'envelope': _safe_str(envelope, 100),
                             'type': _safe_str(ftype, 50), 'amount': _safe_float(amount, 0),
                             'notes': _safe_str(notes, MAX_NOTE_LENGTH)}
                    # Reimporter le meme classeur doublait tous les flux.
                    if _existe(conn, 'flux', ligne, list(ligne), flux_vus):
                        continue
                    cur = conn.execute(
                        'INSERT INTO flux (date, owner, envelope, type, amount, notes) VALUES (?,?,?,?,?,?)',
                        tuple(ligne_en_centimes('flux', ligne).values()))
                    flux_vus.add(cur.lastrowid)
                    flux_imported += 1

            # Entités
            entities_imported = 0
            if 'Entites' in wb.sheetnames:
                we = wb['Entites']
                for i, row in enumerate(we.iter_rows(min_row=2, values_only=True)):
                    if i >= 1000:
                        break
                    if len(row) < 2:
                        continue
                    name = row[0]
                    if not name:
                        continue
                    name           = _safe_str(name, 200)
                    etype          = _safe_str(row[1], 50) if len(row) > 1 else None
                    valuation_mode = _safe_str(row[2], 50) if len(row) > 2 else None
                    gross_assets   = _safe_float(row[3] if len(row) > 3 else 0)
                    debt           = _safe_float(row[4] if len(row) > 4 else 0)
                    comment        = _safe_str(row[6], MAX_NOTE_LENGTH) if len(row) > 6 else None
                    existing = conn.execute(
                        'SELECT id FROM entities WHERE name=?', (name,)
                    ).fetchone()
                    if existing:
                        conn.execute(
                            '''UPDATE entities SET type=?, valuation_mode=?,
                               gross_assets=?, debt=?, comment=? WHERE name=?''',
                            (etype, valuation_mode, gross_assets, debt, comment, name)
                        )
                    else:
                        conn.execute(
                            '''INSERT INTO entities (name, type, valuation_mode, gross_assets, debt, comment)
                               VALUES (?,?,?,?,?,?)''',
                            (name, etype, valuation_mode, gross_assets, debt, comment)
                        )
                    today = datetime.now().strftime('%Y-%m-%d')
                    ecrire_entity_snapshot(conn, name, today, gross_assets, debt)
                    entities_imported += 1

            # Securities (optionnel, avant Holdings pour que les FK existent)
            securities_imported = 0
            if 'Securities' in wb.sheetnames:
                ws_sec = wb['Securities']
                for i, row in enumerate(ws_sec.iter_rows(min_row=2, values_only=True)):
                    if i >= MAX_IMPORT_ROWS:
                        break
                    if not row or not row[0]:
                        continue
                    raw_isin = str(row[0]).strip().upper()
                    if not validate_isin(raw_isin):
                        continue
                    name         = _safe_str(row[1] if len(row) > 1 else None, 200)
                    ticker       = _safe_str(row[2] if len(row) > 2 else None, 50)
                    currency     = _safe_str(row[3] if len(row) > 3 else 'EUR', 10) or 'EUR'
                    asset_class  = _safe_str(row[4] if len(row) > 4 else None, 50)
                    is_priceable = row[5] if len(row) > 5 else 1
                    is_priceable = 0 if str(is_priceable).lower() in ('0', 'false', 'non', 'no', '') else 1
                    if raw_isin.startswith(('FONDS_EUROS_', 'CUSTOM_')):
                        is_priceable = 0
                    existing = conn.execute(
                        'SELECT isin FROM securities WHERE isin=?', (raw_isin,)
                    ).fetchone()
                    if existing:
                        conn.execute(
                            '''UPDATE securities SET name=?, ticker=?, currency=?,
                               asset_class=?, is_priceable=?, updated_at=CURRENT_TIMESTAMP
                               WHERE isin=?''',
                            (name, ticker, currency, asset_class, is_priceable, raw_isin)
                        )
                    else:
                        conn.execute(
                            '''INSERT INTO securities
                               (isin, name, ticker, currency, asset_class, is_priceable, data_source)
                               VALUES (?,?,?,?,?,?,'xlsx')''',
                            (raw_isin, name, ticker, currency, asset_class, is_priceable)
                        )
                    securities_imported += 1

            # Holdings : rattachement par clef (date, owner, category, envelope,
            # entity) et, si la feuille a une colonne d'etablissement, par
            # l'etablissement aussi : sans lui, les titres de deux contrats d'un
            # titulaire chez deux assureurs allaient tous au premier.
            holdings_imported = 0
            if 'Holdings' in wb.sheetnames:
                ws_h = wb['Holdings']
                entete = next(ws_h.iter_rows(min_row=1, max_row=1, values_only=True), ()) or ()
                col_etab = next((k for k, v in enumerate(entete)
                                 if _normaliser_entete(v) in _ENTETES_ETABLISSEMENT), None)
                for i, row in enumerate(ws_h.iter_rows(min_row=2, values_only=True)):
                    if i >= MAX_IMPORT_ROWS:
                        break
                    if not row or len(row) < 7:
                        continue
                    pos_date = _parse_date(row[0])
                    pos_owner = _safe_str(row[1], 100)
                    pos_category = _safe_str(row[2], 100) or ''
                    pos_envelope = _safe_str(row[3], 100) or ''
                    pos_entity = _safe_str(row[4], 200) or ''
                    raw_isin = str(row[5]).strip().upper() if row[5] else ''
                    quantity = _safe_float(row[6], 0)
                    cost_basis = _safe_float(row[7], 0) if len(row) > 7 and row[7] is not None else None
                    market_value = _safe_float(row[8], 0) if len(row) > 8 and row[8] is not None else None
                    as_of_date = _parse_date(row[9]) if len(row) > 9 else None

                    if not pos_date or not pos_owner or not raw_isin or quantity <= 0:
                        continue
                    if not validate_isin(raw_isin):
                        continue

                    sql = '''SELECT id FROM positions
                             WHERE date=? AND owner=? AND category=?
                               AND COALESCE(envelope,'')=? AND COALESCE(entity,'')=?'''
                    params = [pos_date, pos_owner, pos_category, pos_envelope, pos_entity]
                    if col_etab is not None:
                        sql += " AND COALESCE(establishment,'')=?"
                        params.append(_safe_str(row[col_etab] if len(row) > col_etab else None, 200) or '')
                    pos = conn.execute(sql + ' ORDER BY id', params).fetchone()
                    if not pos or pos['id'] not in creees:
                        continue  # parente introuvable, ou deja presente : ses titres y sont

                    # Upsert auto de la security si absente
                    existing = conn.execute(
                        'SELECT isin FROM securities WHERE isin=?', (raw_isin,)
                    ).fetchone()
                    if not existing:
                        is_priceable = 0 if raw_isin.startswith(('FONDS_EUROS_', 'CUSTOM_')) else 1
                        conn.execute(
                            '''INSERT INTO securities
                               (isin, currency, is_priceable, data_source)
                               VALUES (?,'EUR',?,'xlsx-auto')''',
                            (raw_isin, is_priceable)
                        )
                    conn.execute(
                        '''INSERT INTO holdings
                           (position_id, isin, quantity, cost_basis, market_value, as_of_date)
                           VALUES (?,?,?,?,?,?)''',
                        (pos['id'], raw_isin, quantity, cost_basis, market_value, as_of_date)
                    )
                    holdings_imported += 1

        logger.info('Import XLSX: %d positions, %d entités, %d securities, %d holdings, %d skipped',
                    imported, entities_imported, securities_imported, holdings_imported, skipped)
        return jsonify({
            'imported': imported,
            'backup': backup['filename'],
            'entities': entities_imported,
            'securities': securities_imported,
            'holdings': holdings_imported,
            'skipped': skipped,
        })

    except Exception as e:
        logger.error('Import XLSX failed: %s', e, exc_info=True)
        return jsonify({'error': "Échec de l'import — vérifiez le format du fichier."}), 400


# ─── Export / import JSON ───────────────────────────────────────────────────
#
# L'export est une SAUVEGARDE : toutes les tables utiles, toutes leurs
# colonnes, identifiants compris. L'import FUSIONNE en surete : copie de la
# base d'abord, puis ce qui existe l'emporte et n'est jamais double.
#
# Relevé a la revue du 23/09/2026 sur la base de prod : reimporter un export
# dans la meme base doublait les montants (900 000 → 1 150 000 €), les flux
# (120 000 → 240 000 €) ; l'aller-retour export → reset → import perdait 14
# positions sur 162, faute d'etablissement dans la cle, et rattachait les
# titres de deux contrats au premier ; il oubliait le libelle, les surcharges
# de liquidite, l'etablissement des flux, et toute la table des transactions.

FORMAT_EXPORT = 2

# Tables recopiees telles quelles, cle d'unicite pour ne pas doubler.
_TABLES_SIMPLES = {
    'entity_snapshots': ('entity_name', 'date'),
    'fx_rates':         ('pair', 'date'),
    'price_history':    ('isin', 'date'),
    'owner_profiles':   ('owner',),
    'securities':       ('isin',),
    'entities':         ('name',),
}
# Prets, releves, parts et exercices des entites, dates d'effet des contrats :
# (cle d'unicite, champs requis). Une cle peut comprendre une colonne vide
# (banque, etablissement), d'ou la liste des champs requis a part.
_TABLES_CLE_NATURELLE = {
    'entite_operations':      (('entity', 'banque', 'compte', 'date', 'montant', 'libelle'),
                               ('entity', 'date', 'libelle', 'montant')),
    'entite_parts':           (('entity', 'nom'), ('entity', 'nom', 'parts')),
    'entite_exercices':       (('entity', 'fin'), ('entity', 'fin', 'resultat')),
    'entite_soldes_initiaux': (('entity', 'banque', 'compte'), ('entity', 'date', 'solde')),
    'contrats':               (('owner', 'envelope', 'establishment'), ('owner', 'envelope')),
}
# Colonnes numeriques de ces tables : un texte y fausserait les sommes.
_NUMERIQUES = {'montant', 'parts', 'montant_souscrit', 'prix_souscription', 'prix_retrait',
               'resultat', 'solde', 'taux', 'capital', 'interets', 'assurance', 'crd'}
# Un pret se reconnait a son libelle, son entite, ses dates et son montant ;
# son echeancier le suit, et seulement s'il est cree par cet import.
_CLE_PRET = ('libelle', 'entity', 'debut', 'fin', 'montant')
# Tables sans cle naturelle : un doublon se reconnait a toutes ses colonnes metier.
_TABLES_DEDOUBLONNEES = ('flux', 'transactions', 'owner_objectives')
_TECHNIQUES = {'id', 'created_at', 'updated_at'}
# Cle d'identite d'une position : l'etablissement en fait partie — deux
# assurances-vie d'un meme titulaire chez deux assureurs ne sont pas une.
_CLE_POSITION = ('date', 'owner', 'category', 'envelope', 'establishment', 'entity', 'label')
# Configuration exportable ; les reglages (cle API) n'en sont pas.
_CONFIG_EXPORTEE = ('referential', 'allocation_targets', 'user_alerts', 'wealth_target',
                    'benchmark_isin')


def _vide(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _nombres(ligne):
    """Copie de la ligne, colonnes numeriques converties ; None si l'une
    d'elles n'est pas un nombre."""
    out = dict(ligne)
    for c in _NUMERIQUES & set(ligne):
        if ligne[c] is None:
            continue
        n = parse_number(ligne[c])
        if n is None:
            return None
        out[c] = n
    return out


def _colonnes(conn, table):
    try:
        return [r['name'] for r in conn.execute(f'PRAGMA table_info({table})')]
    except Exception:
        return []


def _propre(v):
    """Valeur importable : texte borne, nombre tel quel."""
    if isinstance(v, str):
        return v[:MAX_NOTE_LENGTH]
    if isinstance(v, (int, float)) or v is None:
        return v
    return str(v)[:MAX_NOTE_LENGTH]


def _inserer(conn, table, ligne, cols, ignorer=False):
    # L'import parle en euros, comme l'export ; la base, en centimes pour les
    # tables de montants.COLONNES. Ici seulement, et dans _existe.
    ligne = ligne_en_centimes(table, ligne)
    champs = [c for c in cols if c not in _TECHNIQUES and c in ligne]
    if not champs:
        return None
    verbe = 'INSERT OR IGNORE' if ignorer else 'INSERT'
    cur = conn.execute(f'{verbe} INTO {table} ({", ".join(champs)}) VALUES ({", ".join("?" * len(champs))})',
                       [_propre(ligne[c]) for c in champs])
    return cur.lastrowid if cur.rowcount else None


def _existe(conn, table, ligne, cles, consommes=None):
    """Une ligne DEJA en base qui correspond, et pas encore appariee.

    Deux lignes identiques de l'export (deux Livret A d'une meme titulaire chez
    le meme etablissement, deux versements egaux le meme jour) sont deux
    lignes : chacune ne se reconnait que dans une ligne existante distincte,
    et jamais dans une ligne que cet import vient de creer.
    """
    ligne = ligne_en_centimes(table, ligne)
    cond = ' AND '.join(f'COALESCE({c}, \'\') = COALESCE(?, \'\')' for c in cles)
    for r in conn.execute(f'SELECT rowid FROM {table} WHERE {cond} ORDER BY rowid',
                          [_propre(ligne.get(c)) for c in cles]):
        if consommes is None:
            return r
        if r[0] not in consommes:
            consommes.add(r[0])
            return r
    return None


@import_export_bp.route('/api/import-json', methods=['POST'])
@login_required
@csrf_protect
def import_json():
    data = request.json
    if not data:
        return jsonify({'error': 'Corps JSON manquant'}), 400
    if not isinstance(data, dict):
        return jsonify({'error': 'Objet JSON attendu'}), 400

    try:
        backup = create_db_backup(get_db_path())
    except Exception:
        logger.exception('Import JSON annule : copie prealable impossible')
        return jsonify({'error': 'Copie préalable de la base impossible, import annulé'}), 500

    rapport = {'positions': 0, 'positions_existantes': 0, 'holdings': 0, 'holdings_snapshots': 0,
               'flux': 0, 'doublons': 0, 'skipped': 0, 'backup': backup['filename']}

    def _liste(cle):
        v = data.get(cle) or []
        return v[:MAX_IMPORT_ROWS] if isinstance(v, list) else []

    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')

        # Tables a cle naturelle : ce qui existe l'emporte.
        for table, cles in _TABLES_SIMPLES.items():
            cols = _colonnes(conn, table)
            n = 0
            for ligne in _liste(table):
                if not isinstance(ligne, dict) or any(not ligne.get(c) for c in cles):
                    rapport['skipped'] += 1
                    continue
                if table == 'securities':
                    ligne = dict(ligne, isin=str(ligne['isin']).strip().upper())
                    if not validate_isin(ligne['isin']):
                        rapport['skipped'] += 1
                        continue
                if 'date' in cles and not validate_date(ligne.get('date')):
                    rapport['skipped'] += 1
                    continue
                if _existe(conn, table, ligne, cles):
                    continue
                if _inserer(conn, table, ligne, cols, ignorer=True):
                    n += 1
            rapport[table] = n

        # Positions : correspondance des identifiants source → cible.
        pcols = _colonnes(conn, 'positions')
        correspondance, nouvelles = {}, set()
        pos_consommees = set()
        for p in _liste('positions'):
            if not isinstance(p, dict) or not validate_date(p.get('date')) or not p.get('owner'):
                rapport['skipped'] += 1
                continue
            p = dict(p, category=p.get('category') or '')
            for k in ('ownership_pct', 'debt_pct'):
                if p.get(k) is not None:
                    p[k] = max(0.0, min(parse_number(p[k], 1.0), 1.0))
            deja = _existe(conn, 'positions', p, _CLE_POSITION, pos_consommees)
            if deja:
                rapport['positions_existantes'] += 1
                if p.get('id') is not None:
                    correspondance[p['id']] = deja[0]
                continue
            nid = _inserer(conn, 'positions', p, pcols)
            pos_consommees.add(nid)          # une ligne creee ici n'apparie rien
            rapport['positions'] += 1
            if p.get('id') is not None:
                correspondance[p['id']] = nid
            nouvelles.add(nid)

        # Lignes de titres : seulement sous les positions CREEES par cet import.
        # Sous une position existante, elles doubleraient sa valeur.
        hcols = _colonnes(conn, 'holdings')
        for h in _liste('holdings'):
            if not isinstance(h, dict):
                continue
            cible = correspondance.get(h.get('position_id'))
            if cible is None and h.get('pos_date'):          # export au format 1
                ancienne = {'date': h.get('pos_date'), 'owner': h.get('pos_owner'),
                            'category': h.get('pos_category') or '', 'envelope': h.get('pos_envelope') or None,
                            'establishment': h.get('pos_establishment'), 'entity': h.get('pos_entity') or None,
                            'label': h.get('pos_label')}
                r = _existe(conn, 'positions', ancienne,
                            [c for c in _CLE_POSITION if ancienne.get(c) is not None or c in ('envelope', 'entity')])
                cible = r[0] if r else None
            isin = str(h.get('isin') or '').strip().upper()
            if cible is None or cible not in nouvelles or not validate_isin(isin):
                rapport['skipped'] += 1
                continue
            if not conn.execute('SELECT 1 FROM securities WHERE isin=?', (isin,)).fetchone():
                conn.execute("INSERT INTO securities (isin, currency, is_priceable, data_source) VALUES (?, 'EUR', ?, 'json-auto')",
                             (isin, 0 if isin.startswith(('FONDS_EUROS_', 'CUSTOM_')) else 1))
            _inserer(conn, 'holdings', dict(h, position_id=cible, isin=isin), hcols)
            rapport['holdings'] += 1

        scols = _colonnes(conn, 'holdings_snapshots')
        for s in _liste('holdings_snapshots'):
            cible = correspondance.get(s.get('position_id')) if isinstance(s, dict) else None
            if cible is None or cible not in nouvelles or not validate_date(s.get('snapshot_date')):
                rapport['skipped'] += 1
                continue
            _inserer(conn, 'holdings_snapshots', dict(s, position_id=cible), scols)
            rapport['holdings_snapshots'] += 1

        # Releves, parts, exercices des entites et contrats : ce qui existe
        # l'emporte, sur leur cle naturelle.
        from services.tresorerie_entite import NATURES
        for table, (cles, requis) in _TABLES_CLE_NATURELLE.items():
            cols = _colonnes(conn, table)
            n = 0
            for ligne in _liste(table):
                ligne = _nombres(ligne) if isinstance(ligne, dict) else None
                if (ligne is None or any(_vide(ligne.get(c)) for c in requis)
                        or any(c in ligne and not _vide(ligne[c]) and not validate_date(ligne[c])
                               for c in ('date', 'fin', 'debut', 'date_prix', 'date_effet'))):
                    rapport['skipped'] += 1
                    continue
                if table == 'entite_operations' and ligne.get('nature') not in NATURES:
                    ligne['nature'] = 'autre'
                if not cols or _existe(conn, table, ligne, cles):
                    continue
                if _inserer(conn, table, ligne, cols, ignorer=True):
                    n += 1
            rapport[table] = n

        # Prets : correspondance des identifiants, echeancier sous les seuls
        # prets crees ici — sous un pret existant, il le doublerait.
        prcols = _colonnes(conn, 'prets')
        prets_source, prets_nouveaux = {}, set()
        rapport['prets'] = rapport['pret_echeances'] = 0
        for p in _liste('prets'):
            p = _nombres(p) if isinstance(p, dict) else None
            if p is None or _vide(p.get('libelle')) or not prcols:
                rapport['skipped'] += 1
                continue
            deja = _existe(conn, 'prets', p, _CLE_PRET)
            if deja:
                nid = deja[0]
            else:
                nid = _inserer(conn, 'prets', p, prcols)
                prets_nouveaux.add(nid)
                rapport['prets'] += 1
            if p.get('id') is not None:
                prets_source[p['id']] = nid
        ecols = _colonnes(conn, 'pret_echeances')
        for e in _liste('pret_echeances'):
            e = _nombres(e) if isinstance(e, dict) else None
            cible = prets_source.get(e.get('pret_id')) if e else None
            if (cible is None or cible not in prets_nouveaux or not validate_date(e.get('date'))
                    or any(e.get(c) is None for c in ('rang', 'capital', 'crd'))):
                rapport['skipped'] += 1
                continue
            if _inserer(conn, 'pret_echeances', dict(e, pret_id=cible), ecols, ignorer=True):
                rapport['pret_echeances'] += 1

        # Flux, transactions, objectifs : un doublon a toutes ses colonnes metier.
        for table in _TABLES_DEDOUBLONNEES:
            cols = _colonnes(conn, table)
            metier = [c for c in cols if c not in _TECHNIQUES]
            consommes, n = set(), 0
            for ligne in _liste(table):
                if not isinstance(ligne, dict) or ('date' in cols and not validate_date(ligne.get('date'))):
                    rapport['skipped'] += 1
                    continue
                if table == 'flux' and (not ligne.get('owner') or ligne.get('amount') is None):
                    rapport['skipped'] += 1
                    continue
                if _existe(conn, table, ligne, [c for c in metier if c in ligne], consommes):
                    rapport['doublons'] += 1
                    continue
                consommes.add(_inserer(conn, table, ligne, cols))
                n += 1
            rapport[table] = n

        notes = data.get('snapshot_notes') or {}
        if isinstance(notes, dict):
            for date, texte in notes.items():
                if validate_date(date) and texte:
                    conn.execute('INSERT OR IGNORE INTO snapshot_notes (date, notes) VALUES (?, ?)',
                                 (date, str(texte)[:MAX_NOTE_LENGTH]))

        # Configuration : seulement si absente — l'existante l'emporte.
        config = data.get('config') or {}
        if isinstance(config, dict):
            for cle, valeur in config.items():
                if cle in _CONFIG_EXPORTEE and isinstance(valeur, str):
                    conn.execute('INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)', (cle, valeur))

    logger.info('Import JSON : %s', rapport)
    return jsonify(rapport)


@import_export_bp.route('/api/export')
@login_required
def export_data():
    tables = ('positions', 'flux', 'entities', 'entity_snapshots', 'securities', 'holdings',
              'holdings_snapshots', 'transactions', 'fx_rates', 'price_history',
              'owner_profiles', 'owner_objectives', 'prets', 'pret_echeances',
              'entite_operations', 'entite_parts', 'entite_exercices', 'entite_soldes_initiaux',
              'contrats')
    out = {'format': FORMAT_EXPORT, 'exporte_le': datetime.now().isoformat(timespec='seconds')}
    with get_db() as conn:
        for t in tables:
            try:
                out[t] = [ligne_en_euros(t, r) for r in conn.execute(f'SELECT * FROM {t}')]
            except Exception:
                out[t] = []          # table non migree
        out['snapshot_notes'] = {r['date']: r['notes'] for r in conn.execute(
            'SELECT date, notes FROM snapshot_notes ORDER BY date')}
        out['config'] = {r['key']: r['value'] for r in conn.execute(
            f"SELECT key, value FROM config WHERE key IN ({','.join('?' * len(_CONFIG_EXPORTEE))})",
            _CONFIG_EXPORTEE)}
    return jsonify(out)


@import_export_bp.route('/api/reset', methods=['POST'])
@login_required
@csrf_protect
def reset_db():
    data = request.get_json(silent=True) or {}
    confirmation = str(data.get('confirm') or '').strip().upper()
    if confirmation != RESET_CONFIRMATION:
        return jsonify({
            'error': f'Confirmation requise : tapez {RESET_CONFIRMATION}',
            'confirmation': RESET_CONFIRMATION,
        }), 400

    try:
        backup = create_db_backup(get_db_path())
    except FileNotFoundError:
        return jsonify({'error': 'Base de données introuvable'}), 404
    except Exception:
        logger.exception('Database reset aborted — backup failed')
        return jsonify({'error': 'Backup préalable impossible, reset annulé'}), 500

    # « Vider toute la base » : transactions, cours de change, profils et
    # propositions du conseil restaient, et reapparaissaient apres un import.
    tables = [
        'positions', 'flux', 'entities', 'entity_snapshots', 'snapshot_notes',
        'holdings', 'holdings_snapshots', 'price_history', 'securities',
        'transactions', 'fx_rates', 'owner_profiles', 'owner_objectives',
        'rebalance_proposals', 'allocation_targets', 'macro_snapshots',
        # Prets et donnees des entites : restes en base, ils se rattachaient
        # aux entites du meme nom importees ensuite.
        'pret_echeances', 'prets', 'entite_operations', 'entite_parts', 'entite_exercices',
        'entite_soldes_initiaux', 'contrats',
    ]
    deleted = {}
    with get_db() as conn:
        for t in tables:
            try:
                row = conn.execute(f'SELECT COUNT(*) AS c FROM {t}').fetchone()
                deleted[t] = int(row['c']) if row else 0
                conn.execute(f'DELETE FROM {t}')
            except Exception:
                deleted[t] = 0  # Table peut ne pas exister si migration non appliquée
    total = sum(deleted.values())
    logger.warning('Database reset — %d rows across %d tables deleted; backup=%s',
                   total, len([v for v in deleted.values() if v]), backup['filename'])
    return jsonify({'ok': True, 'total': total, 'deleted': deleted, 'backup': backup})
