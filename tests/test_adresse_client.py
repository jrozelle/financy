"""Adresse du client derriere un reverse proxy : la limite des tentatives de
connexion compte par client, pas par proxy."""
from types import SimpleNamespace

import auth
from auth import adresse_client, _reseaux

PROXY = _reseaux('10.0.0.0/24')


def req(distante, transmis=None):
    return SimpleNamespace(remote_addr=distante,
                           headers={'X-Forwarded-For': transmis} if transmis is not None else {})


def test_sans_proxy_declare_rien_ne_change():
    assert adresse_client(req('203.0.113.9', '198.51.100.1'), reseaux=[]) == '203.0.113.9'


def test_en_tete_lu_derriere_le_proxy():
    assert adresse_client(req('10.0.0.5', '198.51.100.1'), reseaux=PROXY) == '198.51.100.1'


def test_en_tete_ignore_hors_proxy():
    # Un client qui ecrit lui-meme l'en-tete ne choisit pas son adresse.
    assert adresse_client(req('203.0.113.9', '198.51.100.1'), reseaux=PROXY) == '203.0.113.9'


def test_gauche_falsifiee_ignoree():
    # Le client a ecrit 1.2.3.4 ; le proxy a ajoute l'adresse qu'il a vue.
    assert adresse_client(req('10.0.0.5', '1.2.3.4, 198.51.100.1'), reseaux=PROXY) == '198.51.100.1'


def test_chaine_de_proxies():
    assert adresse_client(req('10.0.0.5', '198.51.100.1, 10.0.0.7'), reseaux=PROXY) == '198.51.100.1'


def test_valeur_illisible_garde_la_derniere_adresse_sure():
    assert adresse_client(req('10.0.0.5', 'nimporte, 10.0.0.7'), reseaux=PROXY) == '10.0.0.7'
    assert adresse_client(req('10.0.0.5', ''), reseaux=PROXY) == '10.0.0.5'


def test_ipv6():
    assert adresse_client(req('10.0.0.5', '2001:db8::1'), reseaux=PROXY) == '2001:db8::1'


def test_configuration_illisible_ignoree():
    assert [str(r) for r in _reseaux(' 10.0.0.1 , pas-une-adresse, 192.168.0.0/16,')] == ['10.0.0.1/32', '192.168.0.0/16']


def test_limite_par_client_derriere_le_proxy(monkeypatch):
    """Dix erreurs d'un client ne bloquent pas un autre client du meme proxy."""
    import app as application
    monkeypatch.setattr(auth, 'PROXIES_DE_CONFIANCE', PROXY)
    monkeypatch.setattr(application, 'AUTH_PASSWORD', 'secret')
    application._login_attempts.clear()
    client = application.app.test_client()

    def essai(ip, mdp='faux'):
        with client.session_transaction() as s:
            s['csrf_token'] = 'jeton'
        return client.post('/login', data={'password': mdp, 'csrf_token': 'jeton'},
                           headers={'X-Forwarded-For': ip}, environ_base={'REMOTE_ADDR': '10.0.0.5'})

    for _ in range(application._RATE_LIMIT_MAX):
        essai('198.51.100.1')
    assert essai('198.51.100.1').status_code == 429
    assert essai('198.51.100.2').status_code == 200     # l'autre client n'est pas bloque
    application._login_attempts.clear()
