"""Plus-values realisees, calculees depuis le registre des transactions.

Impossible sans ce registre : `holdings` ne decrit qu'un etat, et une ligne
soldee disparait avec son gain. Methode du prix moyen pondere, frais inclus des
deux cotes — celle retenue par l'administration fiscale pour le prix moyen
pondere d'acquisition, et celle qu'applique BoursoBank sur ses releves.

Une vente ne modifie pas le PRU : elle retire des titres a ce PRU et degage la
plus-value. Le PRU ne bouge qu'a l'achat.
"""


def compute_realized(transactions):
    """Deroule le registre et retourne (par_ligne, evenements).

    `transactions` : iterable de dicts tries par date, avec au minimum
    isin, side, quantity, net_eur (et envelope/date/source_doc pour le detail).

    `par_ligne` : {isin: {quantity, cost, pru, realized, sold_qty}} — etat final.
    `evenements` : une entree par vente, avec le PRU applique et le gain.
    """
    state, events = {}, []
    for t in transactions:
        i = t['isin']
        s = state.setdefault(i, {'quantity': 0.0, 'cost': 0.0,
                                 'realized': 0.0, 'sold_qty': 0.0,
                                 'untracked_qty': 0.0, 'untracked_proceeds': 0.0})
        qty = t['quantity'] or 0
        net = t['net_eur'] or 0
        if t['side'] == 'ACHAT':
            s['quantity'] += qty
            s['cost'] += net
            continue
        # Vente : on ne peut ceder que ce qui est trace. Le surplus signale un
        # achat absent du registre (anterieur a l'historique disponible) ; on
        # l'isole au lieu de fabriquer un PRU.
        sellable = min(qty, s['quantity'])
        excess = qty - sellable
        if sellable > 1e-9:
            pru = s['cost'] / s['quantity']
            proceeds = net * (sellable / qty) if qty else 0.0
            gain = proceeds - sellable * pru
            s['cost'] -= sellable * pru
            s['quantity'] -= sellable
            s['realized'] += gain
            s['sold_qty'] += sellable
            events.append({
                'date': t.get('date'), 'isin': i, 'envelope': t.get('envelope'),
                'quantity': round(sellable, 6), 'pru': round(pru, 6),
                'proceeds': round(proceeds, 2), 'gain': round(gain, 2),
                'source_doc': t.get('source_doc'),
            })
        if excess > 1e-9:
            s['untracked_qty'] += excess
            s['untracked_proceeds'] += net * (excess / qty) if qty else 0.0
    for i, s in state.items():
        s['pru'] = round(s['cost'] / s['quantity'], 6) if s['quantity'] > 1e-9 else None
        for k in ('quantity', 'cost', 'realized', 'sold_qty',
                  'untracked_qty', 'untracked_proceeds'):
            s[k] = round(s[k], 6 if k.endswith('qty') else 2)
    return state, events
