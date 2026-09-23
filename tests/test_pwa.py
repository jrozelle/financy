"""Application installable : le manifeste est servi, et ses icones existent."""
import json
import os

os.environ.setdefault('FINANCY_PASSWORD', 'testpass')
from app import app  # noqa: E402

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_manifeste_servi_et_complet():
    with app.test_client() as c:
        r = c.get('/static/manifest.json')
    assert r.status_code == 200
    m = json.loads(r.data)
    assert m['display'] == 'standalone' and m['start_url'] == '/'
    tailles = {i['sizes'] for i in m['icons']}
    assert {'192x192', '512x512'} <= tailles
    for i in m['icons']:
        assert os.path.exists(os.path.join(RACINE, i['src'].lstrip('/')))


def test_les_pages_le_declarent():
    for page in ('index.html', 'login.html'):
        html = open(os.path.join(RACINE, 'templates', page), encoding='utf-8').read()
        assert 'rel="manifest"' in html and 'viewport-fit=cover' in html
