"""Performance : rentabilite ponderee par le temps (TWR).

Le TWR neutralise les versements et retraits : il mesure le rendement des
placements, pas l'effet du calendrier d'apport. C'est la seule mesure
comparable a un indice, contrairement au TRI (`/api/tri`) qui pondere par les
capitaux.

Methode — Dietz modifiee chainee :
  Les `positions` fournissent une valorisation a chaque date d'arrete. Entre
  deux arretes, les `flux` sont ponderes par le temps restant, puis les
  rendements des sous-periodes sont chaines.

      r_i = (V_fin - V_debut - F) / (V_debut + sum(w_j * f_j))
      w_j = (T - d_j) / T          (d_j : jours ecoules depuis V_debut)

  Dietz plutot qu'un simple ratio parce que les arretes sont trimestriels
  alors que les versements sont mensuels : ignorer leur date gonflerait ou
  ecraserait le rendement selon qu'ils arrivent en debut ou en fin de periode.
"""
from datetime import datetime

from flask import Blueprint, jsonify, request

from models import (get_db, load_referential, compute_position, get_entity_map,
                    get_holdings_map, freeze_holdings_prices)
from auth import login_required

performance_bp = Blueprint('performance', __name__)

# Duree minimale pour annualiser. En dessous, extrapoler quelques semaines a
# l'annee donne un chiffre a trois chiffres qui n'informe sur rien.
MIN_DAYS_ANNUALISE = 180

# Categories sur lesquelles un rendement n'a pas de sens. Un compte courant ou
# un livret ne "performe" pas : sa valeur bouge parce que de l'argent entre et
# sort, et ces mouvements internes ne sont pas des flux externes. Un compte
# courant affichait +324 % sur deux mois. Idem pour les objets de valeur,
# reevalues a la main sans flux.
NON_MEASURABLE_CATEGORIES = {'Cash & dépôts', 'Objets de valeur'}

# Variation au-dela de laquelle un mouvement non declare est plus probable
# qu'une performance reelle. Une TWR ne vaut que ce que vaut la table `flux`.
# Cas typique : une assurance-vie qui recoit un versement non enregistre voit
# sa valeur bondir, et le rendement absorbe l'apport — plus de 80 % de
# performance apparente sur deux semaines. On ne corrige pas (impossible de
# deviner le montant), on signale.
SUSPECT_JUMP = 0.30

# Mailles d'agregation. `account` est la maille par defaut : une enveloppe seule
# melange des contrats sans rapport — l'assurance-vie de la base agrege quatre
# etablissements et quatre personnes, dont deux contrats d'enfants. Leur TWR
# commune ne decrit aucun placement reel.
GROUPINGS = ('account', 'envelope')

_FLUX_IN = ('Versement',)
_FLUX_OUT = ('Retrait', 'Frais')


def _flux_signed(f):
    """Flux externe signe : positif s'il entre, negatif s'il sort.

    Un dividende encaisse n'est PAS un flux externe : il est produit par les
    actifs deja detenus, donc il fait partie du rendement. L'inclure comme
    apport le retirerait de la performance.
    """
    t = f.get('type') or ''
    a = abs(f.get('amount') or 0)
    if t in _FLUX_IN:
        return a
    if t in _FLUX_OUT:
        return -a
    return 0.0


def annualise(cumul, days, min_days=MIN_DAYS_ANNUALISE):
    """Annualise un rendement cumule, ou None si la periode est trop courte."""
    if days is None or days < min_days or cumul is None:
        return None
    return (1.0 + cumul) ** (365.25 / days) - 1.0


def _key(row, grouping):
    """Cle d'agregation d'une position ou d'un flux."""
    env = row.get('envelope') or 'Autre'
    if grouping == 'envelope':
        return (env,)
    return (env, row.get('establishment') or None, row.get('owner') or None)


def _label(key, grouping):
    if grouping == 'envelope':
        return key[0]
    env, etab, owner = key
    parts = [env] + [p for p in (etab, owner) if p]
    return ' · '.join(parts)


