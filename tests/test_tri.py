"""TRI : ce que l'argent a rapporte, selon quand il a ete verse.

Mesure principale de l'application depuis le 22/09/2026. Ces tests
verrouillent ce qui la distingue du TWR, et la regle des flux externes.
"""
import pytest

from routes.performance import _tri, _chain

AN = ['2025-01-01', '2025-07-01', '2026-01-01']


class TestTRI:
    def test_sans_flux_le_tri_egale_le_rendement(self):
        tri, _, jours = _tri(['2025-01-01', '2026-01-01'],
                             {'2025-01-01': 100, '2026-01-01': 110}, [])
        assert tri == pytest.approx(0.10, abs=1e-3)
        assert jours == 365

    def test_verser_avant_une_hausse_eleve_le_tri_pas_le_twr(self):
        # +0 % au premier semestre, +20 % au second. 100 000 verses a
        # mi-parcours profitent de toute la hausse : l'argent a travaille au
        # bon moment, le TRI le dit, le TWR non.
        valeurs = {AN[0]: 100_000, AN[1]: 100_000 + 100_000, AN[2]: 240_000}
        flux = [(AN[1], 100_000)]
        tri, _, _ = _tri(AN, valeurs, flux)
        _, twr, _, _, _ = _chain(AN, valeurs, flux)
        assert twr == pytest.approx(0.20, abs=1e-3)
        assert tri > twr

    def test_verser_avant_une_baisse_abaisse_le_tri(self):
        valeurs = {AN[0]: 100_000, AN[1]: 120_000 + 100_000, AN[2]: 176_000}
        flux = [(AN[1], 100_000)]                    # +20 %, puis −20 %
        tri, _, _ = _tri(AN, valeurs, flux)
        _, twr, _, _, _ = _chain(AN, valeurs, flux)
        assert tri < twr                             # le gros montant a subi la baisse

    def test_un_versement_n_est_pas_du_rendement(self):
        tri, _, _ = _tri(['2025-01-01', '2026-01-01'],
                         {'2025-01-01': 100, '2026-01-01': 200}, [('2025-06-01', 100)])
        assert tri == pytest.approx(0.0, abs=1e-3)

    def test_periode_courte_non_annualisee(self):
        # Deux mois de donnees : annualiser fabriquerait un taux qu'on ne verra
        # jamais. Le rendement sur la periode est rendu a la place.
        tri, periode, jours = _tri(['2026-02-01', '2026-04-01'],
                                   {'2026-02-01': 100, '2026-04-01': 103}, [])
        assert tri is None
        assert periode == pytest.approx(0.03, abs=1e-6)
        assert jours == 59

    def test_valeur_nulle_au_depart_ignoree(self):
        # Un compte ouvert en cours de route demarre a son premier arrete non nul.
        tri, _, _ = _tri(AN, {AN[0]: 0, AN[1]: 100, AN[2]: 110}, [])
        assert tri is not None

    def test_moins_de_deux_arretes_valorises(self):
        assert _tri(AN, {AN[0]: 0, AN[1]: 0, AN[2]: 100}, []) == (None, None, None)


class TestEndpoint:
    """Le TRI arrive avec chaque compte de /api/performance."""

    def test_champs_presents(self, tmp_path, monkeypatch):
        import os
        import models
        monkeypatch.setattr(models, 'DB_PATH', str(tmp_path / 'f.db'))
        monkeypatch.setattr(models, '_BASE_DIR', str(tmp_path))
        os.environ['FINANCY_PASSWORD'] = 'testpass'
        models.init_db()
        from app import app
        with models.get_db() as c:
            for d, v in (('2025-01-01', 100000), ('2026-01-01', 110000)):
                c.execute("INSERT INTO positions (date, owner, category, envelope, establishment, value) "
                          "VALUES (?,'Paul','Actions','PEA','Bourso',?)", (d, v))
            c.commit()
        app.config['TESTING'] = True
        with app.test_client() as cl:
            with cl.session_transaction() as s:
                s['authenticated'] = True
            r = cl.get('/api/performance').get_json()
        g = r['groups'][0]
        assert g['tri'] == pytest.approx(0.10, abs=1e-3)
        assert r['global']['tri'] == pytest.approx(0.10, abs=1e-3)
