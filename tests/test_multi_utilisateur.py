"""Plusieurs personnes, reconnues par le reverse proxy (Authelia) : identite,
titulaire, reglages propres a chacun, journal des modifications."""
import pytest

import auth
from auth import titulaire_de, _reseaux
from tests.test_api import client, anon_client, fresh_db, CSRF_HEADERS  # noqa: F401

PROXY = '10.0.0.5'


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setattr(auth, 'AUTH_PAR_PROXY', True)
    monkeypatch.setattr(auth, 'PROXIES_DE_CONFIANCE', _reseaux('10.0.0.0/24'))


def appel(c, methode, url, qui=None, adresse=PROXY, **kw):
    entetes = {**kw.pop('headers', {}), **({'Remote-User': qui} if qui else {})}
    return getattr(c, methode)(url, headers=entetes, environ_base={'REMOTE_ADDR': adresse}, **kw)


def jeton(c):
    with c.session_transaction() as s:
        return s.get('csrf_token')


class TestIdentite:
    def test_rattachement_au_titulaire(self):
        titulaires = ['Paul', 'Claire', 'Zoé']
        assert titulaire_de('claire', titulaires) == 'Claire'
        assert titulaire_de('paul.m@exemple.fr', titulaires) == 'Paul'
        assert titulaire_de('zoe', titulaires) == 'Zoé'           # accents ignores
        assert titulaire_de('inconnu', titulaires) is None and titulaire_de(None, titulaires) is None

    def test_en_tete_lu_seulement_depuis_le_proxy(self, anon_client, proxy):
        assert appel(anon_client, 'get', '/api/moi', 'claire', adresse='203.0.113.9').status_code == 401
        r = appel(anon_client, 'get', '/api/moi', 'claire')
        assert r.status_code == 200 and r.get_json()['utilisateur'] == 'claire'

    def test_sans_l_option_l_en_tete_ne_vaut_rien(self, anon_client, monkeypatch):
        monkeypatch.setattr(auth, 'PROXIES_DE_CONFIANCE', _reseaux('10.0.0.0/24'))
        r = appel(anon_client, 'get', '/api/moi', 'claire')
        # Refuse, ou ouvert sans mot de passe : dans les deux cas, aucune identite retenue.
        assert r.status_code == 401 or r.get_json()['utilisateur'] is None

    def test_identifiant_mal_forme_refuse(self, anon_client, proxy):
        assert appel(anon_client, 'get', '/api/moi', 'claire<script>').status_code == 401

    def test_changement_de_personne(self, anon_client, proxy):
        appel(anon_client, 'get', '/api/moi', 'paul')
        t1 = jeton(anon_client)
        r = appel(anon_client, 'get', '/api/moi', 'claire')
        assert r.get_json()['utilisateur'] == 'claire' and jeton(anon_client) != t1   # session regeneree


class TestReglagesPropres:
    def test_preferences_et_disposition_de_chacun(self, anon_client, proxy):
        # Reglage commun existant (mot de passe partage, avant Authelia).
        from models import get_db
        with get_db() as c:
            c.execute("INSERT INTO config (key, value) VALUES ('preferences', '{\"financy_x\": \"commun\"}')")
        appel(anon_client, 'get', '/api/moi', 'paul')
        h = {'X-CSRF-Token': jeton(anon_client)}
        assert appel(anon_client, 'get', '/api/preferences', 'paul').get_json() == {'financy_x': 'commun'}
        appel(anon_client, 'patch', '/api/preferences', 'paul', headers=h, json={'financy_x': 'paul'})
        assert appel(anon_client, 'get', '/api/preferences', 'paul').get_json() == {'financy_x': 'paul'}
        # Claire lit toujours le reglage commun.
        appel(anon_client, 'get', '/api/moi', 'claire')
        assert appel(anon_client, 'get', '/api/preferences', 'claire').get_json() == {'financy_x': 'commun'}
        # Revenir a la disposition par defaut ne fait pas reapparaitre la commune.
        with get_db() as c:
            c.execute("INSERT INTO config (key, value) VALUES ('synthese_disposition', '{\"ordre\": [\"chiffres\"]}')")
        h = {'X-CSRF-Token': jeton(anon_client)}
        assert appel(anon_client, 'put', '/api/synthese/disposition', 'claire', headers=h, json={}).status_code == 200
        assert appel(anon_client, 'get', '/api/synthese/disposition', 'claire').get_json() == {}


class TestJournal:
    def test_qui_a_ecrit_quoi(self, anon_client, proxy):
        appel(anon_client, 'get', '/api/moi', 'claire')
        h = {'X-CSRF-Token': jeton(anon_client)}
        assert appel(anon_client, 'post', '/api/flux', 'claire', headers=h, json={
            'date': '2024-06-01', 'owner': 'Claire', 'amount': 100, 'envelope': 'PEA', 'type': 'Versement'}).status_code == 201
        appel(anon_client, 'patch', '/api/preferences', 'claire', headers=h, json={'financy_x': 'y'})
        j = appel(anon_client, 'get', '/api/journal', 'claire').get_json()
        assert [(e['utilisateur'], e['methode'], e['chemin']) for e in j] == [('claire', 'POST', '/api/flux')]
