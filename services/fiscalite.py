"""Impot latent : ce que l'Etat prendrait si tout etait vendu aujourd'hui.

Le patrimoine brut affiche partout n'est pas ce qu'on toucherait. Entre les
deux il y a l'impot sur les plus-values encore latentes, qui n'apparait nulle
part tant qu'on ne vend pas — et qui se compte en dizaines de milliers d'euros.
Le connaitre change deux decisions : dans quelle enveloppe arbitrer, et combien
on peut reellement mobiliser.

Trois principes tiennent ce module :

1. **La maille est l'enveloppe, pas la ligne.** Sur un PEA ou une assurance-vie
   l'impot ne se calcule pas titre par titre : il porte sur la quote-part de
   gains du contrat au moment du rachat. C'est aussi la maille ou l'assiette est
   la plus sure, les apports etant traces dans `flux`.

2. **Une assiette douteuse n'est pas chiffree.** Le Livret A pese 60 000 EUR
   sans un seul versement saisi : « valeur moins apports » y verrait 60 000 EUR
   de plus-value. Une enveloppe dont les apports ne sont pas credibles sort du
   total et figure dans `non_calculees`, avec son motif.

3. **L'anciennete est une hypothese, pas une donnee.** Aucune date d'ouverture
   n'est stockee. Le regime retenu suppose les contrats matures — PEA de plus de
   5 ans, assurance-vie de plus de 8 ans —, c'est-a-dire le regime le plus
   FAVORABLE. L'impot rendu est donc un plancher, et chaque enveloppe dit quelle
   hypothese la porte.

Le resultat est une estimation d'ordre de grandeur, pas une declaration.
"""
from __future__ import annotations
import logging

logger = logging.getLogger('financy.fiscalite')

# Taux en vigueur (2026). Prelevements sociaux et PFU sont des constantes
# nationales ; les loger ici plutot que dans le referentiel evite qu'une
# modification d'affichage ne les fasse deriver en silence.
PS = 0.172                 # prelevements sociaux
PFU = 0.30                 # 12,8 % d'IR + 17,2 % de PS
IR_AV = 0.075              # assurance-vie de plus de 8 ans, sous 150 000 EUR verses
ABATTEMENT_AV = 4600.0     # par titulaire et par an, sur les gains retires

# Regime par defaut de chaque enveloppe. `None` signifie « pas chiffrable ici » :
# l'immobilier depend d'abattements pour duree de detention qu'on ne connait pas,
# le PER melange un capital deductible impose au bareme et des gains au PFU.
REGIMES = {
    'Livret A':       ('exonere',   'Interets exoneres d\'impot et de prelevements sociaux'),
    'LDDS':           ('exonere',   'Interets exoneres d\'impot et de prelevements sociaux'),
    'LEP':            ('exonere',   'Interets exoneres d\'impot et de prelevements sociaux'),
    'Livret Bourso+': ('pfu',       'Livret bancaire : interets au prelevement forfaitaire'),
    'Compte courant': ('exonere',   'Un compte courant ne produit pas de plus-value'),
    'PEL/CEL':        ('pfu',       'Plan ouvert apres 2018 : interets au prelevement forfaitaire'),
    'PEA':            ('ps_seuls',  'Plan de plus de 5 ans (hypothese) : prelevements sociaux seuls'),
    'PEA-PME':        ('ps_seuls',  'Plan de plus de 5 ans (hypothese) : prelevements sociaux seuls'),
    'Assurance-vie':  ('av',        'Contrat de plus de 8 ans (hypothese) : abattement puis 7,5 % + PS'),
    'CTO':            ('pfu',       'Compte-titres : prelevement forfaitaire unique de 30 %'),
    'Crypto':         ('pfu',       'Actifs numeriques : prelevement forfaitaire unique de 30 %'),
    'PER':            (None,        'Sortie en capital : les versements deduits sont imposes au bareme, '
                                    'a un taux marginal que l\'application ne connait pas'),
    'Immobilier':     (None,        'Abattements pour duree de detention : la date d\'acquisition manque'),
    'SCI':            (None,        'Abattements pour duree de detention : la date d\'acquisition manque'),
    'SCPI':           (None,        'Abattements pour duree de detention : la date d\'acquisition manque'),
    'Holding':        (None,        'Cession de titres de societe : regime propre, hors de ce calcul'),
    'Entité':         (None,        'Parts d\'une SCI ou d\'une indivision : regime de l\'immobilier, '
                                    'date d\'acquisition inconnue'),
    'Autre':          (None,        'Enveloppe non precisee : regime inconnu'),
}
# Une enveloppe hors referentiel n'a pas de regime connu : lui preter le
# prelevement forfaitaire inventait un impot. Elle est ecartee, et comptee.
REGIME_INCONNU = (None, 'Enveloppe hors referentiel : regime inconnu')


