/**
 * Persistance des filtres et du tri entre visites.
 *
 * Chaque onglet (positions, flux, actifs) a sa propre cle :
 *   financy_filters_<tab> = JSON {owner, envelope, sortKey, sortDir, ...}
 *
 * Au reload, les valeurs sont restaurees si elles sont toujours coherentes
 * avec les options disponibles (owner qui existe encore, etc.).
 */

import { lirePref, ecrirePref, effacerPref } from './preferences.js';

const PREFIX = 'financy_filters_';

export function saveFilters(tab, obj) {
  ecrirePref(PREFIX + tab, JSON.stringify(obj || {}));
}

export function loadFilters(tab) {
  try {
    const raw = lirePref(PREFIX + tab);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function clearFilterKey(tab) {
  effacerPref(PREFIX + tab);
}

/**
 * Applique un filtre sur un <select> si la valeur est toujours dans les options.
 * Renvoie true si applique, false sinon.
 */
export function applyIfValid(selectId, value) {
  const sel = document.getElementById(selectId);
  if (!sel || !value) return false;
  const opts = [...sel.options].map(o => o.value);
  if (!opts.includes(value)) return false;
  sel.value = value;
  return true;
}
