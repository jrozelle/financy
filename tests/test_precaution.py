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


class TestCeQuiEstGarde:
    def test_reglementes_entiers_puis_le_plus_rentable(self):
        """Livret A entier ; puis, jusqu'a la cible, le support qui rapporte le
        plus ; le surplus est pris sur celui qui rapporte le moins."""
        from services.precaution import repartition
        from routes.performance import cle_compte
        la = ligne('Cash & dépôts', 'Livret A', 20000, owner='A')
        bourso = ligne('Cash & dépôts', 'Livret Bourso+', 60000, owner='A')
        fe = ligne('Fond Euro', 'Assurance-vie', 50000, liquidity='J8–J30', owner='A')
        rendements = {cle_compte(bourso): 0.015, cle_compte(fe): 0.025}
        r = repartition([la, bourso, fe], {'charges_mensuelles': 4000, 'mois_precaution': 18}, rendements=rendements)
        assert r['garde'] == 72000
        assert [(p['envelope'], k) for p, k in r['gardees']] == [('Livret A', 20000), ('Assurance-vie', 50000),
                                                               ('Livret Bourso+', 2000)]
        assert [(p['envelope'], k) for p, k in r['surplus']] == [('Livret Bourso+', 58000)]
        # Les livrets reglementes restent entiers, meme au-dela de la cible.
        r = repartition([la, bourso], {'charges_mensuelles': 1000, 'mois_precaution': 6})
        assert r['garde'] == 20000 and [k for _, k in r['gardees']] == [20000]
        # Sans cible, les seuls livrets reglementes sont gardes.
        assert repartition([la, bourso], {'reserve_eur': 50000})['garde'] == 20000


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
        _make_position(client, owner='Personne 1', category='Cash & dépôts', envelope='Livret A', value=5000)
        _make_position(client, owner='Personne 1', category='Cash & dépôts', envelope='Livret Bourso+', value=20000)
        _make_position(client, owner='Personne 1', category='Cash & dépôts', envelope='Compte courant', value=5000)
        _make_position(client, owner='Personne 1', category='Actions', envelope='PEA', value=10000)
        dca = client.get('/api/projection/epargne').get_json()['dca']
        assert dca['par_titulaire'] == [{'owner': 'Personne 1', 'source': 'precaution', 'montant': 13000}]
        a = client.get('/api/advisor/profiles/Personne 1/allocation').get_json()
        assert (a['precaution']['montant'], a['precaution']['cible'], a['precaution']['ecart']) == (25000, 12000, 13000)
        # Garde hors du calcul : 12 000 ; comptes courants a part ; arbitrable :
        # le surplus du livret bancaire et le PEA.
        exclus = {e['category']: e['montant'] for e in a['exclus']}
        assert exclus['Épargne de précaution'] == 12000 and exclus['Comptes courants'] == 5000
        assert a['total_eur'] == 23000 and a['financier_eur'] == 40000
        cs = client.get('/api/advisor/constats?owner=Personne 1&date=2024-06-01').get_json()['constats']
        c = next(c for c in cs if "d'épargne de précaution au-delà" in c['titre'])
        assert c['niveau'] == 'action' and c['montant'] == 13000


def test_synthese_famille_dont_un_titulaire_sans_cible(client):
    """L'ecart de la famille ne porte que sur l'epargne des titulaires qui ont
    une cible ; les autres sont nommes."""
    client.put('/api/advisor/profiles/Personne 1', headers=CSRF_HEADERS,
               json={'horizon_years': 10, 'risk_tolerance': 3, 'charges_mensuelles': 1000, 'mois_precaution': 3})
    _make_position(client, owner='Personne 1', category='Cash & dépôts', envelope='Livret Bourso+', value=5000)
    _make_position(client, owner='Personne 2', category='Fond Euro', envelope='Assurance-vie', value=7000)
    pr = client.get('/api/synthese?date=2024-06-01').get_json()['precaution']
    assert pr['par_titulaire']['Personne 1'] == {'montant': 5000, 'cible': 3000, 'ecart': 2000,
                                                 'charges_mensuelles': 1000, 'mois': 3}
    f = pr['famille']
    assert (f['montant'], f['montant_avec_cible'], f['cible'], f['ecart']) == (12000, 5000, 3000, 2000)
    assert f['titulaires_sans_cible'] == ['Personne 2']


def test_avec_une_cible_pas_de_supplement_tns_lbo():
    """TNS et LBO retirent des actions pour des liquidites ; les mois de
    charges de la cible couvrent deja ce risque : la matrice s'applique
    comme pour un profil sans eux, et l'ajustement le dit."""
    from services.advisor.allocation import allocation_financiere
    base = {'horizon_years': 15, 'risk_tolerance': 4}
    pos = [ligne('Actions', 'PEA', 50000, owner='A')]
    cible = {'charges_mensuelles': 4000, 'mois_precaution': 18}
    sans_ajustement = allocation_financiere({**base, **cible}, pos)['target']
    avec = allocation_financiere({**base, **cible, 'employment_type': 'TNS', 'has_lbo': True}, pos)
    assert avec['target'] == sans_ajustement and avec['target'].get('Cash', 0) == 0
    assert any('TNS' in a and 'couvre déjà' in a for a in avec['adjustments'])
    # Sans cible, l'ajustement joue toujours.
    assert allocation_financiere({**base, 'employment_type': 'TNS'}, pos)['target']['Cash'] > 0
