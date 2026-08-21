"""Import de mouvements : avis d'operes et releves d'especes.

Deux temps, comme l'import de holdings : `preview` rend ce qui a ete lu sans
rien ecrire, `commit` insere ce que l'utilisateur a valide. Un document deja
importe est detecte et ignore — `transactions.source_doc` porte un index unique,
et les flux sont dedoublonnes sur (date, enveloppe, type, montant).
"""
import hashlib

from flask import Blueprint, jsonify, request

from models import get_db, validate_date
from auth import login_required, csrf_protect
from services.parsers.movements import parse_movements

movements_bp = Blueprint('movements', __name__)

MAX_FILES = 200
MAX_BYTES = 5 * 1024 * 1024


# Les parsers de mouvements lisent des colonnes : la mise en page doit etre
# preservee. Les tolerances serrees sont indispensables sur les releves 2026,
# dont le gabarit fait perdre a pdfplumber l'en-tete et les lignes d'operation
# aux valeurs par defaut.
_EXTRACT = {'layout': True, 'x_tolerance': 1, 'y_tolerance': 2}


def _text(file_bytes):
    """(texte mis en page, mots par page) du PDF.

    Les mots portent leurs coordonnees : sur les releves d'especes, elles sont
    le seul indice fiable de la colonne debit ou credit, la mise en page texte
    ne conservant pas l'alignement a droite des montants.
    """
    from io import BytesIO
    import pdfplumber
    out, words = [], []
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            try:
                out.append(page.extract_text(**_EXTRACT) or '')
            except Exception:
                try:
                    out.append(page.extract_text() or '')
                except Exception:
                    pass
            try:
                words.append(page.extract_words(x_tolerance=1, y_tolerance=2))
            except Exception:
                words.append([])
    return '\n'.join(out), words


def _known_docs(conn):
    """Empreintes des documents deja importes."""
    return {r['source_doc'] for r in conn.execute(
        'SELECT source_doc FROM transactions WHERE source_doc IS NOT NULL')}


def _known_operations(conn):
    """Cle metier des transactions existantes.

    L'empreinte du fichier ne suffit pas : le meme avis retelecharge depuis la
    banque n'a pas les memes octets (horodatage de generation), et passerait pour
    un nouveau document. On identifie donc aussi l'operation par son contenu.
    Deux ordres reellement identiques le meme jour seraient confondus — cas
    theorique, prefere a une double comptabilisation silencieuse ; l'apercu le
    signale pour que l'utilisateur tranche.
    """
    return {(r['date'], r['isin'], r['side'], round(r['quantity'] or 0, 6),
             round(r['net_eur'] or 0, 2))
            for r in conn.execute('SELECT date, isin, side, quantity, net_eur '
                                  'FROM transactions')}


def _flux_signature(conn):
    """Signature des flux existants, pour ne pas reinserer deux fois le meme."""
    return {(r['date'], r['envelope'] or '', r['type'] or '', round(r['amount'] or 0, 2))
            for r in conn.execute('SELECT date, envelope, type, amount FROM flux')}


# Un compte-titres ordinaire se nomme "CTO" chez l'un, "Compte-titres" chez
# l'autre. Le parseur lit le document, pas le referentiel de l'utilisateur : si
# le nom qu'il produit ne figure pas dans `positions`, les flux importes ne se
# rattachent a aucun compte et l'enveloppe affiche un rendement qui absorbe les
# versements — un CTO ressortait a +114 % au lieu de +5 %.
_ENVELOPE_SYNONYMS = {
    'Compte-titres': ('CTO', 'Compte-titres', 'Compte titres', 'CTO ordinaire'),
    'PEA': ('PEA', 'P.E.A.'),
}


def _map_envelopes(items, known):
    """Aligne l'enveloppe lue sur celle employee dans les positions."""
    known = set(known or ())
    unresolved = set()
    for it in items:
        env = it.get('envelope')
        if not env or env in known:
            continue
        match = next((c for c in _ENVELOPE_SYNONYMS.get(env, ()) if c in known), None)
        if match:
            it['envelope'] = match
        else:
            unresolved.add(env)
    return sorted(unresolved)


def _read(files, owner, establishment=None):
    """Parse les fichiers recus et renvoie (mouvements, rejets)."""
    items, rejets = [], []
    for f in files:
        raw = f.read()
        if len(raw) > MAX_BYTES:
            rejets.append({'file': f.filename, 'reason': 'fichier trop volumineux (5 Mo max)'})
            continue
        try:
            text, words = _text(raw)
        except Exception as e:
            rejets.append({'file': f.filename, 'reason': f'PDF illisible : {e}'})
            continue
        mvs = parse_movements(text, words=words)
        if not mvs:
            rejets.append({'file': f.filename,
                           'reason': 'ni avis d\'opéré ni relevé d\'espèces exploitable'})
            continue
        # Sans enveloppe, un mouvement ne se rattache a aucun compte : mieux
        # vaut refuser le document que le ranger au hasard.
        if any(m.envelope is None for m in mvs):
            rejets.append({'file': f.filename,
                           'reason': 'compte non identifié dans le document '
                                     '(relevé de compte courant ?)'})
            continue
        digest = hashlib.sha256(raw).hexdigest()[:16]
        for m in mvs:
            d = m.to_dict()
            d['file'] = f.filename
            d['digest'] = digest
            d['owner'] = owner
            if establishment:
                d['establishment'] = establishment
            items.append(d)
    return items, rejets


