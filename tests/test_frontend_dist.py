"""Ecrans compiles servis sous /dist/ (frontend_dist/, hors de static/)."""
import os

import app as application
from tests.test_api import client, fresh_db  # noqa: F401


def test_bundle_servi_sans_cache(client, tmp_path, monkeypatch):
    (tmp_path / 'credits.js').write_text('export const x = 1;')
    monkeypatch.setattr(application, 'FRONTEND_DIST', str(tmp_path))
    r = client.get('/dist/credits.js')
    assert r.status_code == 200 and b'export const x' in r.data
    assert r.headers['Cache-Control'] == 'no-cache'
    assert 'javascript' in r.headers['Content-Type']


def test_fichier_absent_ou_hors_du_dossier(client, tmp_path, monkeypatch):
    monkeypatch.setattr(application, 'FRONTEND_DIST', str(tmp_path))
    assert client.get('/dist/absent.js').status_code == 404
    assert client.get('/dist/../app.py').status_code == 404
    assert os.path.basename(application.FRONTEND_DIST) != 'static'
