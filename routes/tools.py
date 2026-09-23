import logging
from flask import Blueprint, jsonify, request
from datetime import datetime
from models import (get_db, compute_position, get_entity_map, holdings_a_date,
                    load_referential, validate_date, validate_number,
                    validate_string, parse_number)
from auth import login_required, csrf_protect
from routes.performance import _flux_signed
from services.montants import ligne_en_euros

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
            holdings_map = holdings_a_date(conn, [r['id'] for r in pos_rows], d)
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

        # Flux (regroupés par mois), signes comme partout ailleurs : un
        # retrait saisi en positif s'additionnait aux versements, et dividendes
        # et frais — ni apports ni retraits — gonflaient le total.
        par_mois = {}
        for f in conn.execute('SELECT date, type, amount FROM flux ORDER BY date'):
            m = par_mois.setdefault(f['date'][:7], {'total': 0.0, 'cnt': 0})
            m['total'] += _flux_signed(ligne_en_euros('flux', f))
            m['cnt'] += 1
        for month, m in sorted(par_mois.items()):
            events.append({
                'date': month + '-15',
                'type': 'flux',
                'label': f'{m["cnt"]} flux',
                'value': round(m['total'], 2),
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
            holdings_map = holdings_a_date(conn, [r['id'] for r in rows], date)
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
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        d = {}
    # parse_number refuse nan et inf, que float() acceptait : une simulation
    # a « nan » passait toutes les bornes (toute comparaison a nan est fausse).
    initial = parse_number(d.get('initial', 0))
    monthly = parse_number(d.get('monthly', 0))
    annual_rate_pct = parse_number(d.get('annual_rate', 5))
    years = parse_number(d.get('years', 10))
    if None in (initial, monthly, annual_rate_pct, years) or years != int(years):
        return jsonify({'error': 'Paramètres numériques invalides'}), 400
    years = int(years)
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
    if not validate_date(target_date):
        return jsonify({'error': 'Date invalide (format AAAA-MM-JJ attendu)'}), 400

    from services.snapshot import duplicate_snapshot

    with get_db() as conn:
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

        stats = duplicate_snapshot(conn, last_date, target_date)

    logger.info('Auto-snapshot: %s → %s (%s)', last_date, target_date, stats)
    return jsonify({'ok': True, **stats, 'from_date': last_date, 'to_date': target_date})


@tools_bp.route('/api/snapshots/duplicate', methods=['POST'])
@login_required
@csrf_protect
def duplicate_snapshot_route():
    """Duplique un snapshot (positions ET holdings) d'une date source vers une cible.

    Remplace l'ancien chemin front-end qui recreait les positions une a une via
    POST /api/positions sans copier les holdings — d'ou des actifs vides apres
    duplication. On s'appuie ici sur le helper robuste `duplicate_snapshot`,
    seul point de verite pour copier positions + holdings + figer holdings_snapshots.

    Ecrasement : si la date cible existe deja, ses positions et leurs holdings
    sont purgees d'abord. Le ON DELETE CASCADE n'etant pas actif (PRAGMA
    foreign_keys non positionne sur la connexion), on supprime les holdings
    explicitement pour ne pas laisser d'orphelins.
    """
    d = request.json or {}
    source_date = d.get('source_date')
    target_date = d.get('target_date')
    if not validate_date(source_date) or not validate_date(target_date):
        return jsonify({'error': 'Dates invalides (format AAAA-MM-JJ attendu)'}), 400
    if source_date == target_date:
        return jsonify({'error': 'Les dates source et cible doivent etre differentes'}), 400

    from services.snapshot import duplicate_snapshot

    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')

        src_count = conn.execute(
            'SELECT COUNT(*) AS c FROM positions WHERE date=?', (source_date,)
        ).fetchone()['c']
        if src_count == 0:
            return jsonify({'error': f'Aucune position a la date {source_date}'}), 404

        # Ecrasement de la cible : purge explicite holdings puis positions.
        target_ids = [r['id'] for r in conn.execute(
            'SELECT id FROM positions WHERE date=?', (target_date,)
        ).fetchall()]
        if target_ids:
            placeholders = ','.join('?' * len(target_ids))
            conn.execute(
                f'DELETE FROM holdings WHERE position_id IN ({placeholders})', target_ids
            )
            conn.execute('DELETE FROM positions WHERE date=?', (target_date,))

        stats = duplicate_snapshot(conn, source_date, target_date)

    logger.info('Duplicate snapshot: %s → %s (%s)', source_date, target_date, stats)
    return jsonify({'ok': True, **stats, 'from_date': source_date, 'to_date': target_date})


@tools_bp.route('/api/snapshots/update', methods=['GET'])
@login_required
def preparer_mise_a_jour_route():
    """Ce que l'ecran « Mettre a jour » affiche : les positions de l'arrete
    source, le mode de valorisation de chacune, et les entites qu'elles
    utilisent, a leur valeur de cette date.

    Params : `source` (defaut : dernier arrete), `cible` (defaut : aujourd'hui).
    """
    from services.snapshot import preparer_mise_a_jour
    with get_db() as conn:
        source = request.args.get('source')
        if not source:
            row = conn.execute('SELECT MAX(date) d FROM positions').fetchone()
            source = row['d'] if row else None
        cible = request.args.get('cible') or datetime.now().strftime('%Y-%m-%d')
        if not source:
            return jsonify({'error': 'Aucun arrêté : ajoutez d\u2019abord une position.'}), 404
        if not validate_date(source) or not validate_date(cible):
            return jsonify({'error': 'Dates invalides (format AAAA-MM-JJ attendu)'}), 400
        return jsonify(preparer_mise_a_jour(conn, source, cible))


@tools_bp.route('/api/snapshots/update', methods=['POST'])
@login_required
@csrf_protect
def appliquer_mise_a_jour_route():
    """Cree l'arrete `target_date` depuis `source_date` et y applique les
    soldes saisis — ou modifie `source_date` lui-meme si les deux sont egales.
    Tout ou rien : une seule transaction.

    Corps : {source_date, target_date,
             soldes:  {id_position_source: {value, debt}},
             entites: {nom: {gross_assets, debt}}}
    """
    from services.snapshot import appliquer_mise_a_jour
    d = request.json or {}
    source, cible = d.get('source_date'), d.get('target_date')
    if not validate_date(source) or not validate_date(cible):
        return jsonify({'error': 'Dates invalides (format AAAA-MM-JJ attendu)'}), 400

    soldes, entites = {}, {}
    for pid, v in (d.get('soldes') or {}).items():
        if not str(pid).isdigit() or not isinstance(v, dict):
            return jsonify({'error': f'Position invalide : {pid}'}), 400
        if not validate_number(v.get('value')) or not validate_number(v.get('debt')):
            return jsonify({'error': 'Montant invalide : un solde est un nombre positif'}), 400
        soldes[int(pid)] = {k: parse_number(v[k]) for k in ('value', 'debt') if v.get(k) is not None}
    for nom, v in (d.get('entites') or {}).items():
        if not validate_string(nom, 200) or not isinstance(v, dict):
            return jsonify({'error': 'Entité invalide'}), 400
        if not validate_number(v.get('gross_assets')) or not validate_number(v.get('debt')):
            return jsonify({'error': f'Montant invalide pour l\u2019entité {nom}'}), 400
        # Seuls les champs envoyes changent : une dette absente valait 0, et
        # 80 000 € de dette disparaissaient d'un appel qui ne parlait que du brut.
        # Tresorerie comprise dans la valeur (entite a releves) : un solde de
        # compte peut etre debiteur.
        if not validate_number(v.get('tresorerie'), allow_negative=True):
            return jsonify({'error': f'Trésorerie invalide pour l\u2019entité {nom}'}), 400
        entites[nom] = {k: parse_number(v[k]) for k in ('gross_assets', 'debt', 'tresorerie')
                        if v.get(k) is not None}

    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if not conn.execute('SELECT 1 FROM positions WHERE date=? LIMIT 1', (source,)).fetchone():
            conn.rollback()
            return jsonify({'error': f'Aucun arrêté au {source}'}), 404
        connues = get_entity_map(conn, source)
        for nom, v in entites.items():
            for k in ('gross_assets', 'debt'):
                v.setdefault(k, (connues.get(nom) or {}).get(k, 0))
        try:
            res = appliquer_mise_a_jour(conn, source, cible, soldes, entites)
        except ValueError as e:
            conn.rollback()
            return jsonify({'error': str(e)}), 409
    logger.info('Mise a jour d\'arrete %s -> %s : %s', source, cible, res)
    return jsonify(res)


@tools_bp.route('/api/snapshots/rename', methods=['POST'])
@login_required
@csrf_protect
def rename_snapshot():
    """Renomme la date d'un snapshot ENTIER (positions + entites + holdings_snapshots
    + note) d'une date vers une autre. Deplace le point, sans en creer un nouveau.
    La date cible ne doit pas deja exister (pas de fusion silencieuse).
    """
    d = request.json or {}
    from_date = d.get('from_date')
    to_date = d.get('to_date')
    if not validate_date(from_date) or not validate_date(to_date):
        return jsonify({'error': 'Dates invalides (format AAAA-MM-JJ attendu)'}), 400
    if from_date == to_date:
        return jsonify({'error': 'La nouvelle date doit etre differente'}), 400

    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        src = conn.execute('SELECT COUNT(*) AS c FROM positions WHERE date=?',
                           (from_date,)).fetchone()['c']
        if src == 0:
            return jsonify({'error': f'Aucun snapshot a la date {from_date}'}), 404
        exists = conn.execute('SELECT COUNT(*) AS c FROM positions WHERE date=?',
                              (to_date,)).fetchone()['c']
        if exists > 0:
            return jsonify({'error': f'Un snapshot existe deja au {to_date}'}), 409
        if conn.execute('SELECT 1 FROM snapshot_notes WHERE date=?', (to_date,)).fetchone():
            return jsonify({'error': f'Une note existe deja au {to_date} : supprimez-la ou '
                                     'choisissez une autre date'}), 409
        conn.execute('UPDATE positions SET date=? WHERE date=?', (to_date, from_date))
        # Une valorisation d'entite datee sert a tous les arretes suivants qui
        # n'en ont pas : la deplacer changeait leur valeur. Elle est RECOPIEE a
        # la nouvelle date (celle qui y existait deja l'emporte), jamais retiree.
        # La tresorerie comprise dans la valeur suit : sans elle, l'arrete
        # suivant l'ajouterait une seconde fois.
        conn.execute('''INSERT OR IGNORE INTO entity_snapshots (entity_name, date, gross_assets, debt, tresorerie)
                        SELECT entity_name, ?, gross_assets, debt, tresorerie
                        FROM entity_snapshots WHERE date=?''', (to_date, from_date))
        conn.execute('UPDATE holdings_snapshots SET snapshot_date=? WHERE snapshot_date=?',
                     (to_date, from_date))
        conn.execute('UPDATE snapshot_notes SET date=? WHERE date=?', (to_date, from_date))
        # Les propositions suivent leur arrete : restees a l'ancienne date, elles
        # n'etaient plus jamais purgees et s'affichaient a cote des nouvelles.
        conn.execute('UPDATE rebalance_proposals SET snapshot_date=? WHERE snapshot_date=?',
                     (to_date, from_date))

    logger.info('Rename snapshot: %s → %s (%d positions)', from_date, to_date, src)
    return jsonify({'ok': True, 'from_date': from_date, 'to_date': to_date, 'count': src})


@tools_bp.route('/api/snapshots/delete', methods=['POST'])
@login_required
@csrf_protect
def delete_snapshot():
    """Supprime un snapshot ENTIER a une date (positions + holdings + archives +
    note). L'historique des autres dates est conserve."""
    d = request.json or {}
    date = d.get('date')
    if not validate_date(date):
        return jsonify({'error': 'Date invalide (format AAAA-MM-JJ attendu)'}), 400
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        n = conn.execute('SELECT COUNT(*) AS c FROM positions WHERE date=?',
                         (date,)).fetchone()['c']
        if n == 0:
            return jsonify({'error': f'Aucun snapshot a la date {date}'}), 404
        # ON DELETE CASCADE inactif -> purge explicite des holdings + archives.
        conn.execute('DELETE FROM holdings WHERE position_id IN '
                     '(SELECT id FROM positions WHERE date=?)', (date,))
        conn.execute('DELETE FROM holdings_snapshots WHERE snapshot_date=?', (date,))
        # Les valorisations d'entites restent : elles servent aux arretes
        # suivants, dont la valeur changeait quand on supprimait celui-ci.
        conn.execute('DELETE FROM snapshot_notes WHERE date=?', (date,))
        conn.execute("DELETE FROM rebalance_proposals WHERE snapshot_date=? AND status='pending'", (date,))
        conn.execute('DELETE FROM positions WHERE date=?', (date,))
    logger.info('Delete snapshot: %s (%d positions)', date, n)
    return jsonify({'ok': True, 'date': date, 'count': n})
