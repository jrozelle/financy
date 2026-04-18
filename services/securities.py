"""Helpers partages sur la table securities (dedupliques entre routes)."""
from models import validate_isin


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
             asset_class or ('fonds_euros' if isin.startswith('FONDS_EUROS_') else 'autre'),
             1 if effective_priceable is None else effective_priceable,
             data_source)
        )
        return

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