def _apports_par_enveloppe(conn, date_max, owner=None):
    """Apports externes nets cumules jusqu'a l'arrete, par (enveloppe, titulaire).

    Retourne aussi, par enveloppe, s'il existe au moins un VERSEMENT : sans
    versement, « valeur moins apports » confondrait le capital avec du gain.
    """
    from routes.performance import _flux_signed

    q = 'SELECT date, type, amount, owner, envelope FROM flux WHERE date <= ?'
    p = [date_max]
    if owner:
        q += ' AND owner = ?'
        p.append(owner)

    apports, verses = {}, set()
    for r in conn.execute(q, p):
        f = dict(r)
        env = f.get('envelope') or 'Autre'
        apports[env] = apports.get(env, 0.0) + _flux_signed(f)
        if (f.get('type') or '') == 'Versement':
            verses.add(env)
    return apports, verses


def _pru_par_enveloppe(conn, date, owner=None):
    """Seconde source d'assiette : le prix de revient des titres detenus.

    Moins sure que les apports — un `cost_basis` egal au centime pres a la
    valeur de marche n'est pas un prix de revient, c'est une case remplie par
    defaut — mais elle couvre le PEA et l'assurance-vie, ou les versements sont
    rarement saisis un par un. Le nombre de lignes sans PRU distinct est rendu
    avec le total : c'est lui qui dit ce que l'estimation vaut.
    """
    q = ('SELECT p.envelope, h.cost_basis cb, h.market_value mv '
         'FROM holdings h JOIN positions p ON p.id = h.position_id '
         'WHERE p.date = ?')
    prm = [date]
    if owner:
        q += ' AND p.owner = ?'
        prm.append(owner)

    pru = {}
    for r in conn.execute(q, prm):
        env = r['envelope'] or 'Autre'
        e = pru.setdefault(env, {'cout': 0.0, 'valeur': 0.0, 'lignes': 0, 'sans_pru': 0})
        cb, mv = r['cb'] or 0, r['mv'] or 0
        e['cout'] += cb
        e['valeur'] += mv
        e['lignes'] += 1
        if not cb or abs(cb - mv) < 0.01:
            e['sans_pru'] += 1
    return pru


def _valeurs_par_enveloppe(conn, date, owner=None):
    """Brut attribue par enveloppe, valorise comme la synthese.

    L'ancienne version sommait `positions.value` : ni entite (une position
    liee a une SCI vaut 0 en base), ni quote-part, ni cours du jour. Le « brut »
    de la carte tombait a 540 000 € pour 1 560 000 € dans les indicateurs, et
    l'immobilier detenu en SCI disparaissait sans meme figurer parmi les
    enveloppes ecartees.
    """
    from models import compute_position, get_entity_map, holdings_a_date, load_referential
    q, p = 'SELECT * FROM positions WHERE date = ?', [date]
    if owner:
        q += ' AND owner = ?'
        p.append(owner)
    rows = conn.execute(q, p).fetchall()
    em, ref = get_entity_map(conn, date), load_referential(conn)
    hm = holdings_a_date(conn, [r['id'] for r in rows], date)
    valeurs, titulaires = {}, {}
    for r in rows:
        pos = compute_position(dict(r), em, ref, hm)
        v = pos.get('gross_attributed') or 0
        if abs(v) < 0.005:
            continue
        env = pos.get('envelope') or pos.get('entity') and 'Entité' or 'Autre'
        valeurs[env] = valeurs.get(env, 0.0) + v
        titulaires.setdefault(env, set()).add(pos['owner'])
    return valeurs, titulaires


