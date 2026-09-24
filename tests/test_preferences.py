"""Preferences de lecture partagees entre appareils (/api/preferences)."""
import os

os.environ.setdefault('FINANCY_PASSWORD', 'testpass')

from tests.test_api import client, anon_client, fresh_db, CSRF_HEADERS  # noqa: E402,F401

H = CSRF_HEADERS


def test_vide_au_depart(client):
    assert client.get('/api/preferences').get_json() == {}


def test_fusion_et_effacement(client):
    r = client.patch('/api/preferences', headers=H, json={'financy_repartition': 'categorie',
                                                           'financy_filters_flux': '{"owner":"Paul"}'})
    assert r.status_code == 200
    client.patch('/api/preferences', headers=H, json={'financy_positionsView': 'table',
                                                      'financy_repartition': None})
    assert client.get('/api/preferences').get_json() == {'financy_filters_flux': '{"owner":"Paul"}',
                                                         'financy_positionsView': 'table'}


def test_cle_inconnue_ou_valeur_invalide_refusees(client):
    for corps in ({'autre_cle': 'x'}, {'financy_a-b': 'x'}, {'financy_x': 3},
                  {'financy_x': 'y' * 4001}, [], {}):
        assert client.patch('/api/preferences', headers=H, json=corps).status_code == 400
    assert client.get('/api/preferences').get_json() == {}


def test_csrf_et_session_exiges(client, anon_client):
    assert client.patch('/api/preferences', json={'financy_x': 'y'}).status_code in (400, 403)
    assert anon_client.get('/api/preferences').status_code in (302, 401)


def test_les_preferences_partent_dans_l_export(client):
    client.patch('/api/preferences', headers=H, json={'financy_repartition': 'categorie'})
    config = client.get('/api/export').get_json()['config']
    assert 'financy_repartition' in config['preferences']
