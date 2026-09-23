"""Revue B2 : l'ensemble mesurable ne compte que les flux des comptes gardes."""
from tests.test_api import client, fresh_db  # noqa: F401

from models import get_db


def _pos(conn, date, etab, value):
    conn.execute("INSERT INTO positions (date, owner, category, envelope, establishment, value) "
                 "VALUES (?, 'Paul', 'Actions', 'Assurance-vie', ?, ?)", (date, etab, value))


def test_le_versement_d_un_compte_clos_n_entre_pas_dans_l_ensemble(client):
    with get_db() as conn:
        for d, a, b in (('2025-01-01', 10000, 5000), ('2025-07-01', 10500, 8100), ('2026-01-01', 11000, None)):
            _pos(conn, d, 'Assureur A', a)
            if b is not None:
                _pos(conn, d, 'Assureur B', b)
        # Versement sur le contrat B, clos depuis : il n'a rien a faire dans
        # l'ensemble, qui ne garde que le contrat A.
        conn.execute("INSERT INTO flux (date, owner, envelope, establishment, type, amount) "
                     "VALUES ('2025-03-01', 'Paul', 'Assurance-vie', 'Assureur B', 'Versement', 3000)")
    data = client.get('/api/performance').get_json()
    glob = data['global']
    assert glob['accounts'] == 1
    assert glob['flux_count'] == 0 and glob['flux_net'] == 0
    assert abs(glob['twr'] - 0.10) < 1e-9


def test_le_versement_du_compte_garde_compte(client):
    with get_db() as conn:
        for d, a in (('2025-01-01', 10000), ('2025-07-01', 13500), ('2026-01-01', 14000)):
            _pos(conn, d, 'Assureur A', a)
        conn.execute("INSERT INTO flux (date, owner, envelope, establishment, type, amount) "
                     "VALUES ('2025-03-01', 'Paul', 'Assurance-vie', 'Assureur A', 'Versement', 3000)")
    glob = client.get('/api/performance').get_json()['global']
    assert glob['flux_count'] == 1 and glob['flux_net'] == 3000
