import os
import sqlite3
from datetime import datetime


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
    return {
        'ok': True,
        'filename': backup_filename,
        'size_kb': size_kb,
        'timestamp': ts,
    }
