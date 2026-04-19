"""Helpers partages sur la table securities (dedupliques entre routes)."""
import re
from models import validate_isin


def _infer_asset_class(name):
    """Infere la classe d'actif depuis le nom du titre."""
    if not name:
        return 'autre'
    upper = name.upper()
    if re.search(r'\bETF\b|\bUCITS\b|\bTRACKER\b', upper):
        return 'etf'
    if re.search(r'\bOPCVM\b|\bSICAV\b|\bFCP\b', upper):
        return 'opcvm'
    if re.search(r'\bSCPI\b', upper):
        return 'scpi'
    if re.search(r'\bSCI\b', upper):
        return 'sci'
    if re.search(r'\bFONDS?\s*(EURO|EUR\b|EN\s*EURO)', upper):
        return 'fonds_euros'
    # Actions individuelles : pas de keyword ETF/OPCVM, ISIN FR/US/DE + nom court
    return 'action'


def upsert_security(conn, isin, name=None, ticker=None, currency=None,
                    asset_class=None, is_priceable=None, data_source='manual'):
    """Cree la security si absente, met a jour les champs non-None.

    Utilise par :
    - routes/holdings.py     (CRUD manuel)
    - routes/import_export.py (XLSX + JSON import)
    - routes/pdf_import.py   (commit PDF)

    Regles :
    - Les pseudo-ISIN (FONDS_EUROS_*, CUSTOM_*) ont is_priceable=0 par defaut.
    - Si `is_priceable` est fourni, il prevaut, sauf pour pseudo-ISIN ou il est force a 0.
    - Ne touche jamais `last_price` / `last_price_date` (reserve au refresh provider).
    """
    isin = (isin or '').strip().upper()
    if not validate_isin(isin):
        raise ValueError(f'ISIN invalide : {isin!r}')

    is_pseudo = isin.startswith(('FONDS_EUROS_', 'CUSTOM_'))
    if is_pseudo:
        effective_priceable = 0
    elif is_priceable is None:
        effective_priceable = None  # ne pas forcer de valeur si pas fournie
    else:
        effective_priceable = 0 if not is_priceable else 1

    row = conn.execute('SELECT isin FROM securities WHERE isin=?', (isin,)).fetchone()
    if row is None:
        conn.execute(
            '''INSERT INTO securities
               (isin, name, ticker, currency, asset_class, is_priceable, data_source)
               VALUES (?,?,?,?,?,?,?)''',
            (isin,
             name,
             ticker,
             currency or 'EUR',
             asset_class or ('fonds_euros' if isin.startswith('FONDS_EUROS_') else _infer_asset_class(name)),
             1 if effective_priceable is None else effective_priceable,
             data_source)
        )
        return

    # Si asset_class est 'autre' en base et qu'on a un nom, tenter d'inferer mieux
    if asset_class is None and name:
        existing = conn.execute('SELECT asset_class FROM securities WHERE isin=?', (isin,)).fetchone()
        if existing and (existing['asset_class'] or 'autre') == 'autre':
            inferred = _infer_asset_class(name)
            if inferred != 'action':  # ne pas ecraser 'autre' par 'action' (trop generique)
                asset_class = inferred

    updates, params = [], []
    for col, val in [('name', name), ('ticker', ticker), ('currency', currency),
                     ('asset_class', asset_class)]:
        if val is not None:
            updates.append(f'{col}=?')
            params.append(val)
    if effective_priceable is not None:
        updates.append('is_priceable=?')
        params.append(effective_priceable)
    if updates:
        updates.append('updated_at=CURRENT_TIMESTAMP')
        params.append(isin)
        conn.execute(
            f'UPDATE securities SET {", ".join(updates)} WHERE isin=?', params
        )
