"""Prets : import d'un tableau d'amortissement, echeancier, projection."""
import io
import logging

from flask import Blueprint, jsonify, request

from auth import login_required, csrf_protect
from models import get_db, validate_date, validate_string
from services import prets as svc
from services.montants import centimes, euros

logger = logging.getLogger('financy')
prets_bp = Blueprint('prets', __name__)
MAX_BYTES = 5 * 1024 * 1024


def _parts(conn):
    """Quotes-parts du titulaire demande (`?titulaire=`), None pour la famille :
    les credits se lisent alors entiers."""
    t = (request.args.get('titulaire') or '').strip()
    if not t or t == 'Famille' or not validate_string(t, 100):
        return None
    return svc.parts_titulaire(conn, t)


@prets_bp.route('/api/prets', methods=['GET'])
@login_required
def liste():
    date = request.args.get('date')
    if date and not validate_date(date):
        return jsonify({'error': 'Date invalide'}), 400
    with get_db() as conn:
        r = svc.resume(conn, date)
        parts = _parts(conn)
        if parts is not None:
            r['prets'] = [svc.a_la_part(p, parts[p['id']]) for p in r['prets'] if p['id'] in parts]
            r['titulaire'] = request.args.get('titulaire')
        r['autres_dettes'] = _autres_dettes(conn, request.args.get('titulaire'))
        return jsonify(r)


def _autres_dettes(conn, titulaire=None):
    """Les dettes du dernier arrete qu'aucun credit n'explique : un impot a
    payer sur une plus-value, un pret familial saisi a la main. Sans elles,
    l'ecart entre la dette de la synthese et le restant du des credits
    restait muet."""
    d = conn.execute('SELECT MAX(date) d FROM positions').fetchone()['d']
    if not d:
        return []
    avec_credit = {r['entity'] for r in conn.execute('SELECT DISTINCT entity FROM prets WHERE entity IS NOT NULL')}
    t = (titulaire or '').strip()
    q = ('SELECT owner, label, envelope, establishment, entity, notes, debt, COALESCE(debt_pct, 1) part '
         'FROM positions WHERE date=? AND debt > 0')
    out = []
    for r in conn.execute(q, (d,)):
        if r['entity'] and r['entity'] in avec_credit:
            continue
        if t and t != 'Famille' and r['owner'] != t:
            continue
        out.append({'libelle': ' · '.join(x for x in (r['label'] or r['envelope'], r['establishment'], r['owner']) if x),
                    'montant': round(euros(r['debt']) * (r['part'] if r['entity'] else 1), 2),
                    'notes': r['notes'], 'date': d})
    return out


@prets_bp.route('/api/prets/projection', methods=['GET'])
@login_required
def projection():
    with get_db() as conn:
        return jsonify(svc.projection(conn, parts=_parts(conn)))


@prets_bp.route('/api/prets/calendrier', methods=['GET'])
@login_required
def calendrier():
    with get_db() as conn:
        return jsonify(svc.calendrier(conn, parts=_parts(conn)))


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
                            (centimes(tableau.montant), tableau.echeances[0].date, tableau.echeances[-1].date)).fetchone()
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


@prets_bp.route('/api/prets', methods=['POST'])
@login_required
@csrf_protect
def definir():
    """Un credit sans tableau d'amortissement : l'echeancier se calcule a
    mensualite constante a partir du montant, du taux et de la duree."""
    from models import validate_number, parse_number
    from services.parsers.amortissement import _verifier
    d = request.json or {}
    libelle = (d.get('libelle') or '').strip()
    if not libelle or not validate_string(libelle, 120) or not validate_string(d.get('preteur'), 120):
        return jsonify({'error': 'Libellé requis (120 car. max)'}), 400
    for k, lib in (('montant', 'Montant'), ('taux', 'Taux'), ('mois', 'Durée')):
        if d.get(k) is None or not validate_number(d.get(k)):
            return jsonify({'error': f'{lib} invalide'}), 400
    montant, taux, mois = parse_number(d['montant']), parse_number(d['taux']), int(parse_number(d['mois']))
    assurance = parse_number(d.get('assurance'), 0) if d.get('assurance') not in (None, '') else 0.0
    if montant <= 0 or not (0 <= taux < 30) or not (1 <= mois <= 600) or assurance < 0:
        return jsonify({'error': 'Montant positif, taux entre 0 et 30 %, durée de 1 à 600 mois'}), 400
    if not validate_date(d.get('premiere')):
        return jsonify({'error': 'Date de première échéance invalide (AAAA-MM-JJ)'}), 400
    differe = int(parse_number(d.get('differe'), 0)) if d.get('differe') not in (None, '') else 0
    type_differe = d.get('type_differe') or 'partiel'
    if type_differe not in ('partiel', 'total') or not (0 <= differe < mois):
        return jsonify({'error': 'Différé : total ou partiel, plus court que la durée du prêt'}), 400
    entity = d.get('entity') or None
    with get_db() as conn:
        if entity and not conn.execute('SELECT 1 FROM entities WHERE name=?', (entity,)).fetchone():
            return jsonify({'error': f'Entité inconnue : {entity}'}), 400
        t = _verifier(svc.echeancier_calcule(montant, taux, mois, d['premiere'], assurance, differe, type_differe))
        t.preteur = (d.get('preteur') or '').strip() or None
        pid = svc.enregistrer(conn, t, entity, libelle, 'saisie')
    return jsonify({'id': pid}), 201


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
        if 'ira' in d:
            if d['ira'] not in ('legale', 'aucune'):
                return jsonify({'error': 'IRA : legale ou aucune'}), 400
            champs.append('ira=?'); valeurs.append(d['ira'])
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
