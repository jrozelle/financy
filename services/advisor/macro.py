"""
Snapshot macroeconomique : LLM ou saisie manuelle (phase 7).

Le LLM produit un JSON structure (regime_rates, inflation_view, equities_bias,
summary). L'utilisateur peut ensuite editer le snapshot, qui passe alors en
source='manual'.

Note : sans tool web_search, le LLM s'appuie uniquement sur ses connaissances de
training. Le snapshot est donc une vue "de fond" plutot qu'une analyse temps
reel — d'ou le bouton « Editer » dans l'UI pour ajuster.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime
from .llm import messages_create, get_model, is_available

logger = logging.getLogger('financy.advisor.macro')


VALID_REGIME_RATES   = {'bas', 'neutre', 'haut'}
VALID_INFLATION      = {'maitrisee', 'persistante'}
VALID_EQUITIES_BIAS  = {'defensif', 'neutre', 'offensif'}


SYSTEM_PROMPT = (
    "Tu es un analyste macroeconomique francophone. "
    "Reponds STRICTEMENT en JSON valide selon le schema demande. "
    "Reste sobre, factuel, sans recommandations nominatives. "
    "Le JSON doit comporter exactement les champs : "
    "regime_rates (bas|neutre|haut), inflation_view (maitrisee|persistante), "
    "equities_bias (defensif|neutre|offensif), summary (texte 2-4 phrases en francais)."
)


USER_PROMPT = (
    "Donne ta vue actuelle du contexte macroeconomique pour un epargnant europeen. "
    "Reste prudent : tes connaissances peuvent dater, l'utilisateur ajustera si besoin. "
    "Reponds en JSON uniquement, sans markdown ni commentaire."
)


def generate_snapshot(conn):
    """Appelle le LLM (ou mock) et renvoie un dict pret a inserer en DB."""
    if not is_available():
        raise RuntimeError("Service LLM indisponible (ANTHROPIC_API_KEY absente).")

    res = messages_create(
        conn,
        endpoint='advisor.macro.generate',
        system_blocks=[{'type': 'text', 'text': SYSTEM_PROMPT}],
        user_message=USER_PROMPT,
        max_tokens=512,
        json_response=True,
    )

    data = res.get('json') or {}
    snapshot = {
        'date':           datetime.now().strftime('%Y-%m-%d'),
        'regime_rates':   _coerce(data.get('regime_rates'), VALID_REGIME_RATES, 'neutre'),
        'inflation_view': _coerce(data.get('inflation_view'), VALID_INFLATION, 'maitrisee'),
        'equities_bias':  _coerce(data.get('equities_bias'), VALID_EQUITIES_BIAS, 'neutre'),
        'raw_summary':    (data.get('summary') or '')[:4000],
        'source':         'llm',
    }
    return snapshot, res


def _coerce(value, allowed, default):
    if isinstance(value, str) and value.lower() in allowed:
        return value.lower()
    return default


def save_snapshot(conn, snapshot):
    cur = conn.execute(
        '''INSERT INTO macro_snapshots
           (date, regime_rates, inflation_view, equities_bias, raw_summary, source)
           VALUES (?,?,?,?,?,?)''',
        (snapshot['date'], snapshot['regime_rates'], snapshot['inflation_view'],
         snapshot['equities_bias'], snapshot['raw_summary'], snapshot['source'])
    )
    return cur.lastrowid


def latest_snapshot(conn):
    row = conn.execute(
        'SELECT * FROM macro_snapshots ORDER BY id DESC LIMIT 1'
    ).fetchone()
    return dict(row) if row else None


def update_snapshot(conn, snap_id, updates):
    """Met a jour un snapshot existant (saisie utilisateur)."""
    fields, params = [], []
    for k in ('regime_rates', 'inflation_view', 'equities_bias', 'raw_summary', 'date'):
        if k in updates:
            fields.append(f'{k}=?')
            params.append(updates[k])
    if not fields:
        return None
    # Toute edition manuelle bascule la source
    fields.append("source='manual'")
    params.append(snap_id)
    conn.execute(
        f"UPDATE macro_snapshots SET {', '.join(fields)} WHERE id=?", params
    )
    row = conn.execute('SELECT * FROM macro_snapshots WHERE id=?', (snap_id,)).fetchone()
    return dict(row) if row else None
