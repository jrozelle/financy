"""Epargne de precaution : ce qu'elle compte, sa cible (charges x mois du
profil), et ce que le conseil en fait (garde, DCA, constats)."""
from services.precaution import est_precaution, cible, bilan
from tests.test_api import client, fresh_db, CSRF_HEADERS, _make_position  # noqa: F401


def ligne(category, envelope, net=1000, liquidity='J0–J1', mobilizable=None, **kw):
    return {'category': category, 'envelope': envelope, 'net_attributed': net, 'liquidity': liquidity,
            'mobilizable_value': net if mobilizable is None else mobilizable, **kw}


class TestRegle:
    def test_ce_qui_compte(self):
        assert est_precaution(ligne('Cash & dépôts', 'Livret A'))
        assert est_precaution(ligne('Cash & dépôts', 'Livret Bourso+'))
        assert est_precaution(ligne('Cash & dépôts', 'PEL/CEL', liquidity='J8–J30'))
        assert est_precaution(ligne('Fond Euro', 'Assurance-vie', liquidity='J8–J30'))

    def test_ce_qui_ne_compte_pas(self):
        assert not est_precaution(ligne('Cash & dépôts', 'Compte courant'))          # l'argent qui tourne
        assert not est_precaution(ligne('Cash & dépôts', 'PEA'))                     # especes d'un placement
        assert not est_precaution(ligne('Fond Euro', 'PER', liquidity='Bloqué'))      # bloque
        assert not est_precaution(ligne('Fond Euro', 'Assurance-vie', mobilizable=0))  # contrat nanti
        assert not est_precaution(ligne('Actions', 'Assurance-vie'))
        assert not est_precaution(ligne('Cash & dépôts', 'Livret A', net=0))
        assert not est_precaution(ligne('Cash & dépôts', 'Livret A', label='SCI Exemple'), entites=('SCI Exemple',))

    def test_cible_et_ecart(self):
        assert cible(None) is None and cible({'charges_mensuelles': 2000}) is None
        assert cible({'charges_mensuelles': 2000, 'mois_precaution': 6}) == 12000
        b = bilan([ligne('Cash & dépôts', 'Livret A', 10000), ligne('Fond Euro', 'Assurance-vie', 5000),
                   ligne('Cash & dépôts', 'Compte courant', 3000)],
                  {'charges_mensuelles': 2000, 'mois_precaution': 6})
        assert (b['montant'], b['cible'], b['ecart']) == (15000, 12000, 3000)
        assert [l['montant'] for l in b['lignes']] == [10000, 5000]


class TestGardeDesPropositions:
    def test_la_cible_se_garde_livrets_puis_fonds_euros(self):
        from services.advisor.rebalance import _gardes_precaution, _bucket_proposals
        alloc = {'precaution': {'cible': 30000}, 'precaution_par_classe': {'Cash': 20000, 'Obligations': 40000}}
        g = _gardes_precaution(alloc)
        assert g['par_classe'] == {'Cash': 20000, 'Obligations': 10000}
        assert _gardes_precaution({'precaution': {'cible': None}}) is None
        # Cash surpondere de 25 000 sur 25 000 : seuls 5 000 sortent, la garde reste.
        gap = [{'category': 'Cash', 'delta_eur': -25000, 'actual_eur': 25000, 'target_eur': 0, 'libre_eur': 25000},
               {'category': 'Actions', 'delta_eur': 25000, 'actual_eur': 0, 'target_eur': 25000, 'libre_eur': 0}]
        props = _bucket_proposals(gap, total_eur=25000, precaution=g)
        assert sum(p['amount'] for p in props if p.get('kind') == 'bucket') == 5000


class TestProfilEtConseil:
    def _profil(self, client, **champs):
        return client.put('/api/advisor/profiles/Personne 1', headers=CSRF_HEADERS,
                          json={'horizon_years': 10, 'risk_tolerance': 3, **champs})

    def test_profil_et_reserve_gardee(self, client):
        assert self._profil(client, reserve_eur=50000).status_code == 200
        r = self._profil(client, charges_mensuelles='2 500', mois_precaution=6).get_json()
        assert (r['charges_mensuelles'], r['mois_precaution']) == (2500, 6)
        assert r['reserve_eur'] == 50000          # absente de la requete : gardee
        assert self._profil(client, mois_precaution=99).status_code == 400
        assert self._profil(client, charges_mensuelles=-1).status_code == 400

    def test_dca_et_constat(self, client):
        self._profil(client, charges_mensuelles=2000, mois_precaution=6)
        _make_position(client, owner='Personne 1', category='Cash & dépôts', envelope='Livret A', value=20000)
        _make_position(client, owner='Personne 1', category='Cash & dépôts', envelope='Compte courant', value=5000)
        _make_position(client, owner='Personne 1', category='Actions', envelope='PEA', value=10000)
        dca = client.get('/api/projection/epargne').get_json()['dca']
        assert dca['par_titulaire'] == [{'owner': 'Personne 1', 'source': 'precaution', 'montant': 8000}]
        a = client.get('/api/advisor/profiles/Personne 1/allocation').get_json()['precaution']
        assert (a['montant'], a['cible'], a['ecart']) == (20000, 12000, 8000)
        cs = client.get('/api/advisor/constats?owner=Personne 1&date=2024-06-01').get_json()['constats']
        c = next(c for c in cs if "d'épargne de précaution au-delà" in c['titre'])
        assert c['niveau'] == 'action' and c['montant'] == 8000


def test_synthese_famille_dont_un_titulaire_sans_cible(client):
    """L'ecart de la famille ne porte que sur l'epargne des titulaires qui ont
    une cible ; les autres sont nommes."""
    client.put('/api/advisor/profiles/Personne 1', headers=CSRF_HEADERS,
               json={'horizon_years': 10, 'risk_tolerance': 3, 'charges_mensuelles': 1000, 'mois_precaution': 3})
    _make_position(client, owner='Personne 1', category='Cash & dépôts', envelope='Livret A', value=5000)
    _make_position(client, owner='Personne 2', category='Fond Euro', envelope='Assurance-vie', value=7000)
    pr = client.get('/api/synthese?date=2024-06-01').get_json()['precaution']
    assert pr['par_titulaire']['Personne 1'] == {'montant': 5000, 'cible': 3000, 'ecart': 2000,
                                                 'charges_mensuelles': 1000, 'mois': 3}
    f = pr['famille']
    assert (f['montant'], f['montant_avec_cible'], f['cible'], f['ecart']) == (12000, 5000, 3000, 2000)
    assert f['titulaires_sans_cible'] == ['Personne 2']