def _assiette(env, valeur, apports, verses, pru):
    """Plus-value latente d'une enveloppe : (montant, source, reserve).

    Retourne (None, None, motif) quand aucune source ne tient — mieux vaut une
    enveloppe ecartee et comptee qu'un nombre invente.

    Le prix de revient des titres passe D'ABORD quand il couvre la majorite
    des lignes : le journal des flux ne porte souvent que les versements
    recents, et « valeur moins apports » prenait alors tout le capital ancien
    pour du gain — 160 000 € de plus-value sur 235 000 € d'assurance-vie, pour
    9 000 € au prix de revient.
    """
    e = pru.get(env)
    if e and e['lignes'] and e['sans_pru'] <= e['lignes'] / 2:
        pv = round(e['valeur'] - e['cout'], 2)
        reserve = None
        if e['sans_pru']:
            reserve = (f"{e['sans_pru']} ligne{'s' if e['sans_pru'] > 1 else ''} sur "
                       f"{e['lignes']} sans prix de revient distinct : gain sous-estime")
        return max(0.0, pv), 'prix de revient', reserve

    # A defaut, les apports traces, quand l'enveloppe porte au moins un versement.
    if env in verses:
        pv = round(valeur - apports.get(env, 0.0), 2)
        if pv < 0:
            # Un livret ne perd pas d'argent : des apports superieurs a la
            # valeur signalent des retraits absents du journal, pas une perte.
            return None, None, (f'Apports saisis ({apports.get(env, 0):,.0f} EUR) superieurs a la '
                                f'valeur : des retraits manquent au journal'
                                .replace(',', ' '))
        reserve = None
        if e and e['lignes']:
            reserve = 'Prix de revient trop lacunaire : estimation sur les versements saisis'
        return pv, 'apports', reserve

    if e and e['lignes']:
        return None, None, 'Prix de revient inconnu sur la plupart des lignes, et aucun versement saisi'
    return None, None, 'Ni versement saisi ni prix de revient : la part de gain est inconnue'


def _impot(regime, assiette, nb_titulaires):
    """Impot du sur une plus-value latente, selon le regime de l'enveloppe."""
    if assiette <= 0:
        return 0.0, None
    if regime == 'exonere':
        return 0.0, None
    if regime == 'ps_seuls':
        return assiette * PS, None
    if regime == 'av':
        # L'abattement porte sur les gains RETIRES dans l'annee, par FOYER
        # fiscal : 4 600 EUR seul, 9 200 EUR pour un couple. Compte par
        # titulaire, il atteignait 18 400 EUR avec deux enfants rattaches.
        abattement = ABATTEMENT_AV * min(2, max(1, nb_titulaires))
        taxable = max(0.0, assiette - abattement)
        return taxable * (IR_AV + PS), abattement
    return assiette * PFU, None


def impot_latent(conn, date, owner=None):
    """Impot latent a l'arrete `date`, enveloppe par enveloppe.

    Returns {'brut', 'plus_value', 'impot', 'net_apres_impot', 'enveloppes',
             'non_calculees', 'taux_moyen'}
    """
    valeurs, titulaires = _valeurs_par_enveloppe(conn, date, owner)
    apports, verses = _apports_par_enveloppe(conn, date, owner)
    pru = _pru_par_enveloppe(conn, date, owner)

    lignes, ecartees = [], []
    brut = pv_totale = impot_total = 0.0

    for env in sorted(valeurs, key=lambda e: -valeurs[e]):
        valeur = valeurs[env]
        brut += valeur
        regime, motif = REGIMES.get(env, REGIME_INCONNU)

        # Un regime hors de portee du calcul : la valeur reste au brut, mais
        # ni la plus-value ni l'impot ne sont inventes.
        if regime is None:
            ecartees.append({'enveloppe': env, 'valeur': round(valeur, 2), 'motif': motif})
            continue

        # Une enveloppe exoneree n'a pas besoin d'assiette : le resultat est nul
        # quelle qu'elle soit, donc l'absence d'apports ne la disqualifie pas.
        if regime == 'exonere':
            pv, source, reserve = 0.0, 'exonere', None
        else:
            pv, source, reserve = _assiette(env, valeur, apports, verses, pru)
            if pv is None:
                ecartees.append({'enveloppe': env, 'valeur': round(valeur, 2),
                                 'motif': reserve})
                continue
        nb = len(titulaires.get(env, {None}))
        du, abattement = _impot(regime, pv, nb)

        pv_totale += max(0.0, pv)
        impot_total += du
        lignes.append({
            'enveloppe':   env,
            'valeur':      round(valeur, 2),
            'apports':     round(apports.get(env, 0.0), 2),
            'plus_value':  pv,
            'source':      source,
            'reserve':     reserve,
            'regime':      regime,
            'motif':       motif,
            'abattement':  round(abattement, 2) if abattement else None,
            'impot':       round(du, 2),
            'taux_effectif': round(du / pv, 4) if pv > 0 else 0.0,
        })

    return {
        'date':            date,
        'brut':            round(brut, 2),
        'plus_value':      round(pv_totale, 2),
        'impot':           round(impot_total, 2),
        'net_apres_impot': round(brut - impot_total, 2),
        'taux_moyen':      round(impot_total / pv_totale, 4) if pv_totale > 0 else 0.0,
        'enveloppes':      lignes,
        'non_calculees':   ecartees,
        'valeur_ecartee':  round(sum(e['valeur'] for e in ecartees), 2),
    }
