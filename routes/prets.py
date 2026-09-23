"""Prets : import d'un tableau d'amortissement, echeancier, projection."""
import io
import logging

from flask import Blueprint, jsonify, request

from auth import login_required, csrf_protect
from models import get_db, validate_date, validate_string
from services import prets as svc

logger = logging.getLogger('financy')
prets_bp = Blueprint('prets', __name__)
MAX_BYTES = 5 * 1024 * 1024


@prets_bp.route('/api/prets', methods=['GET'])
@login_required
def liste():
    date = request.args.get('date')
    if date and not validate_date(date):
        return jsonify({'error': 'Date invalide'}), 400
    with get_db() as conn:
        return jsonify(svc.resume(conn, date))


@prets_bp.route('/api/prets/projection', methods=['GET'])
@login_required
def projection():
    with get_db() as conn:
        return jsonify(svc.projection(conn))


@prets_bp.route('/api/prets/dettes', methods=['GET'])
@login_required
def dettes():
    """Dette de chaque entite selon ses echeanciers, a `date`."""
    date = request.args.get('date')
    if not validate_date(date):
        return jsonify({'error': 'Date requise (AAAA-MM-JJ)'}), 400
    with get_db() as conn:
        return jsonify(svc.dettes_par_entite(conn, date))


@prets_bp.route('/api/prets/import', methods=['POST'])
@login_required
@csrf_protect
def importer():
    """step=preview : lit et verifie. step=commit : enregistre."""
    from services.parsers.amortissement import lire_tableau
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'Aucun fichier reçu'}), 400
    raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        return jsonify({'error': 'Fichier trop volumineux (5 Mo max)'}), 413
    if not raw.startswith(b'%PDF-'):
        return jsonify({'error': "Ce fichier n'est pas un PDF"}), 400
    try:
        tableau = lire_tableau(io.BytesIO(raw))
    except ValueError as e:
        return jsonify({'error': str(e)}), 422
    except Exception:
        logger.exception('Lecture tableau d amortissement')
        return jsonify({'error': "PDF illisible : ce n'est peut-être pas un tableau d'amortissement"}), 422

    entity = request.form.get('entity') or None
    libelle = (request.form.get('libelle') or '').strip() or None
    if not validate_string(libelle, 120) or not validate_string(entity, 200):
        return jsonify({'error': 'Libellé ou entité trop long'}), 400
    with get_db() as conn:
        if entity and not conn.execute('SELECT 1 FROM entities WHERE name=?', (entity,)).fetchone():
            return jsonify({'error': f'Entité inconnue : {entity}'}), 400
        # Le meme echeancier deux fois doublerait la dette projetee.
        deja = conn.execute('SELECT id, libelle FROM prets WHERE montant=? AND debut=? AND fin=?',
                            (tableau.montant, tableau.echeances[0].date, tableau.echeances[-1].date)).fetchone()
        apercu = tableau.to_dict()
        apercu['echeances'] = len(tableau.echeances)
        apercu['deja'] = dict(deja) if deja else None
        # Rapprochement : l'emprunteur nomme dans le document, s'il est une entite.
        if tableau.emprunteur:
            r = conn.execute('SELECT name FROM entities WHERE UPPER(name)=UPPER(?)', (tableau.emprunteur,)).fetchone()
            apercu['entite_proposee'] = r['name'] if r else None
        if request.args.get('step') != 'commit':
            return jsonify({'step': 'preview', 'pret': apercu})
        if deja:
            return jsonify({'error': f'Ce prêt est déjà enregistré (« {deja["libelle"]} »)'}), 409
        pid = svc.enregistrer(conn, tableau, entity, libelle, f.filename[:200])
    return jsonify({'step': 'commit', 'id': pid}), 201


@prets_bp.route('/api/prets/<int:pid>', methods=['PATCH'])
@login_required
@csrf_protect
def modifier(pid):
    d = request.json or {}
    champs, valeurs = [], []
    with get_db() as conn:
        if 'entity' in d:
            e = d['entity'] or None
            if e and not conn.execute('SELECT 1 FROM entities WHERE name=?', (e,)).fetchone():
                return jsonify({'error': f'Entité inconnue : {e}'}), 400
            champs.append('entity=?'); valeurs.append(e)
        if 'libelle' in d:
            if not d['libelle'] or not validate_string(d['libelle'], 120):
                return jsonify({'error': 'Libellé invalide'}), 400
            champs.append('libelle=?'); valeurs.append(d['libelle'].strip())
        if not champs:
            return jsonify({'error': 'Rien à modifier'}), 400
        n = conn.execute(f'UPDATE prets SET {", ".join(champs)} WHERE id=?', (*valeurs, pid)).rowcount
    return (jsonify({'ok': True}), 200) if n else (jsonify({'error': 'Prêt introuvable'}), 404)


@prets_bp.route('/api/prets/<int:pid>', methods=['DELETE'])
@login_required
@csrf_protect
def supprimer(pid):
    with get_db() as conn:
        conn.execute('DELETE FROM pret_echeances WHERE pret_id=?', (pid,))
        n = conn.execute('DELETE FROM prets WHERE id=?', (pid,)).rowcount
    return ('', 204) if n else (jsonify({'error': 'Prêt introuvable'}), 404)