@movements_bp.route('/api/import/movements', methods=['POST'])
@login_required
@csrf_protect
def import_movements():
    """step=preview (defaut) : lit et rend. step=commit : ecrit."""
    step = request.args.get('step', 'preview')
    owner = request.form.get('owner') or request.args.get('owner')
    if not owner:
        return jsonify({'error': 'Personne requise'}), 400
    # Les etablissements deja employes dans les positions : les proposer evite
    # les variantes d'orthographe, qui creeraient des comptes fantomes.
    with get_db() as conn:
        known_etabs = sorted({r['establishment'] for r in conn.execute(
            'SELECT DISTINCT establishment FROM positions '
            'WHERE establishment IS NOT NULL AND establishment <> ?', ('',))})
        known_envs = sorted({r['envelope'] for r in conn.execute(
            'SELECT DISTINCT envelope FROM positions WHERE envelope IS NOT NULL')})
    files = request.files.getlist('files') or request.files.getlist('file')
    if not files:
        return jsonify({'error': 'Aucun fichier reçu'}), 400
    if len(files) > MAX_FILES:
        return jsonify({'error': f'{MAX_FILES} fichiers au maximum par lot'}), 400

    items, rejets = _read(files, owner, request.form.get('establishment')
                          or request.args.get('establishment'))
    unresolved_envs = _map_envelopes(items, known_envs)
    with get_db() as conn:
        known = _known_docs(conn)
        known_ops = _known_operations(conn)
        signatures = _flux_signature(conn)
        secs = {r['isin'] for r in conn.execute('SELECT isin FROM securities')}

    tx = [i for i in items if i['kind'] == 'transaction']
    fx = [i for i in items if i['kind'] == 'flux']
    seen_ops = set()
    for i in tx:
        i['source_doc'] = f"import:{i['digest']}"
        op = (i['date'], i['isin'], i['side'],
              round(i['quantity'] or 0, 6), round(i['net_eur'] or 0, 2))
        same_file = i['source_doc'] in known
        same_op = op in known_ops or op in seen_ops
        i['duplicate'] = same_file or same_op
        i['duplicate_reason'] = ('document déjà importé' if same_file
                                 else 'opération déjà enregistrée' if same_op else None)
        i['unknown_isin'] = bool(i['isin']) and i['isin'] not in secs
        if not i['duplicate']:
            seen_ops.add(op)
    seen_fx = set()
    for i in fx:
        sig = (i['date'], i['envelope'] or '', i['flux_type'] or '',
               round(i['net_eur'] or 0, 2))
        i['duplicate'] = sig in signatures or sig in seen_fx
        i['duplicate_reason'] = 'flux déjà enregistré' if i['duplicate'] else None
        if not i['duplicate']:
            seen_fx.add(sig)

    summary = {
        'files': len(files),
        'transactions': sum(1 for i in tx if not i['duplicate']),
        'flux': sum(1 for i in fx if not i['duplicate']),
        'duplicates': sum(1 for i in items if i.get('duplicate')),
        'warnings': sum(1 for i in items if i.get('warnings')),
        'unknown_isins': sorted({i['isin'] for i in tx if i.get('unknown_isin')}),
        'rejected': rejets,
        'known_establishments': known_etabs,
        'unresolved_envelopes': unresolved_envs,
    }
    if step != 'commit':
        return jsonify({'step': 'preview', 'summary': summary,
                        'transactions': tx, 'flux': fx})

    inserted = {'transactions': 0, 'flux': 0, 'securities': 0}
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('BEGIN IMMEDIATE')
        for isin in summary['unknown_isins']:
            name = next((i['name'] for i in tx if i['isin'] == isin and i['name']), isin)
            cur.execute('INSERT OR IGNORE INTO securities (isin, name, data_source) '
                        "VALUES (?,?,'import_avis')", (isin, name))
            inserted['securities'] += 1
        for i in tx:
            if i['duplicate'] or not i['isin']:
                continue
            cur.execute('''INSERT OR IGNORE INTO transactions
                (date, owner, envelope, establishment, isin, side, quantity, price,
                 currency, fx_rate, gross, fees, net_eur, place, source_doc, notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (i['date'], owner, i['envelope'], i['establishment'], i['isin'],
                 i['side'], i['quantity'], i['price'], i['currency'], i['fx_rate'],
                 i['gross'], i['fees'], i['net_eur'], i['place'], i['source_doc'],
                 f"[import] {i['file']}"))
            inserted['transactions'] += cur.rowcount
        for i in fx:
            if i['duplicate']:
                continue
            cur.execute('''INSERT INTO flux
                (date, owner, envelope, establishment, type, amount, notes)
                VALUES (?,?,?,?,?,?,?)''',
                (i['date'], owner, i['envelope'], i['establishment'],
                 i['flux_type'], i['net_eur'], f"[import] {i['label'] or ''}".strip()))
            inserted['flux'] += 1
        conn.commit()
    return jsonify({'step': 'commit', 'summary': summary, 'inserted': inserted})
