"""Tests des signaux « à traiter » agrégés pour la synthèse."""
import os
import tempfile
from datetime import datetime, timedelta

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
from services.todo import collect, COURS_PERIMES_JOURS  # noqa: E402
from services.montants import centimes  # noqa: E402

DATE = '2026-09-02'
ISIN = 'IE0002XZSHO1'
AUJ = datetime(2026, 9, 2)


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


def _position(conn, date=DATE, owner='Paul', envelope='PEA', etab='BoursoBank'):
    return conn.execute(
        'INSERT INTO positions (date, owner, category, envelope, establishment, value) '
        "VALUES (?,?,'Financier',?,?,0)", (date, owner, envelope, etab)).lastrowid


def _titre(conn, isin=ISIN, price_date='2026-09-02', priceable=1):
    conn.execute('INSERT OR IGNORE INTO securities (isin, name, last_price, '
                 'last_price_date, is_priceable) VALUES (?,?,7.12,?,?)',
                 (isin, 'ETF Test', price_date, priceable))


def _holding(conn, pid, isin=ISIN, qty=2640, as_of='2026-08-12'):
    conn.execute('INSERT INTO holdings (position_id, isin, quantity, cost_basis, '
                 'market_value, as_of_date) VALUES (?,?,?,15470.4,19140,?)',
                 (pid, isin, qty, as_of))


def _avis(conn, date, qty, net, owner='Paul', envelope='PEA', etab='BoursoBank'):
    conn.execute(
        '''INSERT INTO transactions (date, owner, envelope, establishment, isin,
           side, quantity, net_eur, source_doc) VALUES (?,?,?,?,?,'ACHAT',?,?,?)''',
        (date, owner, envelope, etab, ISIN, qty, centimes(net), f'doc:{date}:{qty}'))


def _cles(rapport):
    return [s['cle'] for s in rapport['signaux']]


class TestEcartsDeQuantite:
    def test_avis_non_repercute_remonte(self):
        with get_db() as conn:
            _titre(conn)
            pid = _position(conn)
            _holding(conn, pid)
            _avis(conn, '2026-08-17', 120, 851.64)
            _avis(conn, '2026-08-31', 215, 1535.19)
            conn.commit()
            r = collect(conn, DATE, AUJ)
        s = next(x for x in r['signaux'] if x['cle'] == 'reconcile')
        assert s['severite'] == 'warn'
        assert s['nombre'] == 1                    # une ligne concernee
        assert s['montant'] == 2386.83             # 851,64 + 1 535,19
        assert s['onglet'] == 'actifs'

    def test_photo_a_jour_ne_dit_rien(self):
        with get_db() as conn:
            _titre(conn)
            pid = _position(conn)
            _holding(conn, pid, qty=2975, as_of='2026-09-01')
            _avis(conn, '2026-08-17', 120, 851.64)
            conn.commit()
            r = collect(conn, DATE, AUJ)
        assert 'reconcile' not in _cles(r)


class TestCoursPerimes:
    def test_cours_trop_vieux_remonte(self):
        vieux = (AUJ - timedelta(days=COURS_PERIMES_JOURS + 6)).strftime('%Y-%m-%d')
        with get_db() as conn:
            _titre(conn, price_date=vieux)
            pid = _position(conn)
            _holding(conn, pid, qty=2975, as_of='2026-09-01')
            conn.commit()
            r = collect(conn, DATE, AUJ)
        s = next(x for x in r['signaux'] if x['cle'] == 'cours')
        assert s['severite'] == 'info'
        assert s['nombre'] == 1
        assert '11 jours' in s['detail']

    def test_cours_frais_ne_dit_rien(self):
        frais = (AUJ - timedelta(days=1)).strftime('%Y-%m-%d')
        with get_db() as conn:
            _titre(conn, price_date=frais)
            pid = _position(conn)
            _holding(conn, pid, qty=2975, as_of='2026-09-01')
            conn.commit()
            r = collect(conn, DATE, AUJ)
        assert 'cours' not in _cles(r)

    def test_titre_non_detenu_est_ignore(self):
        # un titre sans holding n'a pas besoin d'un cours frais
        with get_db() as conn:
            _titre(conn, price_date='2020-01-01')
            conn.commit()
            r = collect(conn, DATE, AUJ)
        assert 'cours' not in _cles(r)

    def test_cours_tres_vieux_passe_en_avertissement(self):
        # 22 jours : un cours de plus de trois semaines ne decrit plus le marche
        vieux = (AUJ - timedelta(days=22)).strftime('%Y-%m-%d')
        with get_db() as conn:
            _titre(conn, price_date=vieux)
            pid = _position(conn)
            _holding(conn, pid, qty=2975, as_of='2026-09-01')
            conn.commit()
            r = collect(conn, DATE, AUJ)
        s = next(x for x in r['signaux'] if x['cle'] == 'cours')
        assert s['severite'] == 'warn'
        assert '22 jours' in s['detail']

    def test_sans_ticker_compte_a_part(self):
        # Un titre sans ticker ne se resoudra pas par un rafraichissement : il est
        # signale separement et ne gonfle pas le decompte des cours a rafraichir.
        vieux = (AUJ - timedelta(days=10)).strftime('%Y-%m-%d')
        with get_db() as conn:
            _titre(conn, price_date=vieux)
            conn.execute("INSERT INTO securities (isin, name, ticker, last_price_date, "
                         "is_priceable) VALUES ('FR1459AB4169','Opp Taux',NULL,NULL,1)")
            pid = _position(conn)
            _holding(conn, pid, qty=2975, as_of='2026-09-01')
            conn.execute("INSERT INTO holdings (position_id, isin, quantity, as_of_date) "
                         "VALUES (?,'FR1459AB4169',10,'2026-09-01')", (pid,))
            conn.commit()
            r = collect(conn, DATE, AUJ)
        s = next(x for x in r['signaux'] if x['cle'] == 'cours')
        assert s['nombre'] == 1                      # seul le perime est « a rafraichir »
        assert 'sans ticker' in s['detail']

    def test_jamais_de_cours_renvoie_au_referentiel(self):
        # Aucun cours perime, seulement des titres jamais valorises : l'action
        # utile n'est pas « rafraichir » mais « corriger la fiche ».
        with get_db() as conn:
            conn.execute("INSERT INTO securities (isin, name, ticker, last_price_date, "
                         "is_priceable) VALUES ('FR1459AB4169','Opp Taux',NULL,NULL,1)")
            pid = _position(conn)
            conn.execute("INSERT INTO holdings (position_id, isin, quantity, as_of_date) "
                         "VALUES (?,'FR1459AB4169',10,'2026-09-01')", (pid,))
            conn.commit()
            r = collect(conn, DATE, AUJ)
        s = next(x for x in r['signaux'] if x['cle'] == 'cours')
        assert s['onglet'] == 'referentiel'
        assert 'jamais' in s['detail']

    def test_titre_non_cotable_est_ignore(self):
        with get_db() as conn:
            _titre(conn, price_date='2020-01-01', priceable=0)
            pid = _position(conn)
            _holding(conn, pid, qty=2975, as_of='2026-09-01')
            conn.commit()
            r = collect(conn, DATE, AUJ)
        assert 'cours' not in _cles(r)


