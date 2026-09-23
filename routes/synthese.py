import json
from flask import Blueprint, jsonify, request
from datetime import datetime
from models import (get_db, compute_position, get_entity_map, get_holdings_map,
                    load_referential, freeze_holdings_prices)
from auth import login_required, csrf_protect

synthese_bp = Blueprint('synthese', __name__)

# Regroupement des categories de positions en 3 poches patrimoniales pour la
# synthese brut/net. Toute categorie non listee tombe dans "Patrimoine autre".
MACRO_ORDER = ['Patrimoine financier', 'Patrimoine immobilier', 'Patrimoine autre']
MACRO_BUCKETS = {
    'Patrimoine financier': {
        'Cash & dépôts', 'Monétaire', 'Obligations', 'Actions',
        'Fond Euro', 'Produits Structurés', 'Crypto',
    },
    'Patrimoine immobilier': {'Immobilier', 'SCPI'},
    # 'Société' est l'ancien nom de 'Parts sociales' : les deux sont listes,
    # une base non migree restant classee comme avant.
    'Patrimoine autre': {'Objets de valeur', 'Société', 'Parts sociales', 'Autre'},
}


def _macro_bucket(category):
    for bucket, cats in MACRO_BUCKETS.items():
        if category in cats:
            return bucket
    return 'Patrimoine autre'


def _freeze_holdings(holdings_map):
    """Alias historique de models.freeze_holdings_prices (voir ce helper)."""
    return freeze_holdings_prices(holdings_map)


