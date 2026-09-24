import hmac
import ipaddress
import logging
import os
from functools import wraps
from flask import session, request, jsonify, redirect, url_for

AUTH_PASSWORD = os.environ.get('FINANCY_PASSWORD')  # None = pas d'auth
CSRF_PROTECTED_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if AUTH_PASSWORD and not session.get('authenticated'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Non authentifié'}), 401
            return redirect(url_for('auth.login_page'))
        return f(*args, **kwargs)
    return decorated


def csrf_protect(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method in CSRF_PROTECTED_METHODS:
            token = request.headers.get('X-CSRF-Token', '')
            attendu = session.get('csrf_token')
            # Comparaison a temps constant : `!=` s'arrete au premier
            # caractere different et laisse deviner le jeton par la duree.
            if (not token or not isinstance(attendu, str)
                    or not hmac.compare_digest(token.encode(), attendu.encode())):
                return jsonify({'error': 'CSRF token invalide'}), 403
        return f(*args, **kwargs)
    return decorated


# ─── Adresse du client derriere un reverse proxy ─────────────────────────────
# Derriere un proxy, `request.remote_addr` est celle du proxy : toutes les
# tentatives de connexion tombaient dans un seul compteur, et dix erreurs de
# n'importe qui bloquaient tout le monde. L'adresse transmise par le proxy
# (X-Forwarded-For) n'est lue que si la requete vient d'un proxy declare dans
# FINANCY_PROXIES_DE_CONFIANCE (adresses ou reseaux, separes par des
# virgules) ; sans cette variable, rien ne change.
_log = logging.getLogger('financy')


def _reseaux(valeur):
    reseaux = []
    for morceau in (valeur or '').split(','):
        morceau = morceau.strip()
        if not morceau:
            continue
        try:
            reseaux.append(ipaddress.ip_network(morceau, strict=False))
        except ValueError:
            _log.warning('FINANCY_PROXIES_DE_CONFIANCE : « %s » ignore, ni adresse ni reseau', morceau)
    return reseaux


PROXIES_DE_CONFIANCE = _reseaux(os.environ.get('FINANCY_PROXIES_DE_CONFIANCE'))
_signale = False


def _de_confiance(adresse, reseaux):
    try:
        ip = ipaddress.ip_address(adresse)
    except ValueError:
        return False
    return any(ip in r for r in reseaux)


def adresse_client(req=None, reseaux=None):
    """L'adresse du client, lue a travers les seuls proxies de confiance.

    X-Forwarded-For se lit de droite a gauche : chaque proxy AJOUTE a droite
    l'adresse qu'il a vue, et tout ce qui est a gauche peut avoir ete ecrit par
    le client. On saute nos proxies ; la premiere adresse qui n'en est pas un
    est celle que le dernier d'entre eux a recue. Une valeur illisible arrete
    la lecture : on garde alors la derniere adresse sure."""
    global _signale
    req = req or request
    reseaux = PROXIES_DE_CONFIANCE if reseaux is None else reseaux
    distante = req.remote_addr or ''
    transmis = req.headers.get('X-Forwarded-For', '')
    if not reseaux or not _de_confiance(distante, reseaux):
        if transmis and not _signale:
            # Un en-tete transmis par une adresse non declaree : proxy absent de
            # FINANCY_PROXIES_DE_CONFIANCE, ou client qui tente sa chance. Dit
            # une fois, pour qu'une configuration incomplete ne passe pas inapercue.
            _log.warning('X-Forwarded-For recu de %s, absente de FINANCY_PROXIES_DE_CONFIANCE : '
                         'adresse du proxy retenue', distante)
            _signale = True
        return distante
    retenue = distante
    for morceau in reversed([m.strip() for m in transmis.split(',') if m.strip()]):
        try:
            ipaddress.ip_address(morceau)
        except ValueError:
            break
        retenue = morceau
        if not _de_confiance(morceau, reseaux):
            break
    return retenue
