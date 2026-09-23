"""Revue B2 : entites — tresorerie des arretes preservee, renommage en
cascade, suppression refusee tant que prets et releves y sont rattaches."""
from datetime import datetime

from tests.test_api import client, fresh_db, CSRF_HEADERS  # noqa: F401

from models import get_db

H = CSRF_HEADERS
AUJ = datetime.now().strftime('%Y-%m-%d')


def _entite(client, nom='SCI Exemple', gross=100000, debt=40000):
    r = client.post('/api/entities', json={'name': nom, 'type': 'SCI', 'gross_assets': gross,
                                           'debt': debt}, headers=H)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _treso(nom, date=AUJ):
    with get_db() as conn:
        r = conn.execute('SELECT tresorerie FROM entity_snapshots WHERE entity_name=? AND date=?',
                         (nom, date)).fetchone()
    return r['tresorerie'] if r else 'absente'


class TestTresoreriePreservee:
    def test_modifier_l_entite_garde_la_tresorerie_du_jour(self, client):
        e = _entite(client)
        with get_db() as conn:
            conn.execute('UPDATE entity_snapshots SET tresorerie=500000 WHERE entity_name=?', (e['name'],))  # centimes
        r = client.put(f"/api/entities/{e['id']}", json={'name': e['name'], 'gross_assets': 110000,
                                                         'debt': 40000}, headers=H)
        assert r.status_code == 200
        assert _treso(e['name']) == 500000  # centimes
        with get_db() as conn:
            assert conn.execute('SELECT gross_assets FROM entity_snapshots WHERE entity_name=?',
                                (e['name'],)).fetchone()[0] == 11000000  # centimes

    def test_mise_a_jour_sans_tresorerie_ne_l_efface_pas(self):
        from services.snapshot import appliquer_mise_a_jour
        with get_db() as conn:
            conn.execute("INSERT INTO entities (name) VALUES ('SCI Exemple')")
            conn.execute("INSERT INTO entity_snapshots (entity_name, date, gross_assets, debt, tresorerie) "
                         "VALUES ('SCI Exemple', '2026-06-30', 9000000, 3000000, 400000)")  # centimes
            conn.execute("INSERT INTO positions (date, owner, category, value) VALUES ('2026-06-30', 'Paul', 'Actions', 1000)")  # centimes
            appliquer_mise_a_jour(conn, '2026-06-30', '2026-06-30', {},
                                  {'SCI Exemple': {'gross_assets': 95000, 'debt': 30000}})
            r = conn.execute("SELECT gross_assets, tresorerie FROM entity_snapshots "
                             "WHERE entity_name='SCI Exemple' AND date='2026-06-30'").fetchone()
        assert (r['gross_assets'], r['tresorerie']) == (9500000, 400000)  # centimes

    def test_mise_a_jour_avec_tresorerie_l_ecrit(self):
        from services.snapshot import appliquer_mise_a_jour
        with get_db() as conn:
            conn.execute("INSERT INTO entities (name) VALUES ('SCI Exemple')")
            conn.execute("INSERT INTO positions (date, owner, category, value) VALUES ('2026-06-30', 'Paul', 'Actions', 1000)")  # centimes
            appliquer_mise_a_jour(conn, '2026-06-30', '2026-06-30', {},
                                  {'SCI Exemple': {'gross_assets': 95000, 'debt': 0, 'tresorerie': '1 234,5'}})
            t = conn.execute("SELECT tresorerie FROM entity_snapshots WHERE entity_name='SCI Exemple'").fetchone()[0]
        assert t == 123450  # centimes

    def test_deplacer_un_arrete_recopie_la_tresorerie(self, client):
        with get_db() as conn:
            conn.execute("INSERT INTO entities (name) VALUES ('SCI Exemple')")
            conn.execute("INSERT INTO entity_snapshots (entity_name, date, gross_assets, debt, tresorerie) "
                         "VALUES ('SCI Exemple', '2026-06-30', 9000000, 3000000, 400000)")  # centimes
            conn.execute("INSERT INTO positions (date, owner, category, value) VALUES ('2026-06-30', 'Paul', 'Actions', 1000)")  # centimes
        r = client.post('/api/snapshots/rename', json={'from_date': '2026-06-30', 'to_date': '2026-07-01'},
                        headers=H)
        assert r.status_code == 200
        assert _treso('SCI Exemple', '2026-07-01') == 400000  # centimes


