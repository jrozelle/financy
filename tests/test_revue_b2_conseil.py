"""Revue B2 : conseil — credits vus a la part de dette du titulaire, mise a
jour partielle d'un objectif validee, erreur du LLM non divulguee."""
import os

os.environ['ADVISOR_LLM_PROVIDER'] = 'mock'

from tests.test_api import client, fresh_db, CSRF_HEADERS  # noqa: E402,F401

from models import get_db  # noqa: E402

H = CSRF_HEADERS
D = '2026-09-01'


def _indivision(conn):
    conn.execute("INSERT INTO entities (name, type) VALUES ('Maison', 'Indivision')")
    for owner, dp in (('Paul', 0.34), ('Claire', 0.66), ('Lea', 0.0)):
        conn.execute("INSERT INTO positions (date, owner, category, envelope, value, entity, ownership_pct, debt_pct) "
                     "VALUES (?, ?, 'Immobilier', 'Immobilier', 0, 'Maison', 0.5, ?)", (D, owner, dp))
    conn.execute("INSERT INTO prets (id, libelle, entity, montant, taux, debut, fin) "
                 "VALUES (1, 'Prêt maison', 'Maison', 10000000, 1.1, '2026-01-05', '2036-12-05')")
    crd = 10000000                     # centimes
    for i in range(1, 13):
        crd -= 70000
        conn.execute('INSERT INTO pret_echeances VALUES (1, ?, ?, 70000, 9000, 0, ?)', (i, f'2027-{i:02d}-05', crd))


def _credits(owner):
    from services.advisor.constats import constats
    with get_db() as conn:
        return [k for k in constats(conn, D, owner)['constats'] if k['onglet'] == 'credits']


class TestCreditsALaPart:
    def test_montant_a_la_part_de_dette(self):
        with get_db() as conn:
            _indivision(conn)
        (tout,) = _credits(None)
        (paul,) = _credits('Paul')
        assert tout['montant'] == 100000
        assert paul['montant'] == 34000
        assert '⟦34000.0⟧' in paul['detail']

    def test_sans_part_de_dette_le_credit_ne_le_concerne_pas(self):
        with get_db() as conn:
            _indivision(conn)
        assert _credits('Lea') == []


class TestTresorerieDeSociete:
    def test_meme_regle_que_l_allocation(self):
        """Libelle ou entite au nom d'une entite : tresorerie de societe. Une
        categorie qui porte ce nom ne suffit plus, comme dans l'allocation."""
        from services.advisor.constats import constats
        with get_db() as conn:
            conn.execute("INSERT INTO entities (name, type) VALUES ('Holding Exemple', 'Holding')")
            conn.execute("INSERT INTO positions (date, owner, category, envelope, value, label) "
                         "VALUES (?, 'Paul', 'Cash & dépôts', 'Compte courant', 20000, 'Holding Exemple')", (D,))
            assert not [k for k in constats(conn, D)['constats'] if 'comptes courants' in k['titre']]
            conn.execute("INSERT INTO positions (date, owner, category, envelope, value) "
                         "VALUES (?, 'Paul', 'Holding Exemple', 'Compte courant', 16000)", (D,))
            ks = [k for k in constats(conn, D)['constats'] if 'comptes courants' in k['titre']]
        assert len(ks) == 1 and ks[0]['montant'] == 16000


class TestObjectifs:
    def _objectif(self, client):
        client.put('/api/advisor/profiles/Personne 1', json={'horizon_years': 10, 'risk_tolerance': 4}, headers=H)
        r = client.post('/api/advisor/profiles/Personne 1/objectives',
                        json={'label': 'Retraite', 'target_amount': 100000, 'priority': 2}, headers=H)
        assert r.status_code == 201, r.get_json()
        return r.get_json()['id']

    def test_priorite_hors_bornes_refusee(self, client):
        oid = self._objectif(client)
        r = client.patch(f'/api/advisor/objectives/{oid}', json={'priority': 9}, headers=H)
        assert r.status_code == 400
        assert 'priority' in r.get_json()['error']

    def test_mise_a_jour_partielle_acceptee(self, client):
        oid = self._objectif(client)
        r = client.patch(f'/api/advisor/objectives/{oid}', json={'priority': 4}, headers=H)
        assert r.status_code == 200
        assert client.patch(f'/api/advisor/objectives/{oid}', json={'target_amount': 'abc'},
                            headers=H).status_code == 400


class TestMacroErreur:
    def test_le_message_d_exception_n_est_pas_renvoye(self, client, monkeypatch):
        from services.advisor import macro

        def _boum(conn):
            raise RuntimeError('cle secrete sk-ant-xxxx refusee par https://interne')
        monkeypatch.setattr(macro, 'generate_snapshot', _boum)
        r = client.post('/api/advisor/macro/refresh', headers=H)
        assert r.status_code == 503
        assert 'sk-ant' not in r.get_json()['error'] and 'interne' not in r.get_json()['error']