@synthese_bp.route('/api/synthese')
@login_required
def get_synthese():
    date = request.args.get('date')
    with get_db() as conn:
        latest_date = conn.execute('SELECT MAX(date) as d FROM positions').fetchone()['d']
        if not date:
            date = latest_date
        if not date:
            return jsonify({'date': None})
        rows         = conn.execute('SELECT * FROM positions WHERE date=?', (date,)).fetchall()
        entity_map   = get_entity_map(conn, date)
        ref          = load_referential(conn)
        # Cours du jour pour le snapshot le plus recent ; market_value figee des
        # holdings pour l'historique -> vraie valeur enregistree a chaque date
        # (et non positions.value qui peut etre perimee sur une ligne a holdings).
        holdings_map = get_holdings_map(conn, [r['id'] for r in rows])
        if date != latest_date:
            _freeze_holdings(holdings_map)
        linked       = conn.execute(
            '''SELECT entity,
                      SUM(ownership_pct) as total_own,
                      SUM(debt_pct)      as total_debt
               FROM positions WHERE date=? AND entity IS NOT NULL
               GROUP BY entity''', (date,)
        ).fetchall()

    positions = [compute_position(dict(r), entity_map, ref, holdings_map) for r in rows]

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
    # Les categories du referentiel dans son ordre, puis celles que portent
    # des positions sans y figurer : une position « Parts » de 150 000 €,
    # categorie retiree du referentiel, disparaissait de la repartition.
    cats = list(ref['categories']) + sorted({p['category'] for p in positions
                                              if p['category'] and p['category'] not in ref['categories']})
    for cat in cats:
        ops = [p for p in positions if p['category'] == cat]
        if ops:
            totals_by_category[cat] = {
                'net':      sum(p['net_attributed'] for p in ops),
                'gross':    sum(p['gross_attributed'] for p in ops),
                # La dette manquait ici alors qu'elle existe pour les poches et
                # les personnes : sans elle, impossible de lire le levier par
                # categorie — c'est pourtant la ou il se joue (immobilier).
                'debt':     sum(p['debt_attributed'] for p in ops),
                'by_owner': {o: sum(p['net_attributed'] for p in ops if p['owner'] == o)
                             for o in owners},
                'by_owner_gross': {o: sum(p['gross_attributed'] for p in ops if p['owner'] == o)
                                   for o in owners},
            }

    # Par enveloppe : quatrieme angle de repartition, absent jusqu'ici alors que
    # c'est la maille a laquelle on ouvre et ferme un contrat.
    totals_by_envelope = {}
    for p in positions:
        env = p.get('envelope') or 'Sans enveloppe'
        t = totals_by_envelope.setdefault(
            env, {'gross': 0.0, 'net': 0.0, 'debt': 0.0, 'by_owner': {}})
        t['gross'] += p['gross_attributed'] or 0
        t['net']   += p['net_attributed'] or 0
        t['debt']  += p['debt_attributed'] or 0
        # Le detail par titulaire manquait ici seul, si bien que la carte
        # Repartition affichait les totaux de la famille sous un filtre
        # nominatif : elle n'avait rien d'autre a lire.
        ob = t['by_owner'].setdefault(p['owner'], {'gross': 0.0, 'net': 0.0, 'debt': 0.0})
        ob['gross'] += p['gross_attributed'] or 0
        ob['net']   += p['net_attributed'] or 0
        ob['debt']  += p['debt_attributed'] or 0

    # Synthese en 3 poches patrimoniales, brut (gross_attributed) et net
    # (net_attributed = brut - dette attribuee), avec detail par owner.
    totals_by_macro = {b: {'gross': 0.0, 'net': 0.0, 'debt': 0.0, 'by_owner': {}}
                       for b in MACRO_ORDER}
    for p in positions:
        m = totals_by_macro[_macro_bucket(p['category'])]
        m['gross'] += p['gross_attributed']
        m['net']   += p['net_attributed']
        m['debt']  += p['debt_attributed']
        ob = m['by_owner'].setdefault(p['owner'], {'gross': 0.0, 'net': 0.0, 'debt': 0.0})
        ob['gross'] += p['gross_attributed']
        ob['net']   += p['net_attributed']
        ob['debt']  += p['debt_attributed']

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
        """Retourne les totaux famille + par owner pour un snapshot donne."""
        with get_db() as c:
            snap_rows        = c.execute('SELECT * FROM positions WHERE date=?', (snap_date,)).fetchall()
            snap_entity_map  = get_entity_map(c, snap_date)
            snap_ref         = load_referential(c)
            snap_holdings    = get_holdings_map(c, [r['id'] for r in snap_rows])
            if snap_date != latest_date:
                _freeze_holdings(snap_holdings)
        snap_positions = [compute_position(dict(r), snap_entity_map, snap_ref, snap_holdings) for r in snap_rows]
        fam = {
            'net':   sum(p['net_attributed'] for p in snap_positions),
            'gross': sum(p['gross_attributed'] for p in snap_positions),
            'debt':  sum(p['debt_attributed'] for p in snap_positions),
            'mob':   sum(p['mobilizable_value'] for p in snap_positions),
        }
        by_owner = {}
        for o in set(p['owner'] for p in snap_positions):
            ops = [p for p in snap_positions if p['owner'] == o]
            by_owner[o] = {
                'net':   sum(p['net_attributed'] for p in ops),
                'gross': sum(p['gross_attributed'] for p in ops),
                'debt':  sum(p['debt_attributed'] for p in ops),
                'mob':   sum(p['mobilizable_value'] for p in ops),
            }
        return fam, by_owner

    def _calc_delta(cur, prev):
        if not cur or not prev:
            return None
        return {
            'net_delta':   cur['net'] - prev['net'],
            'net_pct':     ((cur['net'] - prev['net']) / abs(prev['net']) * 100) if prev['net'] != 0 else None,
            'gross_delta': cur['gross'] - prev['gross'],
            'debt_delta':  cur['debt'] - prev['debt'],
            'mob_delta':   cur['mob'] - prev['mob'],
        }

    def _build_variation(prev_date_str):
        prev_fam, prev_by_owner = _snapshot_totals(prev_date_str)
        cur_mob = sum(t['mobilizable'] for t in totals_by_owner.values())
        cur_fam = {**family, 'mob': cur_mob}
        result = _calc_delta(cur_fam, prev_fam)
        if result:
            result['prev_date'] = prev_date_str
            result['by_owner'] = {}
            for o in owners:
                cur_o = totals_by_owner.get(o, {'net': 0, 'gross': 0, 'debt': 0, 'mobilizable': 0})
                cur_o_norm = {'net': cur_o['net'], 'gross': cur_o['gross'], 'debt': cur_o['debt'], 'mob': cur_o['mobilizable']}
                prev_o = prev_by_owner.get(o, {'net': 0, 'gross': 0, 'debt': 0, 'mob': 0})
                result['by_owner'][o] = _calc_delta(cur_o_norm, prev_o)
        return result

    # ── Variation vs snapshot précédent ──
    variation = None
    with get_db() as conn2:
        prev_row = conn2.execute(
            'SELECT DISTINCT date FROM positions WHERE date < ? ORDER BY date DESC LIMIT 1',
            (date,)
        ).fetchone()
    if prev_row:
        variation = _build_variation(prev_row['date'])

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
            yoy_variation = _build_variation(yoy_row['date'])
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
        'totals_by_envelope':      totals_by_envelope,
        'totals_by_macro':         totals_by_macro,
        'mobilizable_by_liquidity': mobilizable_by_liquidity,
        'entity_warnings':         entity_warnings,
        'variation':               variation,
        'yoy_variation':           yoy_variation,
        'snapshot_note':           snapshot_note,
    })