class TestFluxProvisoires:
    def test_flux_provisoire_remonte(self):
        with get_db() as conn:
            conn.execute("INSERT INTO flux (date, owner, envelope, type, amount, notes) "
                         "VALUES ('2026-08-14','Léo','Assurance-vie','Versement',7500,"
                         "'[provisoire] versement programmé')")
            conn.commit()
            r = collect(conn, DATE, AUJ)
        s = next(x for x in r['signaux'] if x['cle'] == 'provisoires')
        assert s['nombre'] == 1
        assert s['montant'] == 75
        assert 'Léo' in s['detail']
        assert s['onglet'] == 'flux'

    def test_flux_atteste_ne_dit_rien(self):
        with get_db() as conn:
            conn.execute("INSERT INTO flux (date, owner, type, amount, notes) "
                         "VALUES ('2026-08-14','Paul','Versement',50000,'[import] avis.pdf')")  # centimes
            conn.commit()
            r = collect(conn, DATE, AUJ)
        assert 'provisoires' not in _cles(r)


class TestAgregation:
    def test_le_plus_grave_dabord(self):
        vieux = (AUJ - timedelta(days=10)).strftime('%Y-%m-%d')   # « info »
        with get_db() as conn:
            _titre(conn, price_date=vieux)
            pid = _position(conn)
            _holding(conn, pid)
            _avis(conn, '2026-08-17', 120, 851.64)
            conn.execute("INSERT INTO flux (date, owner, type, amount, notes) "
                         "VALUES ('2026-08-14','Léo','Versement',7500,'[provisoire] x')")  # centimes
            conn.commit()
            r = collect(conn, DATE, AUJ)
        assert r['total'] == 3
        assert r['signaux'][0]['cle'] == 'reconcile'      # seul « warn »
        assert r['signaux'][0]['severite'] == 'warn'
        assert all(s['severite'] == 'info' for s in r['signaux'][1:])

    def test_base_saine_ne_dit_rien(self):
        with get_db() as conn:
            _titre(conn)
            pid = _position(conn)
            _holding(conn, pid, qty=2975, as_of='2026-09-01')
            conn.commit()
            r = collect(conn, DATE, AUJ)
        assert r == {'signaux': [], 'total': 0}

    def test_un_signal_en_echec_nemporte_pas_les_autres(self, monkeypatch):
        import services.todo as todo
        monkeypatch.setattr(todo, '_cours_perimes',
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
        with get_db() as conn:
            conn.execute("INSERT INTO flux (date, owner, type, amount, notes) "
                         "VALUES ('2026-08-14','Léo','Versement',7500,'[provisoire] x')")  # centimes
            conn.commit()
            r = collect(conn, DATE, AUJ)
        assert _cles(r) == ['provisoires']


class TestEndpoint:
    def test_defaut_dernier_arrete(self, client):
        with get_db() as conn:
            _titre(conn)
            pid = _position(conn)
            _holding(conn, pid)
            _avis(conn, '2026-08-17', 120, 851.64)
            conn.commit()
        r = client.get('/api/todo')
        assert r.status_code == 200
        assert r.json['date'] == DATE
        assert any(s['cle'] == 'reconcile' for s in r.json['signaux'])

    def test_date_invalide(self, client):
        with get_db() as conn:
            _position(conn)
            conn.commit()
        assert client.get('/api/todo?date=hier').status_code == 400

    def test_sans_donnees(self, client):
        r = client.get('/api/todo')
        assert r.status_code == 200
        assert r.json == {'date': None, 'signaux': [], 'total': 0}

    def test_exige_la_session(self):
        app.config['TESTING'] = True
        with app.test_client() as anon:
            assert anon.get('/api/todo').status_code in (302, 401)
