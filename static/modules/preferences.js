/**
 * Preferences de lecture, en base : colonnes, filtres, tris, angle de la
 * repartition, hypotheses de projection. Reglees une fois, retrouvees sur
 * tous les appareils — elles vivaient dans le navigateur, et le telephone ne
 * savait rien des choix faits sur l'ordinateur.
 *
 * Meme usage que localStorage (valeurs textuelles, lecture synchrone) : une
 * copie en memoire, chargee au demarrage (`chargerPreferences`, avant le
 * premier rendu), ecrite en base a chaque changement. localStorage en garde
 * un double, qui sert si le serveur ne repond pas.
 *
 * Restent propres a l'appareil, hors de ce module : le mode discretion, la
 * densite, les noeuds ouverts de l'arbre.
 */
import { api } from './api.js';

// Cles partagees entre appareils (les autres restent dans le navigateur).
const PARTAGEES = [
  /^financy_filters_/, /^financy_columns_/, /^financy_arbo_(groupe|tri)$/,
  /^financy_repartition$/, /^financy_projection_v2$/,
];
const partagee = cle => PARTAGEES.some(r => r.test(cle));

let _prefs = null;
let _enAttente = {};
let _minuteur = null;

function _local(cle) {
  try { return localStorage.getItem(cle); } catch { return null; }
}
function _localEcrire(cle, v) {
  try { if (v == null) localStorage.removeItem(cle); else localStorage.setItem(cle, v); } catch { /* session privee */ }
}
function _clesLocales() {
  try { return Object.keys(localStorage).filter(partagee); } catch { return []; }
}

// Marque, par navigateur, la reprise de ses anciens choix en base.
const REPRIS = 'financy_prefs_reprises';

/** A appeler une fois, avant le premier rendu. La premiere fois dans chaque
 *  navigateur, les choix qu'il avait faits montent en base, sauf ceux que la
 *  base connait deja (elle l'emporte) : aucun appareil ne perd les siens. */
export async function chargerPreferences() {
  try {
    _prefs = await api('GET', '/api/preferences', null, { silent: true }) || {};
    if (!_local(REPRIS)) {
      const reprises = Object.fromEntries(_clesLocales()
        .filter(c => !(c in _prefs)).map(c => [c, _local(c)]).filter(([, v]) => v != null));
      if (Object.keys(reprises).length) {
        _prefs = await api('PATCH', '/api/preferences', reprises, { silent: true }) || { ..._prefs, ...reprises };
      }
      _localEcrire(REPRIS, '1');
    }
    Object.entries(_prefs).forEach(([c, v]) => _localEcrire(c, v));
  } catch {
    // Serveur injoignable : la copie du navigateur.
    _prefs = Object.fromEntries(_clesLocales().map(c => [c, _local(c)]));
  }
}

export function lirePref(cle) {
  if (!partagee(cle) || _prefs === null) return _local(cle);
  return _prefs[cle] ?? null;
}

export function ecrirePref(cle, valeur) {
  const v = valeur == null ? null : String(valeur);
  _localEcrire(cle, v);
  if (!partagee(cle)) return;
  if (_prefs) { if (v == null) delete _prefs[cle]; else _prefs[cle] = v; }
  // Un glisser de colonne ou une saisie ecrivent en rafale : un envoi groupe.
  _enAttente[cle] = v;
  clearTimeout(_minuteur);
  _minuteur = setTimeout(_envoyer, 400);
}

export function effacerPref(cle) { ecrirePref(cle, null); }

async function _envoyer() {
  const lot = _enAttente;
  _enAttente = {};
  if (!Object.keys(lot).length) return;
  try { await api('PATCH', '/api/preferences', lot, { silent: true }); }
  // Echec : la copie locale reste, et le lot repart avec la prochaine
  // ecriture — sous les valeurs plus recentes, qui l'emportent.
  catch { _enAttente = { ...lot, ..._enAttente }; }
}
