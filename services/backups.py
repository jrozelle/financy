import os
import re as _re
import sqlite3
from datetime import datetime, timedelta as _timedelta


def create_db_backup(db_path, backup_dir=None):
    """Create a consistent SQLite backup and return its metadata."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)

    backup_dir = backup_dir or os.path.join(os.path.dirname(db_path), 'backups')
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    db_name = os.path.splitext(os.path.basename(db_path))[0]
    backup_filename = f'{db_name}_{ts}.db'
    backup_path = os.path.join(backup_dir, backup_filename)

    with sqlite3.connect(db_path) as source:
        with sqlite3.connect(backup_path) as target:
            source.backup(target)

    size_kb = round(os.path.getsize(backup_path) / 1024, 1)
    # La rotation suit chaque copie : jamais en tache de fond, et jamais sans
    # que la copie du jour existe. Un echec de purge ne fait pas echouer la copie.
    try:
        purger(db_path)
    except OSError:
        pass
    return {
        'ok': True,
        'filename': backup_filename,
        'size_kb': size_kb,
        'timestamp': ts,
    }


# ─── Rotation ────────────────────────────────────────────────────────────────
#
# Deux familles de copies : celles de l'application (backups/patrimoine_AAAAMMJJ_...db)
# et celles faites a la main avant une intervention (patrimoine.db.bak-AAAAMMJJ-HHMM-motif).
# Tout est garde 30 jours ; au-dela, la derniere copie de chaque mois ; et jamais
# moins des dix plus recentes, quel que soit leur age.

RETENTION_JOURS = 30
MIN_RECENTES = 10

_AUTO = _re.compile(r'_(\d{8})_(\d{6})_\d+\.db$')
_MANUELLE = _re.compile(r'\.bak-(\d{8})-(\d{4})')


def _date_de(nom):
    m = _AUTO.search(nom)
    if m:
        return datetime.strptime(m[1] + m[2], '%Y%m%d%H%M%S')
    m = _MANUELLE.search(nom)
    if m:
        return datetime.strptime(m[1] + m[2], '%Y%m%d%H%M')
    return None                      # nom inconnu : jamais supprime


def copies(db_path):
    """Les copies de la base, (chemin, date), de la plus recente a la plus ancienne."""
    dossier = os.path.dirname(db_path)
    base = os.path.basename(db_path)
    candidats = [os.path.join(dossier, n) for n in os.listdir(dossier) if n.startswith(base + '.bak-')]
    auto = os.path.join(dossier, 'backups')
    if os.path.isdir(auto):
        candidats += [os.path.join(auto, n) for n in os.listdir(auto)]
    datees = [(c, _date_de(os.path.basename(c))) for c in candidats if os.path.isfile(c)]
    return sorted(((c, d) for c, d in datees if d), key=lambda x: x[1], reverse=True)


def a_supprimer(liste, maintenant=None):
    """Les chemins que la regle de retention ne garde pas."""
    maintenant = maintenant or datetime.now()
    garder = {c for c, _ in liste[:MIN_RECENTES]}
    garder |= {c for c, d in liste if maintenant - d <= _timedelta(days=RETENTION_JOURS)}
    vus = set()
    for c, d in liste:                              # du plus recent au plus ancien
        if (d.year, d.month) not in vus:
            vus.add((d.year, d.month))
            garder.add(c)
    return [c for c, _ in liste if c not in garder]


def purger(db_path, simulation=False):
    """Applique la retention. Renvoie les copies supprimees (ou qui le seraient)."""
    cibles = a_supprimer(copies(db_path))
    if not simulation:
        for c in cibles:
            os.remove(c)
    return cibles


if __name__ == '__main__':
    # python -m services.backups [--appliquer] : liste ce que la retention supprimerait.
    import sys
    from models import DB_PATH
    appliquer = '--appliquer' in sys.argv
    cibles = purger(DB_PATH, simulation=not appliquer)
    for c in cibles:
        print(('supprime ' if appliquer else 'a supprimer ') + os.path.basename(c))
    # En simulation, les cibles sont encore la : elles ne comptent pas parmi les gardees.
    gardees = len(copies(DB_PATH)) - (0 if appliquer else len(cibles))
    print(f'{len(cibles)} copie(s) {"supprimee(s)" if appliquer else "a supprimer (simulation)"}, '
          f'{gardees} gardee(s)')
