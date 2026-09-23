import json
import os
from flask import Blueprint, jsonify, request
from models import get_db, load_referential, REFERENTIAL_TEMPLATES, parse_number, get_db_path, validate_string
from auth import login_required, csrf_protect

referential_bp = Blueprint('referential', __name__)

MAX_ALERTES = 100
MAX_LIBELLE = 200
_OPERATEURS = ('<', '>', '<=', '>=')


def _erreur_cibles(data):
    """Allocation cible : {categorie: pourcentage de 0 a 100}."""
    if len(data) > 200:
        return 'Trop de catégories'
    for cat, v in data.items():
        if not cat or len(cat) > MAX_LIBELLE:
            return 'Nom de catégorie invalide'
        n = parse_number(v) if not isinstance(v, bool) else None
        if n is None or n < 0 or n > 100:
            return f'{cat} : pourcentage entre 0 et 100 attendu'
    return None


def _erreur_alertes(data):
    """Alertes : [{label, metric, category, op, threshold}]."""
    if len(data) > MAX_ALERTES:
        return f'{MAX_ALERTES} alertes au plus'
    for a in data:
        if not isinstance(a, dict):
            return 'Chaque alerte doit être un objet'
        for champ in ('label', 'metric', 'category'):
            v = a.get(champ)
            if v is not None and (not isinstance(v, str) or len(v) > MAX_LIBELLE):
                return f'Alerte : {champ} invalide'
        if a.get('op') is not None and a['op'] not in _OPERATEURS:
            return f'Alerte : opérateur attendu parmi {" ".join(_OPERATEURS)}'
        t = a.get('threshold')
        if t is not None and (isinstance(t, bool) or parse_number(t) is None):
            return 'Alerte : seuil numérique attendu'
    return None


@referential_bp.route('/api/config')
@login_required
def get_config():
    with get_db() as conn:
        entity_names = [r['name'] for r in
                        conn.execute('SELECT name FROM entities ORDER BY name').fetchall()]
        ref = load_referential(conn)
    return jsonify({
        'owners':               ref['owners'],
        'categories':           ref['categories'],
        'envelopes':            list(ref['envelope_meta'].keys()),
        'flux_types':           ref['flux_types'],
        'liquidity_order':      ref['liquidity_order'],
        'category_mobilizable': ref['category_mobilizable'],
        'envelope_meta':        ref['envelope_meta'],
        'entity_types':         ref['entity_types'],
        'valuation_modes':      ref['valuation_modes'],
        'entity_names':         entity_names,
    })


# — Allocation cible —

@referential_bp.route('/api/targets', methods=['GET'])
@login_required
def get_targets():
    with get_db() as conn:
        row = conn.execute("SELECT value FROM config WHERE key='allocation_targets'").fetchone()
    if row:
        try:
            return jsonify(json.loads(row['value']))
        except Exception:
            pass
    return jsonify({})


@referential_bp.route('/api/targets', methods=['PUT'])
@login_required
@csrf_protect
def save_targets():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Objet JSON attendu'}), 400
    err = _erreur_cibles(data)
    if err:
        return jsonify({'error': err}), 400
    data = {cat: parse_number(v) for cat, v in data.items()}
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES ('allocation_targets', ?)",
            (json.dumps(data),)
        )
    return jsonify({'ok': True})


# — Alertes —

@referential_bp.route('/api/alerts', methods=['GET'])
@login_required
def get_alerts():
    with get_db() as conn:
        row = conn.execute("SELECT value FROM config WHERE key='user_alerts'").fetchone()
    if row:
        try:
            return jsonify(json.loads(row['value']))
        except Exception:
            pass
    return jsonify([])


@referential_bp.route('/api/alerts', methods=['PUT'])
@login_required
@csrf_protect
def save_alerts_api():
    data = request.get_json(silent=True)
    if not isinstance(data, list):
        return jsonify({'error': 'Tableau JSON attendu'}), 400
    err = _erreur_alertes(data)
    if err:
        return jsonify({'error': err}), 400
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES ('user_alerts', ?)",
            (json.dumps(data),)
        )
    return jsonify({'ok': True})


# — Référentiel —

@referential_bp.route('/api/referential/templates', methods=['GET'])
@login_required
def get_templates():
    return jsonify({name: tpl for name, tpl in REFERENTIAL_TEMPLATES.items()})


