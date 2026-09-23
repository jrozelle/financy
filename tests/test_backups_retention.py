"""Rotation des copies de la base : 30 jours entiers, puis une par mois, et
jamais moins des dix plus recentes."""
import os
from datetime import datetime

from services.backups import a_supprimer, copies, purger, _date_de

MAINTENANT = datetime(2026, 9, 23, 12, 0)


def test_dates_des_deux_familles():
    assert _date_de('patrimoine.db.bak-20260702-1750-before-snapdelete') == datetime(2026, 7, 2, 17, 50)
    assert _date_de('patrimoine_20260923_110512_123456.db') == datetime(2026, 9, 23, 11, 5, 12)
    assert _date_de('notes.txt') is None


def _liste(*dates):
    return sorted(((f'/d/{d}', datetime.strptime(d, '%Y%m%d')) for d in dates), key=lambda x: x[1], reverse=True)


def test_une_par_mois_au_dela_de_trente_jours():
    anciennes = ['20260301', '20260315', '20260320', '20260402', '20260428']
    recentes = [f'202609{j:02d}' for j in range(10, 22)]         # 12 copies de septembre
    supprimees = a_supprimer(_liste(*anciennes, *recentes), MAINTENANT)
    assert sorted(supprimees) == ['/d/20260301', '/d/20260315', '/d/20260402']


def test_jamais_moins_des_dix_plus_recentes():
    vieilles = [f'202401{j:02d}' for j in range(1, 13)]           # douze copies de janvier 2024
    supprimees = a_supprimer(_liste(*vieilles), MAINTENANT)
    assert len(supprimees) == 2 and '/d/20240112' not in supprimees


def test_purge_reelle_et_fichiers_inconnus_intacts(tmp_path):
    db = tmp_path / 'patrimoine.db'
    db.write_bytes(b'x')
    (tmp_path / 'backups').mkdir()
    for j in range(1, 13):
        (tmp_path / f'patrimoine.db.bak-202401{j:02d}-1200-test').write_bytes(b'x')
    (tmp_path / 'backups' / 'lisez-moi.txt').write_text('garde')
    simulees = purger(str(db), simulation=True)
    assert len(simulees) == 2 and all(os.path.exists(c) for c in simulees)
    assert purger(str(db)) == simulees and not any(os.path.exists(c) for c in simulees)
    assert (tmp_path / 'backups' / 'lisez-moi.txt').exists() and db.exists()
    assert len(copies(str(db))) == 10
