"""Tresorerie des entites : import de releves bancaires, bilan du levier."""
import io
import logging
import unicodedata

from flask import Blueprint, jsonify, request

from auth import login_required, csrf_protect
from models import get_db, validate_date, validate_number, validate_string, parse_number
from services import tresorerie_entite as svc

logger = logging.getLogger('financy')
tresorerie_bp = Blueprint('tresorerie', __name__)
MAX_BYTES = 5 * 1024 * 1024


def _corps():
    """Le corps JSON s'il est un objet, sinon un objet vide."""
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def _norm(s):
    s = unicodedata.normalize('NFD', s or '')
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').upper()


@tresorerie_bp.route('/api/entites/tresorerie', methods=['GET'])
@login_required
def liste():
    """Les entites qui ont des operations, avec leur bilan."""
    with get_db() as conn:
        noms = [r['entity'] for r in conn.execute(
            'SELECT DISTINCT entity FROM entite_operations ORDER BY entity')]
        return jsonify({'entites': [svc.bilan(conn, n) for n in noms], 'natures': svc.NATURES})


@tresorerie_bp.route('/api/entites/releves', methods=['POST'])
@login_required
@csrf_protect
def importer():
    """step=preview : lit et verifie un releve. step=commit : l'enregistre.
    Reimporter un releve n'ajoute rien : chaque operation est unique."""
    from services.parsers.releve_bancaire import lire_releve
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'Aucun fichier reçu'}), 400
    raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        return jsonify({'error': 'Fichier trop volumineux (5 Mo max)'}), 413
    if not raw.startswith(b'%PDF-'):
        return jsonify({'error': "Ce fichier n'est pas un PDF"}), 400
    try:
        rel = lire_releve(io.BytesIO(raw))
    except ValueError as e:
        return jsonify({'error': str(e)}), 422
    except Exception:
        logger.exception('Lecture releve bancaire')
        return jsonify({'error': "PDF illisible : ce n'est peut-être pas un relevé de compte"}), 422

    entity = request.form.get('entity') or None
    if not validate_string(entity, 200):
        return jsonify({'error': 'Entité trop longue'}), 400
    with get_db() as conn:
        entites = [r['name'] for r in conn.execute('SELECT name FROM entities')]
        entete = _norm(rel.entete)
        proposee = next((e for e in entites if _norm(e) in entete), None)
        apercu = {'banque': rel.banque, 'compte': rel.compte, 'debut': rel.debut, 'fin': rel.fin,
                  'solde_initial': rel.solde_initial, 'solde_final': rel.solde_final,
                  'operations': len(rel.operations), 'entite_proposee': proposee,
                  'fichier': f.filename[:200]}
        if request.args.get('step') != 'commit':
            return jsonify({'step': 'preview', 'releve': apercu})
        if not entity or entity not in entites:
            return jsonify({'error': 'Choisissez l’entité titulaire du compte'}), 400
        ajoutees, deja = svc.enregistrer(conn, entity, rel, f.filename[:200], svc.associes(conn, entity))
    return jsonify({'step': 'commit', 'ajoutees': ajoutees, 'deja': deja}), 201


@tresorerie_bp.route('/api/entites/operations/<int:oid>', methods=['PATCH'])
@login_required
@csrf_protect
def reclasser(oid):
    """Corrige la nature d'une operation mal classee."""
    nature = _corps().get('nature')
    if not isinstance(nature, str) or nature not in svc.NATURES:
        return jsonify({'error': 'Nature inconnue'}), 400
    with get_db() as conn:
        n = conn.execute('UPDATE entite_operations SET nature=? WHERE id=?', (nature, oid)).rowcount
    return (jsonify({'ok': True}), 200) if n else (jsonify({'error': 'Opération introuvable'}), 404)


