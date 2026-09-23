"""
Acces aux parametres applicatifs stockes dans la table config (cle 'settings'),
et aux secrets (cle d'API), stockes hors de la base.

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


# ─── Secrets ──────────────────────────────────────────────────────────────────
#
# Une cle d'API ne va ni dans la base ni dans le depot : la base est recopiee
# dans chaque sauvegarde et chaque export, et le depot est public. Elle vit dans
# un fichier a part, a cote de la base (hors git : `secrets.json` est ignore),
# lisible par le seul proprietaire. La variable d'environnement, si elle
# existe, a toujours la priorite.

NOM_FICHIER_SECRETS = 'secrets.json'


def _chemin_secrets():
    import models
    return os.path.join(os.path.dirname(os.path.abspath(models.DB_PATH)), NOM_FICHIER_SECRETS)


def lire_secrets():
    try:
        with open(_chemin_secrets(), encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def ecrire_secret(nom, valeur):
    """Ecrit (ou retire, si `valeur` est vide) un secret, fichier en 0600."""
    secrets = lire_secrets()
    if valeur:
        secrets[nom] = valeur
    else:
        secrets.pop(nom, None)
    chemin = _chemin_secrets()
    tmp = chemin + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(secrets, f)
    os.replace(tmp, chemin)


def migrer_cle_depuis_la_base(conn):
    """Une cle enregistree en base par une version precedente passe dans le
    fichier de secrets, puis quitte la base."""
    row = conn.execute("SELECT value FROM config WHERE key='settings'").fetchone()
    s = json.loads(row['value']) if row else {}
    cle = s.pop('anthropic_api_key', None)
    if cle:
        if not lire_secrets().get('anthropic_api_key'):
            ecrire_secret('anthropic_api_key', cle)
        save_settings(conn, s)


def get_api_key():
    """Cle API Anthropic : variable d'environnement, sinon fichier de secrets."""
    return os.environ.get('ANTHROPIC_API_KEY') or lire_secrets().get('anthropic_api_key')
