"""Montants en centimes : conversion, et reconstruction des tables sous controle."""
import sqlite3

import pytest

import models
from services.montants import centimes, euros, ligne_en_centimes, ligne_en_euros


class TestConversion:
    def test_arrondi_commercial(self):
        # 2.675 vaut 2.67499999... en binaire : round() donnerait 267.
        assert centimes(2.675) == 268
        assert centimes(-12.345) == -1235
        assert centimes(0.1 + 0.2) == 30
        assert centimes(5367.970895604706) == 536797

    def test_valeurs_vides(self):
        assert centimes(None) is None and centimes('') is None and euros(None) is None

    def test_aller_retour(self):
        for v in (0, 0.01, 12.5, -1234.56, 1077732.0):
            assert euros(centimes(v)) == v

    def test_seules_les_colonnes_de_montant(self):
        l = {'montant_souscrit': 1000.0, 'parts': 12.5, 'prix_retrait': 180.5}
        assert ligne_en_centimes('entite_parts', l) == {'montant_souscrit': 100000, 'parts': 12.5,
                                                        'prix_retrait': 180.5}
        assert ligne_en_euros('entite_parts', {'montant_souscrit': 100000}) == {'montant_souscrit': 1000.0}
        assert ligne_en_centimes('autre_table', {'montant': 3.3}) == {'montant': 3.3}


def _base_v20():
    """Base en memoire au schema d'avant les centimes."""
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    for v, f in models.MIGRATIONS:
        if v <= 20:
            f(c)
    return c


def _ops(c, *montants):
    for i, m in enumerate(montants):
        c.execute("INSERT INTO entite_operations (entity, date, libelle, montant, nature) "
                  "VALUES ('SCI Exemple', '2026-01-02', ?, ?, 'revenu')", (f'op {i}', m))


class TestReconstruction:
    def test_valeurs_index_et_compteur_conserves(self):
        c = _base_v20()
        _ops(c, 1234.5, -99.999, 0.1 + 0.2)
        c.execute('DELETE FROM entite_operations WHERE libelle=?', ('op 2',))   # compteur a 3
        c.execute("INSERT INTO entite_parts (entity, nom, parts, montant_souscrit, prix_souscription) "
                  "VALUES ('SCI Exemple', 'SCPI A', 12.5, 2500.004, 200.0)")
        models._migration_021(c)
        assert [tuple(r) for r in c.execute('SELECT id, montant FROM entite_operations ORDER BY id')] \
            == [(1, 123450), (2, -10000)]
        p = c.execute('SELECT parts, montant_souscrit, prix_souscription FROM entite_parts').fetchone()
        assert tuple(p) == (12.5, 250000, 200.0)       # parts et prix unitaire restent en REAL
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name='idx_entite_op'").fetchone()
        c.execute("INSERT INTO entite_operations (entity, date, libelle, montant, nature) "
                  "VALUES ('SCI Exemple', '2026-02-01', 'suivante', 100, 'revenu')")
        assert c.execute("SELECT id FROM entite_operations WHERE libelle='suivante'").fetchone()[0] == 4
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name LIKE '%__centimes'").fetchone()

    def test_idempotente(self):
        c = _base_v20()
        _ops(c, 10.0)
        models._migration_021(c)
        models._migration_021(c)
        assert c.execute('SELECT montant FROM entite_operations').fetchone()[0] == 1000

    def test_table_stricte_refuse_un_montant_non_entier(self):
        c = _base_v20()
        models._migration_021(c)
        with pytest.raises(sqlite3.IntegrityError):
            _ops(c, 12.5)

    def test_doublon_revele_par_l_arrondi_annule_tout(self):
        """Deux operations identiques a l'arrondi pres heurtent l'unicite :
        la reconstruction s'annule, l'ancienne table reste intacte."""
        c = _base_v20()
        for m in (1234.5, 1234.4999999):
            c.execute("INSERT INTO entite_operations (entity, date, libelle, montant, nature, banque, compte) "
                      "VALUES ('SCI Exemple', '2026-01-02', 'x', ?, 'revenu', 'Banque', '0001')", (m,))
        with pytest.raises(sqlite3.IntegrityError):
            models._migration_021(c)
        assert [r[0] for r in c.execute('SELECT montant FROM entite_operations ORDER BY id')] \
            == [1234.5, 1234.4999999]
        assert 'STRICT' not in c.execute(
            "SELECT sql FROM sqlite_master WHERE name='entite_operations'").fetchone()[0]
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name LIKE '%__centimes'").fetchone()