def _values_by_group(conn, dates, grouping, owner=None):
    """{date: {cle: valeur}}, {cle: {categories}} — sans valeur par defaut.

    Un groupe ABSENT d'un arrete n'y vaut pas zero : il n'y est pas valorise.
    La distinction est vitale — un snapshot qui ne couvre pas un compte ferait
    sinon tomber sa valeur a zero puis remonter, produisant -100 % suivi de
    +4000 %. Les dates sans valorisation sont donc omises, pas mises a zero.
    """
    ref = load_referential(conn)
    by_date, cats, meta = {}, {}, {}
    for d in dates:
        rows = conn.execute('SELECT * FROM positions WHERE date=?', (d,)).fetchall()
        emap = get_entity_map(conn, d)
        hmap = get_holdings_map(conn, [r['id'] for r in rows])
        # Arrete historique : market_value enregistree, pas le cours du jour.
        # Le dernier arrete garde le cours du jour, comme la synthese.
        if d != dates[-1]:
            freeze_holdings_prices(hmap)
        positions = [compute_position(dict(r), emap, ref, hmap) for r in rows]
        if owner:
            positions = [p for p in positions if p['owner'] == owner]
        vals = {}
        for p in positions:
            k = _key(p, grouping)
            vals[k] = vals.get(k, 0.0) + (p['net_attributed'] or 0)
            cats.setdefault(k, set()).add(p.get('category'))
            meta.setdefault(k, {'envelope': p.get('envelope') or 'Autre',
                                'establishment': p.get('establishment'),
                                'owner': p.get('owner')})
        by_date[d] = vals
    return by_date, cats, meta


def _composition_flux(dates, members):
    """Flux synthetiques traduisant les changements de composition d'un agregat.

    Un agregat (une enveloppe, l'ensemble du patrimoine) additionne plusieurs
    comptes. Quand un compte APPARAIT entre deux arretes, le total augmente sans
    qu'aucun versement ne soit declare : le rendement absorbe l'arrivee du
    capital. C'est ainsi qu'une assurance-vie de 100 000 EUR entrant dans le
    perimetre affichait +35 % de performance sur quinze jours.

    On traite donc l'apparition d'un compte comme un apport et sa disparition
    comme un retrait, dates a la fin de la sous-periode : poids nul dans le
    denominateur de Dietz, ce qui neutralise l'effet sans fabriquer de rendement.

    `members` : {cle de compte: {date: valeur}}. Retourne [(date, montant signe)].
    """
    out = []
    for k in range(len(dates) - 1):
        d0, d1 = dates[k], dates[k + 1]
        delta = 0.0
        for vals in members.values():
            at0, at1 = d0 in vals, d1 in vals
            if at1 and not at0:
                delta += vals[d1]
            elif at0 and not at1:
                delta -= vals[d0]
        if abs(delta) > 0.005:
            out.append((d1, delta))
    return out


def _chain(dates, values, flux):
    """Chaine les rendements Dietz modifiee.

    Retourne (serie, cumul, jours, trous, sauts_suspects).

    Une sous-periode n'est mesurable que si ses DEUX bornes portent du capital :
    on ne calcule pas de rendement sur un intervalle qui part de zero, sinon le
    premier versement se retrouve au denominateur.
    """
    idx, serie, start, last, gaps, suspects = 100.0, [], None, None, 0, []
    for k in range(len(dates) - 1):
        d0, d1 = dates[k], dates[k + 1]
        v0, v1 = values[d0], values[d1]
        t0 = datetime.strptime(d0, '%Y-%m-%d')
        span = (datetime.strptime(d1, '%Y-%m-%d') - t0).days
        if span <= 0:
            continue
        if v0 <= 0 or v1 <= 0:
            gaps += 1
            continue
        period = [(datetime.strptime(fd, '%Y-%m-%d'), amt)
                  for fd, amt in flux if d0 < fd <= d1]
        net = sum(amt for _, amt in period)
        weighted = sum(amt * ((span - (fd - t0).days) / span) for fd, amt in period)
        base = v0 + weighted
        if base <= 0:
            continue
        if start is None:
            start = d0
            serie.append({'date': d0, 'index': 100.0})
        r = (v1 - v0 - net) / base
        # `r` est deja la part INEXPLIQUEE de la variation : les flux declares
        # en sont retires. On ne conditionne donc pas l'alerte a leur absence —
        # un versement de 100 EUR n'explique pas une chute de 20 000.
        if abs(r) > SUSPECT_JUMP:
            suspects.append({'from': d0, 'to': d1, 'change': round(r, 4),
                             'delta': round(v1 - v0, 2), 'flux': round(net, 2)})
        idx *= 1.0 + r
        serie.append({'date': d1, 'index': round(idx, 4)})
        last = d1
    if start is None or last is None:
        return [], None, None, gaps, suspects
    days = (datetime.strptime(last, '%Y-%m-%d')
            - datetime.strptime(start, '%Y-%m-%d')).days
    return serie, idx / 100.0 - 1.0, days, gaps, suspects


