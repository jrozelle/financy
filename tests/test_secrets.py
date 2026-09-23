"""La cle d'API vit hors de la base (ni sauvegarde ni export ne l'emportent),
dans un fichier lisible du seul proprietaire ; l'environnement l'emporte."""
import json
import os
import stat
import tempfile

import pytest

import models

_tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_tmp.close()
models.DB_PATH = _tmp.name
models._BASE_DIR = os.path.dirname(_tmp.name)
os.environ['FINANCY_PASSWORD'] = 'testpass'

from models import init_db, get_db  # noqa: E402
from app import app  # noqa: E402
from services import settings  # noqa: E402

H = {'X-CSRF-Token': 'test'}
CLE = 'sk-ant-api03-' + 'x' * 40


@pytest.fixture(autouse=True)
def base(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    for f in (models.DB_PATH, settings._chemin_secrets()):
        if os.path.exists(f):
            os.unlink(f)
    init_db()
    settings.invalidate_cache()
    yield


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['authenticated'] = True
            s['csrf_token'] = 'test'
        yield c


def test_la_cle_saisie_ne_va_pas_en_base(client):
    assert client.put('/api/settings', headers=H, json={'anthropic_api_key': CLE}).status_code == 200
    with get_db() as conn:
        row = conn.execute("SELECT value FROM config WHERE key='settings'").fetchone()
    assert CLE not in (row['value'] if row else '')
    assert settings.get_api_key() == CLE
    assert stat.S_IMODE(os.stat(settings._chemin_secrets()).st_mode) == 0o600
    assert client.get('/api/settings').get_json()['effective_source'] == 'fichier'


def test_l_environnement_l_emporte(client, monkeypatch):
    settings.ecrire_secret('anthropic_api_key', CLE)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-env')
    assert settings.get_api_key() == 'sk-ant-env'


def test_une_cle_ancienne_en_base_est_deplacee(client):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('settings', ?)",
                     (json.dumps({'anthropic_api_key': CLE, 'autre': 1}),))
    client.get('/api/settings')
    with get_db() as conn:
        s = json.loads(conn.execute("SELECT value FROM config WHERE key='settings'").fetchone()['value'])
    assert 'anthropic_api_key' not in s and s['autre'] == 1
    assert settings.lire_secrets()['anthropic_api_key'] == CLE


def test_effacer(client):
    client.put('/api/settings', headers=H, json={'anthropic_api_key': CLE})
    client.put('/api/settings', headers=H, json={'anthropic_api_key': ''})
    assert settings.get_api_key() is None
