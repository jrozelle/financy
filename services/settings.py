"""
Acces aux parametres applicatifs stockes dans la table config (cle 'settings').

Fournit un cache TTL leger pour eviter les round-trips DB repetitifs
(ex: _get_api_key est appele plusieurs fois par requete advisor).
"""
import json
import os
import time

_cache = {'data': None, 'ts': 0}
_CACHE_TTL = 5  # secondes


def _load_settings_from_db():
    from models import get_db
    with get_db() as conn:
        row = conn.execute("SELECT value FROM config WHERE key='settings'").fetchone()
        return json.loads(row['value']) if row else {}


def load_settings():
    """Charge les settings avec cache TTL de 5s."""
    now = time.monotonic()
    if _cache['data'] is not None and (now - _cache['ts']) < _CACHE_TTL:
        return _cache['data']
    try:
        data = _load_settings_from_db()
    except Exception:
        return _cache['data'] or {}
    _cache['data'] = data
    _cache['ts'] = now
    return data


def save_settings(conn, settings):
    """Ecrit les settings en DB et invalide le cache."""
    conn.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES ('settings', ?)",
        (json.dumps(settings),)
    )
    _cache['data'] = None
    _cache['ts'] = 0


def invalidate_cache():
    _cache['data'] = None
    _cache['ts'] = 0


def get_api_key():
    """Cle API Anthropic : DB settings d'abord, puis env var."""
    try:
        s = load_settings()
        db_key = s.get('anthropic_api_key')
        if db_key:
            return db_key
    except Exception:
        pass
    return os.environ.get('ANTHROPIC_API_KEY')
