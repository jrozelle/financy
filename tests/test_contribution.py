"""Tests de la décomposition apports / performance."""
import os
import tempfile

import pytest

import models

_tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_tmp.close()
models.DB_PATH = _tmp.name
models._BASE_DIR = os.path.dirname(_tmp.name)
os.environ['FINANCY_PASSWORD'] = 'testpass'
os.environ['PRICE_PROVIDER'] = 'mock'

from models import init_db, get_db  # noqa: E402
from app import app  # noqa: E402
from services.contribution import decompose  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)
    init_db()
    yield
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['authenticated'] = True
            s['csrf_token'] = 'test'
        yield c


def _flux(conn, date, type_, montant, owner='Paul'):
    conn.execute('INSERT INTO flux (date, owner, envelope, type, amount) '
                 "VALUES (?,?,'PEA',?,?)", (date, owner, type_, montant))


def _arretes(*couples):
    """(date, net) -> la forme attendue par decompose()."""
    return [{'date': d, 'family_net': n, 'by_owner': {'Paul': n}} for d, n in couples]


class TestDecomposition:
    def test_identite_apports_plus_performance(self):
        with get_db() as conn:
            _flux(conn, '2026-02-10', 'Versement', 1000)
            conn.commit()
            r = decompose(conn, _arretes(('2026-01-31', 100000), ('2026-03-31', 105000)))
        p = r['periodes'][0]
        assert p['variation'] == 5000
        assert p['apports'] == 1000
        assert p['performance'] == 4000
        assert p['apports'] + p['performance'] == p['variation']

    def test_hausse_entierement_due_a_l_epargne(self):
        # Le patrimoine monte de 2 000 et 2 000 ont ete verses : le marche n'y
        # est pour rien. C'est exactement ce que la carte doit rendre lisible.
        with get_db() as conn:
            _flux(conn, '2026-02-10', 'Versement', 2000)
            conn.commit()
            r = decompose(conn, _arretes(('2026-01-31', 50000), ('2026-03-31', 52000)))
        assert r['periodes'][0]['performance'] == 0
        assert r['periodes'][0]['apports'] == 2000

    def test_retrait_compte_en_negatif(self):
        with get_db() as conn:
            _flux(conn, '2026-02-10', 'Retrait', 3000)
            conn.commit()
            r = decompose(conn, _arretes(('2026-01-31', 50000), ('2026-03-31', 48000)))
        p = r['periodes'][0]
        assert p['apports'] == -3000
        assert p['performance'] == 1000        # −2 000 de variation, −3 000 sortis

    def test_dividendes_et_frais_ne_sont_pas_des_apports(self):
        # Regle de l'application : un dividende est produit par les actifs
        # detenus, des frais sont preleves dans le contrat. Les deux
        # appartiennent au rendement, pas aux apports.
        with get_db() as conn:
            _flux(conn, '2026-02-10', 'Dividende/Intérêt', 800)
            _flux(conn, '2026-02-11', 'Frais', 200)
            conn.commit()
            r = decompose(conn, _arretes(('2026-01-31', 50000), ('2026-03-31', 50600)))
        p = r['periodes'][0]
        assert p['apports'] == 0
        assert p['performance'] == 600

    def test_borne_basse_exclue(self):
        # Un flux tombant le jour d'un arrete est deja dans sa valeur : le
        # compter de nouveau le ferait apparaitre deux fois.
        with get_db() as conn:
            _flux(conn, '2026-01-31', 'Versement', 5000)
            conn.commit()
            r = decompose(conn, _arretes(('2026-01-31', 50000), ('2026-03-31', 51000)))
        assert r['periodes'][0]['apports'] == 0

    def test_borne_haute_incluse(self):
        with get_db() as conn:
            _flux(conn, '2026-03-31', 'Versement', 5000)
            conn.commit()
            r = decompose(conn, _arretes(('2026-01-31', 50000), ('2026-03-31', 55000)))
        assert r['periodes'][0]['apports'] == 5000

    def test_filtrage_par_titulaire(self):
        with get_db() as conn:
            _flux(conn, '2026-02-10', 'Versement', 1000, owner='Paul')
            _flux(conn, '2026-02-10', 'Versement', 4000, owner='Claire')
            conn.commit()
            arretes = [
                {'date': '2026-01-31', 'family_net': 100000,
                 'by_owner': {'Paul': 60000, 'Claire': 40000}},
                {'date': '2026-03-31', 'family_net': 106000,
                 'by_owner': {'Paul': 61500, 'Claire': 44500}},
            ]
            r = decompose(conn, arretes, owner='Paul')
        p = r['periodes'][0]
        assert p['variation'] == 1500          # la part de Paul seulement
        assert p['apports'] == 1000            # ses versements seulement
        assert p['performance'] == 500

    def test_limite_garde_les_periodes_recentes(self):
        with get_db() as conn:
            conn.commit()
            arretes = _arretes(*[(f'2026-{m:02d}-01', 1000 * m) for m in range(1, 9)])
            r = decompose(conn, arretes, limite=3)
        assert len(r['periodes']) == 3
        assert r['periodes'][-1]['fin'] == '2026-08-01'

    def test_totaux_coherents(self):
        with get_db() as conn:
            _flux(conn, '2026-02-10', 'Versement', 1000)
            _flux(conn, '2026-04-10', 'Versement', 2000)
            conn.commit()
            r = decompose(conn, _arretes(
                ('2026-01-31', 100000), ('2026-03-31', 104000), ('2026-05-31', 108000)))
        assert r['total_apports'] == 3000
        assert r['total_variation'] == 8000
        assert r['total_performance'] == 5000
        assert r['total_apports'] + r['total_performance'] == r['total_variation']


class TestEndpoint:
    def _snapshot(self, conn, date, valeur, owner='Paul'):
        conn.execute('INSERT INTO positions (date, owner, category, envelope, value) '
                     "VALUES (?,?,'Financier','PEA',?)", (date, owner, valeur))

    def test_deux_arretes_minimum(self, client):
        with get_db() as conn:
            self._snapshot(conn, '2026-01-31', 50000)
            conn.commit()
        r = client.get('/api/contribution')
        assert r.status_code == 200
        assert r.json['periodes'] == []        # une photo ne fait pas une variation

    def test_decomposition_via_l_api(self, client):
        with get_db() as conn:
            self._snapshot(conn, '2026-01-31', 50000)
            self._snapshot(conn, '2026-03-31', 53000)
            _flux(conn, '2026-02-10', 'Versement', 1000)
            conn.commit()
        r = client.get('/api/contribution')
        assert r.status_code == 200
        p = r.json['periodes'][0]
        assert p['variation'] == 3000
        assert p['apports'] == 1000
        assert p['performance'] == 2000

    def test_limite_bornee(self, client):
        with get_db() as conn:
            self._snapshot(conn, '2026-01-31', 50000)
            self._snapshot(conn, '2026-03-31', 53000)
            conn.commit()
        assert client.get('/api/contribution?limit=999').status_code == 200
        assert client.get('/api/contribution?limit=0').status_code == 200

    def test_exige_la_session(self):
        app.config['TESTING'] = True
        with app.test_client() as anon:
            assert anon.get('/api/contribution').status_code in (302, 401)