@referential_bp.route('/api/referential', methods=['GET'])
@login_required
def get_referential_api():
    with get_db() as conn:
        ref = load_referential(conn)
    return jsonify(ref)


@referential_bp.route('/api/referential', methods=['PUT'])
@login_required
@csrf_protect
def save_referential():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Objet JSON attendu'}), 400
    required = ['owners', 'categories', 'category_mobilizable', 'envelope_meta']
    for k in required:
        if k not in data:
            return jsonify({'error': f'Champ manquant : {k}'}), 400
    if not data['owners']:
        return jsonify({'error': 'La liste des propriétaires ne peut pas être vide'}), 400
    for k in ('owners', 'categories'):
        v = data[k]
        if (not isinstance(v, list) or len(v) > 500
                or any(not isinstance(x, str) or not x.strip() or len(x) > MAX_LIBELLE for x in v)):
            return jsonify({'error': f'{k} : liste de noms attendue ({MAX_LIBELLE} car. max)'}), 400
    for k in ('category_mobilizable', 'envelope_meta'):
        if not isinstance(data[k], dict):
            return jsonify({'error': f'{k} : objet attendu'}), 400
    data.pop('liquidity_order', None)
    renommages = data.pop('renommages', None) or []
    err = _valider_renommages(renommages, data)
    if err:
        return jsonify({'error': err}), 400
    if renommages:
        # Un renommage reecrit des positions et des flux : copie datee d'abord.
        from services.backups import create_db_backup
        create_db_backup(get_db_path())
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        propages = _appliquer_renommages(conn, renommages)
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES ('referential', ?)",
            (json.dumps(data),)
        )
    return jsonify({'ok': True, 'renommages': propages})


# Renommer une categorie ou une enveloppe changeait la seule cle du
# referentiel : positions et flux gardaient l'ancien nom. Sur la base de prod,
# renommer « Actions » faisait disparaitre 110 000 € de la repartition et
# retomber leur taux de mobilisation au defaut. Le renommage se propage
# desormais, dans la meme transaction que le referentiel.
_CHAMPS = {'category': ('categories', 'la catégorie'), 'envelope': ('envelope_meta', "l'enveloppe")}


def _valider_renommages(renommages, ref):
    if not isinstance(renommages, list):
        return 'renommages : liste attendue'
    for r in renommages:
        if not isinstance(r, dict) or r.get('champ') not in _CHAMPS:
            return 'Renommage invalide'
        a, n = (r.get('ancien') or '').strip(), (r.get('nouveau') or '').strip()
        if not a or not n or len(n) > 80:
            return 'Renommage invalide : nom vide ou trop long'
        liste = ref.get(_CHAMPS[r['champ']][0]) or []
        if list(liste).count(n) > 1:
            return (f'« {n} » existe deja dans le referentiel : renommer {_CHAMPS[r["champ"]][1]} '
                    f'« {a} » en « {n} » fusionnerait les deux sans le dire')
    return None


def _appliquer_renommages(conn, renommages):
    out = []
    for r in renommages:
        champ, a, n = r['champ'], r['ancien'].strip(), r['nouveau'].strip()
        if a == n:
            continue
        nb_pos = conn.execute(f'UPDATE positions SET {champ}=? WHERE {champ}=?', (n, a)).rowcount
        nb_flux = conn.execute(f'UPDATE flux SET {champ}=? WHERE {champ}=?', (n, a)).rowcount
        if champ == 'category':
            conn.execute("UPDATE allocation_targets SET bucket_name=? WHERE bucket_type='category' AND bucket_name=?", (n, a))
            for cle in ('allocation_targets', 'user_alerts'):
                row = conn.execute('SELECT value FROM config WHERE key=?', (cle,)).fetchone()
                if not row:
                    continue
                try:
                    v = json.loads(row['value'])
                except Exception:
                    continue
                if isinstance(v, dict) and a in v:
                    v[n] = v.pop(a)
                elif isinstance(v, list):
                    for x in v:
                        if isinstance(x, dict) and x.get('category') == a:
                            x['category'] = n
                conn.execute('UPDATE config SET value=? WHERE key=?', (json.dumps(v), cle))
        out.append({'champ': champ, 'ancien': a, 'nouveau': n, 'positions': nb_pos, 'flux': nb_flux})
    return out


