"""
Wrapper Anthropic SDK pour l'advisor (phase 7).

- Prompt caching obligatoire sur les blocs systeme et le contexte profil/positions.
- Logging des couts dans la table llm_usage.
- Mock automatique en mode demo (is_demo_mode), sans cle API,
  ou avec ADVISOR_LLM_PROVIDER=mock.
- Garde-fou budget mensuel via ADVISOR_BUDGET_USD.
"""
from __future__ import annotations
import json
import logging
import os
import time
from datetime import datetime, date
from typing import Optional, List, Dict

logger = logging.getLogger('financy.advisor.llm')

DEFAULT_MODEL = 'claude-sonnet-4-6'

# Tarifs (USD / 1M tokens) — claude-sonnet-4-6
PRICING = {
    'claude-sonnet-4-6': {
        'input':            3.00,
        'cached_input':     0.30,
        'cache_write_5m':   3.75,
        'output':          15.00,
    },
    'claude-haiku-4-5': {
        'input':            1.00,
        'cached_input':     0.10,
        'cache_write_5m':   1.25,
        'output':           5.00,
    },
    'claude-opus-4-7': {
        'input':            5.00,
        'cached_input':     0.50,
        'cache_write_5m':   6.25,
        'output':          25.00,
    },
}


def get_model():
    """Modele par defaut, configurable via env ADVISOR_MODEL."""
    return os.environ.get('ADVISOR_MODEL', DEFAULT_MODEL)


def _get_api_key():
    """Cle API Anthropic : DB settings d'abord, puis env var."""
    from services.settings import get_api_key
    return get_api_key()


def is_mock_mode():
    """Mock LLM en mode demo, sans cle API, ou si ADVISOR_LLM_PROVIDER=mock."""
    if os.environ.get('ADVISOR_LLM_PROVIDER', '').lower() == 'mock':
        return True
    if not _get_api_key():
        return True
    try:
        from models import is_demo_mode
        if is_demo_mode():
            return True
    except Exception:
        pass
    return False


def is_available():
    """L'advisor LLM est disponible si on a une cle API ou en mode mock (tests)."""
    return bool(_get_api_key()) or is_mock_mode()


# ─── Calcul de cout ──────────────────────────────────────────────────────────

def compute_cost(model, input_tokens=0, cached_input_tokens=0,
                 cache_write_tokens=0, output_tokens=0):
    """Calcule le cout USD d'un appel a partir des tokens reportes par l'API."""
    rates = PRICING.get(model, PRICING[DEFAULT_MODEL])
    return round(
        (input_tokens        * rates['input']           / 1_000_000) +
        (cached_input_tokens * rates['cached_input']    / 1_000_000) +
        (cache_write_tokens  * rates['cache_write_5m']  / 1_000_000) +
        (output_tokens       * rates['output']          / 1_000_000),
        6
    )


# ─── Logging usage en DB ─────────────────────────────────────────────────────

def log_usage(conn, endpoint, model, usage_dict, latency_ms, cost):
    try:
        conn.execute(
            '''INSERT INTO llm_usage
               (date, endpoint, model, input_tokens, cached_input_tokens,
                output_tokens, cost_usd, latency_ms)
               VALUES (?,?,?,?,?,?,?,?)''',
            (datetime.now().strftime('%Y-%m-%d'), endpoint, model,
             usage_dict.get('input_tokens', 0),
             usage_dict.get('cached_input_tokens', 0),
             usage_dict.get('output_tokens', 0),
             cost, int(latency_ms))
        )
    except Exception:
        logger.exception('llm_usage insert failed')


def monthly_cost(conn):
    """Total des couts USD pour le mois en cours."""
    month_prefix = datetime.now().strftime('%Y-%m')
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM llm_usage WHERE date LIKE ?",
            (month_prefix + '%',)
        ).fetchone()
        return float(row['total']) if row else 0.0
    except Exception:
        return 0.0


