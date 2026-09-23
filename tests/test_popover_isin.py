"""Fenetre ISIN : la valorisation suit le chemin des positions.

Elle calculait `quantite x cours` dans la devise du titre et l'affichait en
euros : un titre du Nasdaq a 100 USD valait 100 EUR. Elle passe desormais par
`_holding_effective_value`, qui convertit par fx_rates et ne valorise rien
faute de taux.
"""
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
import routes.prices as prices  # noqa: E402
from services.montants import centimes  # noqa: E402

D = '2026-09-01'


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)
    init_db()
    # La route rafraichit l'historique a la lecture : ici, rien ne doit ecrire.
    monkeypatch.setattr(prices, 'refresh_history', lambda *a, **k: None)
    yield
    if os.path.exists(models.DB_PATH):
        os.unlink(models.DB_PATH)


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['authenticated'] = True
        yield c


def _ligne(c, isin, devise, cours, qty, cout, taux=None, mv=None):
    c.execute('INSERT INTO securities (isin, name, currency, is_priceable, last_price, last_price_date) '
              'VALUES (?,?,?,1,?,?)', (isin, 'Titre', devise, cours, D))
    pid = c.execute("INSERT INTO positions (date, owner, category, envelope, value) "
                    "VALUES (?, 'Paul', 'Actions', 'CTO', 0)", (D,)).lastrowid
    c.execute('INSERT INTO holdings (position_id, isin, quantity, cost_basis, market_value, as_of_date) '
              'VALUES (?,?,?,?,?,?)', (pid, isin, qty, centimes(cout), centimes(mv), D))
    if taux:
        c.execute("INSERT INTO fx_rates (pair, date, rate) VALUES (?, ?, ?)", (f'EUR{devise}', D, taux))
    c.commit()


def _holding(client, isin):
    r = client.get(f'/api/prices/history/{isin}').get_json()
    assert 'holding' in r, r
    return r['holding']


def test_un_cours_en_dollars_est_converti(client):
    with get_db() as c:
        _ligne(c, 'US0378331005', 'USD', 110.0, 10, 900.0, taux=1.10)
    h = _holding(client, 'US0378331005')
    assert h['current_value'] == pytest.approx(1000.0)      # 10 x 110 / 1,10
    assert h['pnl'] == pytest.approx(100.0)


def test_sans_taux_rien_n_est_valorise_et_c_est_dit(client):
    with get_db() as c:
        _ligne(c, 'US5949181045', 'USD', 110.0, 10, 900.0)
    h = _holding(client, 'US5949181045')
    assert not h['current_value']
    assert h['pnl'] is None                                 # pas « -900 » de perte
    assert any('taux' in a for a in h['alertes'])


def test_la_detention_par_enveloppe_donne_la_meme_valeur(client):
    with get_db() as c:
        _ligne(c, 'FR0000120271', 'EUR', 50.0, 20, 800.0)
    h = _holding(client, 'FR0000120271')
    assert [p['market_value'] for p in h['positions']] == [pytest.approx(h['current_value'])]


def test_plus_value_de_position_ignore_une_ligne_sans_taux():
    """Meme regle cote Positions : une ligne en dollars sans taux n'est ni un
    gain ni une perte, et le decompte des lignes mesurees le dit."""
    from models import _plus_value
    lignes = [
        {'cost_basis': 900.0, 'market_value': None, 'quantity': 10, 'last_price': 110.0,
         'currency': 'USD', 'fx_rate': None, 'is_priceable': 1, 'last_price_date': D},
        {'cost_basis': 400.0, 'market_value': None, 'quantity': 10, 'last_price': 50.0,
         'currency': 'EUR', 'is_priceable': 1, 'last_price_date': D},
    ]
    pv = _plus_value(lignes, 1.0)
    assert pv['gain_lignes'] == 1
    assert pv['gain_attributed'] == pytest.approx(100.0)
