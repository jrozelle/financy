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
        by_date, cats, meta = _values_by_group(conn, dates, grouping, owner)
        flux = [dict(r) for r in conn.execute('SELECT * FROM flux ORDER BY date')]
    if owner:
        flux = [f for f in flux if f['owner'] == owner]

    # Rattachement des flux. Depuis `flux.establishment` (migration 010), un
    # flux se rattache exactement a son compte. Les flux anterieurs, ou ceux
    # saisis sans etablissement, restent ambigus : on les repartit au prorata de
    # la valeur entre les comptes de la meme (enveloppe, personne), et on compte
    # combien pour pouvoir le signaler.
    keys = sorted({k for v in by_date.values() for k in v},
                  key=lambda k: tuple(str(x or '') for x in k))
    out = []
    for k in keys:
        k_dates = [d for d in dates if k in by_date[d]]
        k_values = {d: by_date[d][k] for d in k_dates}
        approx = 0
        if grouping == 'envelope':
            k_flux = [(f['date'], _flux_signed(f)) for f in flux
                      if (f.get('envelope') or 'Autre') == k[0]]
        else:
            env, etab, own = k
            siblings = [x for x in keys if x[0] == env and x[2] == own]
            k_flux = []
            for f in flux:
                if (f.get('envelope') or 'Autre') != env or f.get('owner') != own:
                    continue
                amt = _flux_signed(f)
                if not amt:
                    continue
                f_etab = f.get('establishment') or None
                if f_etab:
                    if f_etab == etab:
                        k_flux.append((f['date'], amt))
                    continue
                if len(siblings) == 1:
                    k_flux.append((f['date'], amt))
                    continue
                # Etablissement inconnu et plusieurs comptes candidats.
                d_ref = max([d for d in dates if d <= f['date'] and by_date[d]],
                            default=k_dates[0] if k_dates else dates[0])
                tot = sum(by_date[d_ref].get(x, 0.0) for x in siblings) or 0.0
                share = (by_date[d_ref].get(k, 0.0) / tot) if tot else 0.0
                if share:
                    k_flux.append((f['date'], amt * share))
                    approx += 1
        k_flux = [(d, a) for d, a in k_flux if a]
        serie, cumul, days, gaps, suspects = _chain(k_dates, k_values, k_flux)
        k_cats = sorted(c for c in cats.get(k, set()) if c)
        m = meta.get(k, {})
        # Un groupe sans rendement calculable — un compte ouvert au dernier
        # arrete, par exemple — n'est PAS retire de la reponse : l'omettre en
        # silence fait diverger cet onglet de la synthese sans explication.
        # Il est rendu avec son statut, et l'interface l'affiche comme tel.
        if cumul is None:
            # Deux causes distinctes, qu'il serait faux de confondre : un compte
            # trop recent (une seule valorisation) et un poste a valeur nulle ou
            # negative (dette nette, apport en compte courant), sur lequel aucun
            # rendement n'existe meme avec dix ans d'historique.
            status = ('negative' if k_values and min(k_values.values()) <= 0
                      else 'insufficient')
        elif set(k_cats) - NON_MEASURABLE_CATEGORIES:
            status = 'ok'
        else:
            status = 'non_measurable'
        out.append({
            'status': status,
            'key': '|'.join(str(x or '') for x in k),
            'label': _label(k, grouping),
            'envelope': m.get('envelope'), 'establishment': m.get('establishment'),
            'owner': m.get('owner'),
            'serie': serie, 'twr': cumul, 'days': days,
            'twr_annualise': annualise(cumul, days),
            'annualisable': bool(days) and days >= MIN_DAYS_ANNUALISE,
            'categories': k_cats,
            'measurable': status == 'ok',
            'suspect_periods': suspects,
            'value': k_values[k_dates[-1]], 'dates_count': len(k_dates),
            'gaps': gaps, 'flux_count': len(k_flux), 'flux_approx': approx,
            'flux_net': round(sum(a for _, a in k_flux), 2),
        })
    out.sort(key=lambda e: (e['status'] != 'ok', -e['value']))

    # L'ensemble agrege les seuls groupes mesurables : y melanger les comptes
    # courants ferait passer leurs mouvements de tresorerie pour du rendement.
    keep = {e['key'] for e in out if e['status'] == 'ok'}
    keep_keys = [k for k in keys if '|'.join(str(x or '') for x in k) in keep]
    g_tot = {d: sum(by_date[d].get(k, 0.0) for k in keep_keys) for d in dates}
    g_tot = {d: v for d, v in g_tot.items() if v}
    envs_keep = {(e['envelope'], e['owner']) for e in out if e['status'] == 'ok'}
    g_flux = [(f['date'], _flux_signed(f)) for f in flux
              if ((f.get('envelope') or 'Autre'), f.get('owner')) in envs_keep]
    g_flux = [(d, a) for d, a in g_flux if a]
    g_dates = sorted(g_tot)
    g_serie, g_cumul, g_days, g_gaps, g_susp = _chain(g_dates, g_tot, g_flux)
    glob = None
    if g_cumul is not None:
        glob = {'label': 'Ensemble mesurable', 'serie': g_serie, 'twr': g_cumul,
                'days': g_days, 'twr_annualise': annualise(g_cumul, g_days),
                'annualisable': g_days >= MIN_DAYS_ANNUALISE,
                'value': g_tot[g_dates[-1]], 'dates_count': len(g_dates),
                'gaps': g_gaps, 'suspect_periods': g_susp,
                'flux_count': len(g_flux),
                'flux_net': round(sum(a for _, a in g_flux), 2),
                'groups': sorted(keep)}

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