@synthese_bp.route('/api/snapshot-diff')
@login_required
def get_snapshot_diff():
    """Compare deux snapshots agreges PAR ENVELOPPE + ETABLISSEMENT + PERSONNE.

    Par defaut : la date fournie (ou la derniere) vs le snapshot precedent.
    Valorisation alignee sur la synthese : cours du jour pour le snapshot le plus
    recent, valeur figee (stockee) pour l'historique -> la variation inclut donc
    l'effet marche, et le total = la variation nette affichee en KPI. Retourne les
    mouvements par compte tries par |Δ net|, nouvelles/cloturees.

    La personne fait partie de la maille : sans elle, une meme enveloppe chez un
    meme etablissement fusionnait des contrats sans rapport — l'assurance-vie
    BoursoBank additionnait celle de l'utilisateur et celles de ses deux enfants,
    et affichait 80 000 EUR la ou les autres ecrans en montraient 71 450.
    """
    to_date = request.args.get('date')
    owner = request.args.get('owner')
    with get_db() as conn:
        dates = [r['date'] for r in conn.execute(
            'SELECT DISTINCT date FROM positions ORDER BY date').fetchall()]
        if not dates:
            return jsonify({'from_date': None, 'to_date': None,
                            'movements': [], 'totals': {}})
        if not to_date or to_date not in dates:
            to_date = dates[-1]
        prev = [d for d in dates if d < to_date]
        from_date = prev[-1] if prev else None
        ref = load_referential(conn)

        latest_date = dates[-1]

        def _positions_at(date):
            if date is None:
                return []
            rows = conn.execute('SELECT * FROM positions WHERE date=?', (date,)).fetchall()
            emap = get_entity_map(conn, date)
            hmap = get_holdings_map(conn, [r['id'] for r in rows])
            if date != latest_date:
                _freeze_holdings(hmap)
            ps = [compute_position(dict(r), emap, ref, hmap) for r in rows]
            return [p for p in ps if not owner or p['owner'] == owner]

        before = _positions_at(from_date)
        after = _positions_at(to_date)

    def _agg(positions):
        agg = {}
        for p in positions:
            env = p.get('envelope') or 'Autre'
            est = p.get('establishment') or ''
            own = p.get('owner') or ''
            e = agg.setdefault((env, est, own), {'net': 0.0, 'envelope': env,
                                                'establishment': est, 'owner': own})
            e['net'] += p.get('net_attributed', 0) or 0
        return agg

    b, a = _agg(before), _agg(after)
    movements = []
    for key in set(b) | set(a):
        in_b, in_a = key in b, key in a
        rep = a.get(key) or b.get(key)
        net_before = b[key]['net'] if in_b else 0.0
        net_after = a[key]['net'] if in_a else 0.0
        movements.append({
            'label':         rep['envelope'],
            'envelope':      rep['envelope'],
            'establishment': rep['establishment'],
            'owner':         rep['owner'],
            'net_before':    round(net_before, 2),
            'net_after':     round(net_after, 2),
            'delta':         round(net_after - net_before, 2),
            'status':        'new' if not in_b else 'closed' if not in_a else 'changed',
        })
    movements.sort(key=lambda m: -abs(m['delta']))
    net_b = round(sum(m['net_before'] for m in movements), 2)
    net_a = round(sum(m['net_after'] for m in movements), 2)
    return jsonify({
        'from_date': from_date, 'to_date': to_date,
        'movements': movements,
        'totals': {'net_before': net_b, 'net_after': net_a,
                   'delta': round(net_a - net_b, 2)},
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
        latest_date = dates[-1] if dates else None
        history = []
        for date in dates:
            rows         = conn.execute('SELECT * FROM positions WHERE date=?', (date,)).fetchall()
            entity_map   = get_entity_map(conn, date)
            # Cours du jour pour le dernier snapshot ; market_value figee sinon.
            holdings_map = get_holdings_map(conn, [r['id'] for r in rows])
            if date != latest_date:
                _freeze_holdings(holdings_map)
            positions    = [compute_position(dict(r), entity_map, ref, holdings_map) for r in rows]
            if owner:
                positions = [p for p in positions if p['owner'] == owner]
            snap_owners = sorted(set(p['owner'] for p in positions))
            # Brut, dette et mobilisable sont deja calcules par compute_position :
            # les sommer ici ne coute rien et evite un second parcours de
            # l'historique cote client pour les sparklines des indicateurs.
            entry = {
                'date':         date,
                'family_net':   sum(p['net_attributed'] for p in positions),
                'family_gross': sum(p['gross_attributed'] for p in positions),
                'family_debt':  sum(p['debt_attributed'] for p in positions),
                'family_mob':   sum(p['mobilizable_value'] for p in positions),
                'by_owner':     {o: sum(p['net_attributed'] for p in positions if p['owner'] == o)
                                for o in snap_owners},
                'by_owner_detail': {o: {
                    'net':   sum(p['net_attributed'] for p in positions if p['owner'] == o),
                    'gross': sum(p['gross_attributed'] for p in positions if p['owner'] == o),
                    'debt':  sum(p['debt_attributed'] for p in positions if p['owner'] == o),
                    'mob':   sum(p['mobilizable_value'] for p in positions if p['owner'] == o),
                } for o in snap_owners},
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

# Duree minimale pour annualiser. En dessous, extrapoler quelques semaines a
# l'annee donne un chiffre a trois chiffres qui n'informe sur rien : un compte
# ouvert depuis 7 semaines et en hausse de 12 % afficherait +245 % par an.
MIN_DAYS_ANNUALISE = 180


def _xirr(cashflows, min_days=MIN_DAYS_ANNUALISE):
    """
    Calcule le XIRR (taux de rendement interne annualisé).
    cashflows : liste de (date_str 'YYYY-MM-DD', montant)
    Retourne le taux annuel en % ou None si non convergent, ou si la periode
    couverte est plus courte que `min_days` (annualisation non significative).
    Utilise Newton-Raphson avec plusieurs estimations initiales,
    puis bisection en fallback.
    """
    if len(cashflows) < 2:
        return None
    dates = [datetime.strptime(d, '%Y-%m-%d') for d, _ in cashflows]
    if (max(dates) - min(dates)).days < min_days:
        return None
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


def _period_return(cashflows):
    """Rendement brut sur la periode, pour les cas non annualisables.

    Retourne {days, invested, final, return} ou None. `invested` somme les
    sorties de tresorerie de l'investisseur (montants negatifs), `final` les
    entrees (valeur finale + retraits).
    """
    if len(cashflows) < 2:
        return None
    dates = [datetime.strptime(d, '%Y-%m-%d') for d, _ in cashflows]
    days = (max(dates) - min(dates)).days
    invested = -sum(a for _, a in cashflows if a < 0)
    final = sum(a for _, a in cashflows if a > 0)
    if invested <= 0:
        return None
    return {'days': days, 'invested': round(invested, 2),
            'final': round(final, 2), 'return': round(final / invested - 1, 6)}


def _flux_to_cashflow(f):
    """Convertit un flux en cashflow signé pour le XIRR.

    Les frais de gestion ne sont pas un cashflow : preleves a l'interieur du
    contrat, ils reduisent sa valeur finale, et c'est ainsi qu'ils doivent
    peser sur le rendement. Les compter en plus comme un decaissement les
    facturait deux fois.
    """
    ftype = f.get('type', '')
    amount = f.get('amount', 0)
    if ftype == 'Versement':
        return (f['date'], -abs(amount))
    elif ftype in ('Retrait', 'Dividende/Intérêt'):
        return (f['date'], abs(amount))
    elif ftype == 'Frais':
        return (f['date'], 0.0)
    return (f['date'], amount)


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


@synthese_bp.route('/api/todo')
@login_required
def todo():
    """Signaux systeme a traiter pour un arrete. Lecture seule.

    `date` par defaut : l'arrete le plus recent. Les avertissements d'entites et
    les alertes de seuil de l'utilisateur ne sont PAS ici : le front les evalue
    contre la synthese qu'il detient deja.
    """
    from models import validate_date
    from services.todo import collect

    date = request.args.get('date')
    with get_db() as conn:
        if not date:
            row = conn.execute('SELECT MAX(date) AS d FROM positions').fetchone()
            date = row['d'] if row else None
            if not date:
                return jsonify({'date': None, 'signaux': [], 'total': 0})
        elif not validate_date(date):
            return jsonify({'error': 'Date invalide (format AAAA-MM-JJ attendu)'}), 400
        data = collect(conn, date)
    return jsonify({'date': date, **data})


@synthese_bp.route('/api/impot-latent')
@login_required
def impot_latent_api():
    """Impot qui resterait du si tout etait vendu a l'arrete demande.

    Params : `date` (defaut : dernier arrete), `owner` (defaut : famille).
    Lecture seule. Les enveloppes dont l'assiette n'est pas sure sont rendues
    a part dans `non_calculees`, avec leur valeur et leur motif : elles pesent
    dans le patrimoine sans peser dans l'estimation, et le dire est le seul
    moyen de ne pas faire passer un plancher pour un total.
    """
    from services.fiscalite import impot_latent

    owner = request.args.get('owner') or None
    if owner in ('Famille', ''):
        owner = None

    with get_db() as conn:
        date = request.args.get('date')
        if not date:
            row = conn.execute('SELECT MAX(date) d FROM positions').fetchone()
            date = row['d'] if row else None
        if not date:
            return jsonify({'brut': 0, 'plus_value': 0, 'impot': 0,
                            'net_apres_impot': 0, 'enveloppes': [],
                            'non_calculees': [], 'valeur_ecartee': 0})
        return jsonify(impot_latent(conn, date, owner))


@synthese_bp.route('/api/contribution')
@login_required
def contribution():
    """Decomposition de la variation du net : apports externes / performance.

    Params : `owner` (defaut : famille), `limit` (nombre de periodes, defaut 8).
    Lecture seule, s'appuie sur les arretes existants.
    """
    from services.contribution import decompose

    owner = request.args.get('owner') or None
    if owner in ('Famille', ''):
        owner = None
    limite = request.args.get('limit', type=int) or 8
    limite = max(1, min(limite, 40))

    with get_db() as conn:
        dates = [r['date'] for r in conn.execute(
            'SELECT DISTINCT date FROM positions ORDER BY date').fetchall()]
        if len(dates) < 2:
            # Une seule photo ne fait pas une variation : rien a decomposer.
            return jsonify({'periodes': [], 'total_apports': 0,
                            'total_performance': 0, 'total_variation': 0})
        ref = load_referential(conn)
        dernier = dates[-1]
        arretes = []
        for date in dates:
            rows = conn.execute('SELECT * FROM positions WHERE date=?', (date,)).fetchall()
            holdings_map = get_holdings_map(conn, [r['id'] for r in rows])
            if date != dernier:
                _freeze_holdings(holdings_map)
            positions = [compute_position(dict(r), get_entity_map(conn, date), ref, holdings_map)
                         for r in rows]
            # Par compte, pour reperer ceux qui entrent ou sortent du suivi.
            comptes = {}
            for p in positions:
                cle = (p['owner'], p.get('envelope') or '', p.get('establishment') or '',
                       p.get('entity') or '', p.get('label') or '')
                c = comptes.setdefault(cle, {'net': 0.0})
                c['net'] += p['net_attributed'] or 0
            arretes.append({
                'date': date,
                'family_net': sum(p['net_attributed'] for p in positions),
                'by_owner': {o: sum(p['net_attributed'] for p in positions if p['owner'] == o)
                             for o in set(p['owner'] for p in positions)},
                'comptes': comptes,
            })
        data = decompose(conn, arretes, owner, limite)
    return jsonify(data)