@referential_bp.route('/api/referential/usage', methods=['GET'])
@login_required
def referential_usage():
    """Nombre de positions et de flux, toutes dates, qui portent une valeur."""
    champ, valeur = request.args.get('champ'), request.args.get('valeur')
    if champ not in ('owner', 'category', 'envelope') or not valeur:
        return jsonify({'error': 'champ (owner|category|envelope) et valeur requis'}), 400
    with get_db() as conn:
        n_pos = conn.execute(f'SELECT COUNT(*) FROM positions WHERE {champ}=?', (valeur,)).fetchone()[0]
        n_flux = conn.execute(f'SELECT COUNT(*) FROM flux WHERE {champ}=?', (valeur,)).fetchone()[0]
    return jsonify({'positions': n_pos, 'flux': n_flux})


@referential_bp.route('/api/referential/orphans', methods=['GET'])
@login_required
def check_orphans():
    """Vérifie les positions/flux orphelins si une catégorie ou enveloppe est supprimée."""
    with get_db() as conn:
        ref = load_referential(conn)
        categories = set(ref['categories'])
        envelopes  = set(ref.get('envelope_meta', {}).keys())

        orphans = {}

        # Catégories utilisées dans positions mais absentes du référentiel
        cat_rows = conn.execute(
            'SELECT DISTINCT category FROM positions WHERE category IS NOT NULL'
        ).fetchall()
        for r in cat_rows:
            cat = r['category']
            if cat and cat not in categories:
                cnt = conn.execute('SELECT COUNT(*) as c FROM positions WHERE category=?', (cat,)).fetchone()['c']
                orphans.setdefault('categories', {})[cat] = cnt

        # Enveloppes utilisées dans positions/flux mais absentes du référentiel
        env_rows = conn.execute(
            'SELECT DISTINCT envelope FROM positions WHERE envelope IS NOT NULL '
            'UNION SELECT DISTINCT envelope FROM flux WHERE envelope IS NOT NULL'
        ).fetchall()
        for r in env_rows:
            env = r['envelope']
            if env and env not in envelopes:
                pos_cnt = conn.execute('SELECT COUNT(*) as c FROM positions WHERE envelope=?', (env,)).fetchone()['c']
                flux_cnt = conn.execute('SELECT COUNT(*) as c FROM flux WHERE envelope=?', (env,)).fetchone()['c']
                if pos_cnt or flux_cnt:
                    orphans.setdefault('envelopes', {})[env] = {'positions': pos_cnt, 'flux': flux_cnt}

    return jsonify(orphans)


# — Parametres applicatifs (cles API, etc.) —

from services.settings import load_settings as _load_settings, save_settings as _save_settings


@referential_bp.route('/api/settings', methods=['GET'])
@login_required
def get_settings():
    from services.settings import lire_secrets, migrer_cle_depuis_la_base
    with get_db() as conn:
        migrer_cle_depuis_la_base(conn)
    api_key = lire_secrets().get('anthropic_api_key', '')
    env_key = os.environ.get('ANTHROPIC_API_KEY', '')
    result = {
        'anthropic_api_key_set': bool(api_key),
        'anthropic_api_key_masked': (api_key[:10] + '...' + api_key[-4:]) if len(api_key) > 14 else '',
        'anthropic_api_key_env': bool(env_key),
        # L'environnement l'emporte toujours sur le fichier de secrets.
        'effective_source': 'env' if env_key else ('fichier' if api_key else 'none'),
        'llm_available': bool(env_key or api_key),
    }
    return jsonify(result)


@referential_bp.route('/api/settings', methods=['PUT'])
@login_required
@csrf_protect
def update_settings():
    from services.settings import ecrire_secret, migrer_cle_depuis_la_base
    d = request.get_json(silent=True)
    if not isinstance(d, dict) or not d:
        return jsonify({'error': 'Corps requis'}), 400
    with get_db() as conn:
        migrer_cle_depuis_la_base(conn)
        if 'anthropic_api_key' in d:
            key = (d['anthropic_api_key'] or '').strip()
            if key and not key.startswith('sk-ant-'):
                return jsonify({'error': 'Format de cle invalide (attendu : sk-ant-...)'}), 400
            if not validate_string(key, 300):
                return jsonify({'error': 'Cle trop longue'}), 400
            # Hors de la base : ni sauvegarde ni export ne l'emportent.
            ecrire_secret('anthropic_api_key', key or None)
    return jsonify({'ok': True})