class TestRenommage:
    def test_le_nom_suit_dans_prets_releves_parts_exercices(self, client):
        e = _entite(client)
        with get_db() as conn:
            conn.execute("INSERT INTO prets (libelle, entity, montant) VALUES ('Prêt', 'SCI Exemple', 100000)")
            conn.execute("INSERT INTO entite_operations (entity, date, libelle, montant, nature) "
                         "VALUES ('SCI Exemple', '2026-01-02', 'x', 10, 'autre')")
            conn.execute("INSERT INTO entite_parts (entity, nom, parts) VALUES ('SCI Exemple', 'SCPI A', 10)")
            conn.execute("INSERT INTO entite_exercices (entity, fin, resultat) VALUES ('SCI Exemple', '2025-12-31', 0)")
            conn.execute("INSERT INTO entite_soldes_initiaux (entity, date, solde) VALUES ('SCI Exemple', '2026-01-01', 5)")
        r = client.put(f"/api/entities/{e['id']}", json={'name': 'SCI Nouvelle', 'gross_assets': 1, 'debt': 0},
                       headers=H)
        assert r.status_code == 200
        with get_db() as conn:
            for table in ('prets', 'entite_operations', 'entite_parts', 'entite_exercices',
                          'entite_soldes_initiaux'):
                assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE entity='SCI Nouvelle'").fetchone()[0] == 1, table
                assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE entity='SCI Exemple'").fetchone()[0] == 0

    def test_renommer_vers_un_nom_pris_est_refuse(self, client):
        e = _entite(client)
        _entite(client, 'Holding Exemple')
        r = client.put(f"/api/entities/{e['id']}", json={'name': 'Holding Exemple', 'gross_assets': 1, 'debt': 0},
                       headers=H)
        assert r.status_code == 409
        assert 'existe déjà' in r.get_json()['error']

    def test_creer_un_doublon_est_refuse(self, client):
        _entite(client)
        r = client.post('/api/entities', json={'name': 'SCI Exemple'}, headers=H)
        assert r.status_code == 409

    def test_nom_trop_long(self, client):
        e = _entite(client)
        assert client.post('/api/entities', json={'name': 'x' * 201}, headers=H).status_code == 400
        r = client.put(f"/api/entities/{e['id']}", json={'name': 'x' * 201}, headers=H)
        assert r.status_code == 400
        assert client.put(f"/api/entities/{e['id']}", json=['x'], headers=H).status_code == 400


class TestSuppression:
    def test_refusee_tant_qu_un_pret_y_est_rattache(self, client):
        e = _entite(client)
        with get_db() as conn:
            conn.execute("INSERT INTO prets (libelle, entity, montant) VALUES ('Prêt', 'SCI Exemple', 100000)")
            conn.execute("INSERT INTO entite_operations (entity, date, libelle, montant, nature) "
                         "VALUES ('SCI Exemple', '2026-01-02', 'x', 10, 'autre')")
        r = client.delete(f"/api/entities/{e['id']}?force=1", headers=H)
        assert r.status_code == 409
        body = r.get_json()
        assert 'prêt' in body['error'] and 'opération' in body['error']
        # Le front ne doit pas y voir la confirmation des positions liees.
        assert 'position(s) liée(s)' not in body['error'] and body['confirm_required'] is False
        assert body['dependances']['prets'] == 1
        with get_db() as conn:
            assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 1

    def test_acceptee_sans_dependance(self, client):
        e = _entite(client)
        assert client.delete(f"/api/entities/{e['id']}", headers=H).status_code == 204