@performance_bp.route('/api/performance')
@login_required
def get_performance():
    owner = request.args.get('owner')
    grouping = request.args.get('group', 'account')
    if grouping not in GROUPINGS:
        return jsonify({'error': f'Maille inconnue (attendu : {", ".join(GROUPINGS)})'}), 400

    with get_db() as conn:
        dates = [r['date'] for r in conn.execute(
            'SELECT DISTINCT date FROM positions ORDER BY date').fetchall()]
        if len(dates) < 2:
            return jsonify({'dates': dates, 'groups': [], 'global': None,
                            'grouping': grouping, 'insufficient': True})
        # Toujours calcule a la maille compte : c'est le grain le plus fin, et
        # les changements de composition d'un agregat ne sont visibles qu'a ce
        # niveau.
        by_date, cats, meta = _values_by_group(conn, dates, 'account', owner)
        flux = [dict(r) for r in conn.execute('SELECT * FROM flux ORDER BY date')]
    if owner:
        flux = [f for f in flux if f['owner'] == owner]

    accounts = sorted({k for v in by_date.values() for k in v},
                      key=lambda k: tuple(str(x or '') for x in k))
    # {cle de compte: {date: valeur}}
    acct_values = {a: {d: by_date[d][a] for d in dates if a in by_date[d]} for a in accounts}

    def group_key(acct):
        return (acct[0],) if grouping == 'envelope' else acct

    groups = {}
    for a in accounts:
        groups.setdefault(group_key(a), []).append(a)

    out = []
    for gk, members in groups.items():
        mvals = {a: acct_values[a] for a in members}
        g_dates = sorted({d for v in mvals.values() for d in v})
        g_values = {d: sum(v[d] for v in mvals.values() if d in v) for d in g_dates}

        # Flux reels : rattachement exact par etablissement quand il est connu.
        approx = 0
        g_flux = []
        for f in flux:
            amt = _flux_signed(f)
            if not amt:
                continue
            f_env = f.get('envelope') or 'Autre'
            f_own = f.get('owner')
            f_etab = f.get('establishment') or None
            cand = [a for a in members if a[0] == f_env
                    and (grouping == 'envelope' or a[2] == f_own)]
            if not cand:
                continue
            if grouping == 'envelope':
                g_flux.append((f['date'], amt))
                continue
            # maille compte : un flux appartient a un etablissement precis
            siblings = [a for a in accounts if a[0] == f_env and a[2] == f_own]
            if f_etab:
                if any(a[1] == f_etab for a in cand):
                    g_flux.append((f['date'], amt))
                continue
            if len(siblings) == 1:
                g_flux.append((f['date'], amt))
                continue
            d_ref = max([d for d in dates if d <= f['date'] and by_date[d]],
                        default=g_dates[0])
            tot = sum(by_date[d_ref].get(x, 0.0) for x in siblings) or 0.0
            share = sum(by_date[d_ref].get(a, 0.0) for a in cand) / tot if tot else 0.0
            if share:
                g_flux.append((f['date'], amt * share))
                approx += 1

        comp = _composition_flux(g_dates, mvals) if len(members) > 1 else []
        serie, cumul, days, gaps, suspects = _chain(g_dates, g_values, g_flux + comp)

        g_cats = sorted({c for a in members for c in (cats.get(a) or set()) if c})
        if cumul is None:
            status = ('negative' if g_values and min(g_values.values()) <= 0
                      else 'insufficient')
        elif set(g_cats) - NON_MEASURABLE_CATEGORIES:
            status = 'ok'
        else:
            status = 'non_measurable'
        m = meta.get(members[0], {})
        # Le capital apporte n'a de sens que sur la periode mesuree : additionner
        # des versements anterieurs au premier arrete afficherait un apport que
        # le calcul, lui, ignore.
        window = [(d, a) for d, a in g_flux
                  if serie and serie[0]['date'] < d <= serie[-1]['date']] if serie else []
        out.append({
            'status': status,
            'key': '|'.join(str(x or '') for x in gk),
            'label': _label(gk, grouping),
            'envelope': gk[0],
            'establishment': None if grouping == 'envelope' else m.get('establishment'),
            'owner': None if grouping == 'envelope' else m.get('owner'),
            'serie': serie, 'twr': cumul, 'days': days,
            'twr_annualise': annualise(cumul, days),
            'annualisable': bool(days) and days >= MIN_DAYS_ANNUALISE,
            'categories': g_cats, 'measurable': status == 'ok',
            'suspect_periods': suspects,
            'value': g_values[g_dates[-1]], 'dates_count': len(g_dates),
            'gaps': gaps, 'accounts': len(members),
            'flux_count': len(window),
            'flux_net': round(sum(a for _, a in window), 2),
            'flux_approx': approx,
        })
    out.sort(key=lambda e: (e['status'] != 'ok', -e['value']))

    # Ensemble : memes regles, sur les seuls comptes mesurables.
    keep = [a for gk, members in groups.items() for a in members
            if next(e for e in out if e['key'] == '|'.join(str(x or '') for x in gk))['status'] == 'ok']
    glob = None
    if keep:
        mvals = {a: acct_values[a] for a in keep}
        g_dates = sorted({d for v in mvals.values() for d in v})
        g_values = {d: sum(v[d] for v in mvals.values() if d in v) for d in g_dates}
        pairs = {(a[0], a[2]) for a in keep}
        g_flux = [(f['date'], _flux_signed(f)) for f in flux
                  if ((f.get('envelope') or 'Autre'), f.get('owner')) in pairs
                  and _flux_signed(f)]
        comp = _composition_flux(g_dates, mvals)
        serie, cumul, days, gaps, suspects = _chain(g_dates, g_values, g_flux + comp)
        if cumul is not None:
            window = [(d, a) for d, a in g_flux
                      if serie[0]['date'] < d <= serie[-1]['date']]
            glob = {'label': 'Ensemble mesurable', 'serie': serie, 'twr': cumul,
                    'days': days, 'twr_annualise': annualise(cumul, days),
                    'annualisable': days >= MIN_DAYS_ANNUALISE,
                    'value': g_values[g_dates[-1]], 'dates_count': len(g_dates),
                    'gaps': gaps, 'suspect_periods': suspects,
                    'flux_count': len(window),
                    'flux_net': round(sum(a for _, a in window), 2),
                    'accounts': len(keep),
                    'groups': sorted(e['key'] for e in out if e['status'] == 'ok')}

    return jsonify({
        'dates': dates, 'first_date': dates[0], 'date': dates[-1],
        'owner': owner, 'grouping': grouping, 'groupings': list(GROUPINGS),
        'groups': out, 'global': glob,
        'excluded': [{'label': e['label'], 'value': e['value'], 'status': e['status'],
                      'dates_count': e['dates_count']}
                     for e in out if e['status'] != 'ok'],
        'min_days_annualise': MIN_DAYS_ANNUALISE,
        'non_measurable_categories': sorted(NON_MEASURABLE_CATEGORIES),
    })
