"""Revue B2 : la sauvegarde JSON couvre prets, releves, parts, exercices et
contrats ; le reset les vide ; l'import XLSX rattache les titres a
l'etablissement quand la feuille le donne."""
import io

from tests.test_api import client, fresh_db, CSRF_HEADERS  # noqa: F401

from models import get_db

H = CSRF_HEADERS
TABLES = ('prets', 'pret_echeances', 'entite_operations', 'entite_parts', 'entite_exercices',
          'entite_soldes_initiaux', 'contrats')


def _seed():
    with get_db() as conn:
        conn.execute("INSERT INTO entities (name, type) VALUES ('SCI Exemple', 'SCI')")
        conn.execute("INSERT INTO prets (id, libelle, entity, montant, taux, debut, fin) "
                     "VALUES (7, 'Prêt SCPI', 'SCI Exemple', 100000, 3.5, '2025-01-05', '2040-01-05')")
        for rang in (1, 2):
            conn.execute('INSERT INTO pret_echeances VALUES (7, ?, ?, 300, 290, 10, ?)',
                         (rang, f'2025-0{rang}-05', 100000 - 300 * rang))
        conn.execute("INSERT INTO entite_operations (entity, date, libelle, montant, nature, banque, compte) "
                     "VALUES ('SCI Exemple', '2026-01-10', 'SCPI A DISTRIBUTION', 350, 'revenu', 'Qonto', '0001')")
        conn.execute("INSERT INTO entite_parts (entity, nom, parts, montant_souscrit) VALUES ('SCI Exemple', 'SCPI A', 40, 10000)")
        conn.execute("INSERT INTO entite_exercices (entity, fin, resultat) VALUES ('SCI Exemple', '2025-12-31', -1200)")
        conn.execute("INSERT INTO entite_soldes_initiaux (entity, banque, compte, date, solde) "
                     "VALUES ('SCI Exemple', 'Qonto', '0001', '2026-01-01', 800)")
        conn.execute("INSERT INTO contrats (owner, envelope, establishment, date_effet) "
                     "VALUES ('Paul', 'Assurance-vie', 'Assureur X', '2015-03-01')")


def _compter():
    with get_db() as conn:
        return {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in TABLES}


def test_export_reset_import_restitue_tout(client):
    _seed()
    avant = _compter()
    exp = client.get('/api/export').get_json()
    for t in TABLES:
        assert len(exp[t]) == avant[t], t

    r = client.post('/api/reset', json={'confirm': 'VIDER'}, headers=H).get_json()
    for t in TABLES:
        assert r['deleted'][t] == avant[t], t
    assert all(v == 0 for v in _compter().values())

    rapport = client.post('/api/import-json', json=exp, headers=H).get_json()
    assert _compter() == avant
    assert rapport['prets'] == 1 and rapport['pret_echeances'] == 2
    with get_db() as conn:
        pid = conn.execute('SELECT id FROM prets').fetchone()[0]
        assert conn.execute('SELECT COUNT(*) FROM pret_echeances WHERE pret_id=?', (pid,)).fetchone()[0] == 2


def test_reimporter_n_ajoute_rien(client):
    _seed()
    avant = _compter()
    exp = client.get('/api/export').get_json()
    rapport = client.post('/api/import-json', json=exp, headers=H).get_json()
    assert _compter() == avant
    assert rapport['prets'] == 0 and rapport['pret_echeances'] == 0


def test_l_existant_l_emporte(client):
    _seed()
    exp = client.get('/api/export').get_json()
    exp['entite_parts'][0]['parts'] = 999
    exp['contrats'][0]['date_effet'] = '2020-01-01'
    client.post('/api/import-json', json=exp, headers=H)
    with get_db() as conn:
        assert conn.execute('SELECT parts FROM entite_parts').fetchone()[0] == 40
        assert conn.execute('SELECT date_effet FROM contrats').fetchone()[0] == '2015-03-01'


def test_lignes_invalides_ecartees(client):
    rapport = client.post('/api/import-json', headers=H, json={
        'entite_operations': [{'entity': 'SCI Exemple', 'date': 'hier', 'libelle': 'x', 'montant': 1},
                              {'entity': 'SCI Exemple', 'date': '2026-01-01', 'libelle': 'x', 'montant': 'abc'},
                              {'entity': 'SCI Exemple', 'date': '2026-01-02', 'libelle': 'y', 'montant': '12,5',
                               'nature': 'inventee'}],
        'pret_echeances': [{'pret_id': 99, 'rang': 1, 'date': '2026-01-01', 'capital': 1, 'crd': 1}],
    }).get_json()
    assert rapport['entite_operations'] == 1 and rapport['skipped'] == 3
    with get_db() as conn:
        r = conn.execute('SELECT montant, nature FROM entite_operations').fetchone()
    assert (r['montant'], r['nature']) == (12.5, 'autre')


def _xlsx(holdings_entete, holdings):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Positions'
    ws.append(['date', 'owner', 'category', 'envelope', 'establishment', 'value', 'debt'])
    ws.append(['2026-06-30', 'Paul', 'Actions', 'Assurance-vie', 'Assureur A', 0, 0])
    ws.append(['2026-06-30', 'Paul', 'Actions', 'Assurance-vie', 'Assureur B', 0, 0])
    wh = wb.create_sheet('Holdings')
    wh.append(holdings_entete)
    for h in holdings:
        wh.append(h)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _titres_par_etab():
    with get_db() as conn:
        return {r['establishment']: r['n'] for r in conn.execute(
            'SELECT p.establishment, COUNT(h.id) n FROM positions p LEFT JOIN holdings h ON h.position_id=p.id '
            'GROUP BY p.establishment')}


def test_xlsx_titres_rattaches_a_leur_etablissement(client):
    entete = ['date', 'owner', 'category', 'envelope', 'entity', 'isin', 'quantity',
              'cost_basis', 'market_value', 'as_of_date', 'Établissement']
    buf = _xlsx(entete, [
        ['2026-06-30', 'Paul', 'Actions', 'Assurance-vie', None, 'FR0010315770', 10, 1000, 1100, None, 'Assureur A'],
        ['2026-06-30', 'Paul', 'Actions', 'Assurance-vie', None, 'IE00B4L5Y983', 5, 500, 550, None, 'Assureur B'],
    ])
    r = client.post('/api/import', data={'file': (buf, 'p.xlsx')}, headers=H, content_type='multipart/form-data')
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['holdings'] == 2
    assert _titres_par_etab() == {'Assureur A': 1, 'Assureur B': 1}


def test_xlsx_sans_colonne_etablissement_reste_compatible(client):
    entete = ['date', 'owner', 'category', 'envelope', 'entity', 'isin', 'quantity']
    buf = _xlsx(entete, [['2026-06-30', 'Paul', 'Actions', 'Assurance-vie', None, 'FR0010315770', 10]])
    r = client.post('/api/import', data={'file': (buf, 'p.xlsx')}, headers=H, content_type='multipart/form-data')
    assert r.get_json()['holdings'] == 1
