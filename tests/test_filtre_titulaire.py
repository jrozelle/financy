"""Le filtre « titulaire » doit atteindre TOUT ce qui est affiche.

Quatre valeurs echappaient au filtre le 22/09/2026, toutes de la meme facon :
la donnee par personne existait, mais l'affichage lisait le total famille faute
de la chercher — ou, pour les enveloppes, faute qu'elle existe. Le symptome
etait un « dont 890 000 EUR d'immobilier » sous des actifs bruts de
950 000 EUR pour une seule personne.

Ces tests verrouillent la partie serveur : chaque agregat expose de quoi
filtrer, et les parts des titulaires redonnent le total.
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

DATE = '2026-06-30'


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


@pytest.fixture
def deux_titulaires():
    """Paul : 100 000 d'actions en PEA. Claire : 300 000 d'immobilier."""
    with get_db() as conn:
        conn.execute('INSERT INTO positions (date, owner, category, envelope, value, debt) '
                     "VALUES (?,'Paul','Actions','PEA',100000,0)", (DATE,))
        conn.execute('INSERT INTO positions (date, owner, category, envelope, value, debt) '
                     "VALUES (?,'Claire','Immobilier','Immobilier',300000,120000)", (DATE,))
        conn.commit()


def _syn(client):
    r = client.get(f'/api/synthese?date={DATE}')
    assert r.status_code == 200
    return r.get_json()


class TestDetailParTitulaire:
    """Chaque agregat doit porter de quoi filtrer, sans quoi l'affichage n'a
    d'autre choix que de montrer le total de la famille."""

    def test_les_poches_portent_le_detail(self, client, deux_titulaires):
        macro = _syn(client)['totals_by_macro']
        immo = macro['Patrimoine immobilier']
        assert immo['by_owner']['Claire']['gross'] == 300000
        assert immo['by_owner'].get('Paul', {}).get('gross', 0) == 0

    def test_les_poches_portent_aussi_la_dette(self, client, deux_titulaires):
        # Sans la dette par titulaire, le levier d'une poche ne se lit pas.
        immo = _syn(client)['totals_by_macro']['Patrimoine immobilier']
        assert immo['by_owner']['Claire']['debt'] == 120000

    def test_les_enveloppes_portent_le_detail(self, client, deux_titulaires):
        # C'est le seul agregat qui en etait depourvu : la carte Repartition
        # affichait donc la famille sous un filtre nominatif.
        env = _syn(client)['totals_by_envelope']
        assert env['PEA']['by_owner']['Paul']['gross'] == 100000
        assert env['Immobilier']['by_owner']['Claire']['net'] == 180000
        assert env['Immobilier']['by_owner']['Claire']['debt'] == 120000

    def test_les_categories_portent_le_detail(self, client, deux_titulaires):
        cat = _syn(client)['totals_by_category']
        assert cat['Actions']['by_owner_gross']['Paul'] == 100000
        assert cat['Actions']['by_owner']['Paul'] == 100000

    def test_la_liquidite_se_recalcule_depuis_les_positions(self, client, deux_titulaires):
        # `mobilizable_by_liquidity` est un total famille par construction : le
        # front le refait par titulaire depuis /api/positions. Chaque ligne doit
        # donc porter son titulaire, son delai et son montant mobilisable — sans
        # quoi le sous-titre « x EUR sous 24 h » retombe sur la famille.
        lignes = client.get(f'/api/positions?date={DATE}').get_json()
        assert lignes
        for p in lignes:
            assert 'owner' in p and 'liquidity' in p and 'mobilizable_value' in p
        assert {p['owner'] for p in lignes} == {'Paul', 'Claire'}


class TestLesPartsFontLeTotal:
    """Un detail par titulaire qui ne redonne pas le total serait pire que pas
    de detail du tout : l'ecart passerait inapercu."""

    def test_poches(self, client, deux_titulaires):
        for poche in _syn(client)['totals_by_macro'].values():
            for champ in ('gross', 'net'):
                somme = sum(o[champ] for o in poche['by_owner'].values())
                assert somme == pytest.approx(poche[champ])

    def test_enveloppes(self, client, deux_titulaires):
        for env in _syn(client)['totals_by_envelope'].values():
            for champ in ('gross', 'net', 'debt'):
                somme = sum(o[champ] for o in env['by_owner'].values())
                assert somme == pytest.approx(env[champ])

    def test_categories(self, client, deux_titulaires):
        for cat in _syn(client)['totals_by_category'].values():
            assert sum(cat['by_owner_gross'].values()) == pytest.approx(cat['gross'])
            assert sum(cat['by_owner'].values()) == pytest.approx(cat['net'])

    def test_titulaires(self, client, deux_titulaires):
        syn = _syn(client)
        for champ in ('gross', 'net', 'debt'):
            somme = sum(o[champ] for o in syn['totals_by_owner'].values())
            assert somme == pytest.approx(syn['family'][champ])


class TestPerformanceFiltree:
    def test_le_twr_ne_voit_que_le_titulaire_demande(self, client):
        with get_db() as conn:
            for d, vj, vp in (('2026-01-31', 100000, 50000), (DATE, 110000, 100000)):
                conn.execute('INSERT INTO positions (date, owner, category, envelope, value) '
                             "VALUES (?,'Paul','Actions','PEA',?)", (d, vj))
                conn.execute('INSERT INTO positions (date, owner, category, envelope, value) '
                             "VALUES (?,'Claire','Actions','PEA',?)", (d, vp))
            conn.commit()
        r = client.get('/api/performance?owner=Paul').get_json()
        assert r['global'] is not None
        # +10 % pour Paul ; Claire a double, l'inclure le ferait deraper.
        assert r['global']['twr'] == pytest.approx(0.10, abs=1e-6)
        assert r['global']['value'] == 110000


class TestCategoriesRenommees:
    """« Société » a ete renommee « Parts sociales » dans le referentiel sans
    que les jeux de categories du code suivent. Le classement en poche n'en
    souffrait pas — la categorie inconnue tombe en « Patrimoine autre », ce qui
    se trouvait etre juste —, mais le conseiller, lui, pouvait proposer
    d'arbitrer des parts de holding comme un ETF."""

    def test_les_parts_sociales_ne_s_arbitrent_pas(self):
        from services.advisor.rebalance import NON_ARBITRABLE
        assert 'Parts sociales' in NON_ARBITRABLE
        assert 'Société' in NON_ARBITRABLE      # base non migree

    def test_les_deux_noms_tombent_dans_la_meme_poche(self):
        from routes.synthese import _macro_bucket
        assert _macro_bucket('Parts sociales') == _macro_bucket('Société')

    def test_le_classement_couvre_le_referentiel_par_defaut(self):
        # Une categorie non listee tombe en « autre » : acceptable, mais elle
        # doit y tomber par decision, pas par oubli.
        from routes.synthese import MACRO_BUCKETS
        from models import _CATEGORIES_FULL
        classees = {c for cats in MACRO_BUCKETS.values() for c in cats}
        assert not set(_CATEGORIES_FULL) - classees