def usage_summary(conn, days=30):
    """Resume des appels recents pour l'UI."""
    try:
        rows = conn.execute(
            '''SELECT date, COUNT(*) as calls,
                      SUM(input_tokens) as input_tokens,
                      SUM(cached_input_tokens) as cached_input_tokens,
                      SUM(output_tokens) as output_tokens,
                      SUM(cost_usd) as cost_usd
               FROM llm_usage
               WHERE date >= date('now', ?)
               GROUP BY date ORDER BY date''',
            (f'-{int(days)} days',)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def budget_remaining_usd():
    """Dollars restants ce mois selon ADVISOR_BUDGET_USD (None = pas de limite)."""
    raw = os.environ.get('ADVISOR_BUDGET_USD')
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


# ─── Appel LLM avec cache ────────────────────────────────────────────────────

def messages_create(conn, endpoint, system_blocks, user_message,
                    max_tokens=2048, model=None, json_response=False,
                    cache_breakpoint_at_end_of_system=True):
    """Appel Claude API avec prompt caching et logging.

    - system_blocks : liste de blocs system. Le dernier bloc reçoit cache_control.
    - user_message  : string ou liste de content blocks.
    - json_response : si True, le bloc texte renvoye est parse en JSON.

    Retourne un dict :
      {text, json (optionnel), usage, cost_usd, model, latency_ms, cached: bool}
    """
    model = model or get_model()

    # Garde-fou budget
    budget = budget_remaining_usd()
    if budget is not None:
        spent = monthly_cost(conn)
        if spent >= budget:
            raise RuntimeError(
                f'Budget LLM mensuel atteint ({spent:.2f} $ / {budget:.2f} $). '
                f'Augmentez ADVISOR_BUDGET_USD ou attendez le mois prochain.'
            )

    if is_mock_mode():
        return _mock_call(endpoint, system_blocks, user_message,
                          json_response=json_response, model=model)

    return _live_call(conn, endpoint, system_blocks, user_message,
                      max_tokens, model, json_response,
                      cache_breakpoint_at_end_of_system)


def _mock_call(endpoint, system_blocks, user_message, json_response, model):
    """Renvoie une reponse stub deterministe pour tests + mode demo."""
    if json_response:
        if 'macro' in endpoint:
            text = json.dumps({
                'regime_rates':   'neutre',
                'inflation_view': 'maitrisee',
                'equities_bias':  'neutre',
                'summary':        '[MOCK] Snapshot macro fictif. En mode reel, ce contenu serait genere par Claude.',
            })
        else:
            text = json.dumps({'rationale': '[MOCK] Justification fictive.'})
    else:
        text = '[MOCK] Reponse Claude non disponible (mock).'
    return {
        'text':       text,
        'json':       json.loads(text) if json_response else None,
        'usage':      {'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0},
        'cost_usd':   0.0,
        'model':      model + ' (mock)',
        'latency_ms': 0,
        'cached':     False,
    }


def _live_call(conn, endpoint, system_blocks, user_message,
               max_tokens, model, json_response, cache_breakpoint):
    try:
        import anthropic
    except ImportError:
        raise RuntimeError('SDK anthropic non installe (pip install anthropic).')

    client = anthropic.Anthropic(api_key=_get_api_key())

    # Place le cache_control sur le dernier bloc systeme pour caching.
    sys_blocks = [dict(b) for b in system_blocks]  # deep copy minimal
    if cache_breakpoint and sys_blocks:
        sys_blocks[-1] = {
            **sys_blocks[-1],
            'cache_control': {'type': 'ephemeral'},
        }

    messages = (
        [{'role': 'user', 'content': user_message}]
        if isinstance(user_message, str)
        else [{'role': 'user', 'content': user_message}]
    )

    kwargs = {
        'model':      model,
        'max_tokens': max_tokens,
        'system':     sys_blocks,
        'messages':   messages,
    }
    # JSON mode : pas d'output_config, on ajoute l'instruction dans le prompt
    # et on parse la reponse. L'API Anthropic ne supporte pas json_object nativement.

    start = time.monotonic()
    try:
        response = client.messages.create(**kwargs)
    except Exception as e:
        logger.warning('Claude API call failed (%s): %s', endpoint, e)
        raise

    latency_ms = int((time.monotonic() - start) * 1000)

    text_blocks = [b for b in response.content if getattr(b, 'type', None) == 'text']
    text = '\n'.join(b.text for b in text_blocks).strip()

    usage_obj = response.usage
    usage_dict = {
        'input_tokens':           getattr(usage_obj, 'input_tokens', 0) or 0,
        'cached_input_tokens':    getattr(usage_obj, 'cache_read_input_tokens', 0) or 0,
        'output_tokens':          getattr(usage_obj, 'output_tokens', 0) or 0,
        'cache_creation_tokens':  getattr(usage_obj, 'cache_creation_input_tokens', 0) or 0,
    }

    cost = compute_cost(
        model,
        input_tokens=usage_dict['input_tokens'],
        cached_input_tokens=usage_dict['cached_input_tokens'],
        cache_write_tokens=usage_dict['cache_creation_tokens'],
        output_tokens=usage_dict['output_tokens'],
    )
    log_usage(conn, endpoint, model, usage_dict, latency_ms, cost)

    parsed = None
    if json_response and text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning('Claude JSON response unparseable: %s', text[:200])

    return {
        'text':       text,
        'json':       parsed,
        'usage':      usage_dict,
        'cost_usd':   cost,
        'model':      model,
        'latency_ms': latency_ms,
        'cached':     usage_dict['cached_input_tokens'] > 0,
    }