@tresorerie_bp.route('/api/entites/<path:entite>/parts', methods=['PUT'])
@login_required
@csrf_protect
def enregistrer_parts(entite):
    """Remplace les parts detenues par l'entite. Chaque ligne : nom, parts,
    montant_souscrit, prix_souscription, prix_retrait (facultatif), date_prix."""
    lignes = _corps().get('parts')
    if not isinstance(lignes, list) or len(lignes) > 50:
        return jsonify({'error': 'Liste de parts attendue'}), 400
    propres = []
    vus = set()
    for l in lignes:
        if not isinstance(l, dict):
            return jsonify({'error': 'Chaque part doit être un objet'}), 400
        nom = l.get('nom')
        nom = nom.strip() if isinstance(nom, str) else ''
        if not nom or not validate_string(nom, 120):
            return jsonify({'error': 'Nom de part manquant ou trop long'}), 400
        if nom in vus:
            return jsonify({'error': f'{nom} : part en double'}), 400
        vus.add(nom)
        # validate_number accepte « 1 234,5 » ; float() le refusait ensuite.
        for k in ('parts', 'montant_souscrit', 'prix_souscription', 'prix_retrait'):
            if not validate_number(l.get(k)):
                return jsonify({'error': f'{nom} : {k} invalide'}), 400
        parts = parse_number(l.get('parts'))
        if not parts or parts <= 0:
            return jsonify({'error': f'{nom} : nombre de parts invalide'}), 400
        if l.get('date_prix') and not validate_date(l['date_prix']):
            return jsonify({'error': f'{nom} : date invalide'}), 400
        if not validate_string(l.get('source'), 200):
            return jsonify({'error': f'{nom} : source trop longue'}), 400
        propres.append(dict(l, nom=nom, parts=parts))
    with get_db() as conn:
        if not conn.execute('SELECT 1 FROM entities WHERE name=?', (entite,)).fetchone():
            return jsonify({'error': f'Entité inconnue : {entite}'}), 404
        conn.execute('DELETE FROM entite_parts WHERE entity=?', (entite,))
        for l in propres:
            conn.execute(
                'INSERT INTO entite_parts (entity, nom, parts, montant_souscrit, prix_souscription, '
                'prix_retrait, date_prix, source) VALUES (?,?,?,?,?,?,?,?)',
                (entite, l['nom'], l['parts'], parse_number(l.get('montant_souscrit')),
                 parse_number(l.get('prix_souscription')), parse_number(l.get('prix_retrait')),
                 l.get('date_prix') or None, l.get('source') or None))
        return jsonify(svc.parts(conn, entite) or {'lignes': []})


@tresorerie_bp.route('/api/entites/<path:entite>/exercices', methods=['PUT'])
@login_required
@csrf_protect
def enregistrer_exercices(entite):
    """Remplace les exercices clos de l'entite : fin, resultat fiscal, debut et
    source facultatifs. Un resultat negatif est un deficit reportable."""
    lignes = _corps().get('exercices')
    if not isinstance(lignes, list) or len(lignes) > 50:
        return jsonify({'error': 'Liste d’exercices attendue'}), 400
    fins = set()
    for l in lignes:
        if not isinstance(l, dict):
            return jsonify({'error': 'Chaque exercice doit être un objet'}), 400
        if not l.get('fin') or not validate_date(l['fin']) or (l.get('debut') and not validate_date(l['debut'])):
            return jsonify({'error': 'Date d’exercice invalide'}), 400
        if l['fin'] in fins:
            return jsonify({'error': f'Exercice clos le {l["fin"]} saisi deux fois'}), 400
        fins.add(l['fin'])
        if l.get('resultat') is None or not validate_number(l['resultat'], allow_negative=True):
            return jsonify({'error': f'Résultat invalide pour l’exercice clos le {l["fin"]}'}), 400
        if not validate_string(l.get('source'), 200):
            return jsonify({'error': 'Source trop longue'}), 400
    with get_db() as conn:
        if not conn.execute('SELECT 1 FROM entities WHERE name=?', (entite,)).fetchone():
            return jsonify({'error': f'Entité inconnue : {entite}'}), 404
        conn.execute('DELETE FROM entite_exercices WHERE entity=?', (entite,))
        for l in lignes:
            conn.execute('INSERT INTO entite_exercices (entity, debut, fin, resultat, source) VALUES (?,?,?,?,?)',
                         (entite, l.get('debut') or None, l['fin'], parse_number(l['resultat']),
                          l.get('source') or None))
        return jsonify({'exercices': svc.exercices(conn, entite)})
