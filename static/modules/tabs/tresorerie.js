/**
 * Tresorerie des entites, lue sur leurs releves bancaires. La carte est un
 * ecran Svelte (frontend/src/entites/Tresorerie.svelte, compile dans
 * /dist/tresorerie.js) ; ce module charge les donnees et les lui passe.
 */
import { S } from '../state.js';
import { api } from '../api.js';
import { isMasked } from '../mask.js';

export async function loadTresorerie() {
  const cible = document.getElementById('tresorerie-app');
  if (!cible) return;
  let donnees;
  try {
    donnees = await api('GET', '/api/entites/tresorerie', null, { silent: true });
  } catch { return; }
  const { afficher } = await import('/dist/tresorerie.js');
  afficher(cible, {
    donnees, entites: (S.entities || []).map(e => e.name), masque: isMasked(), onRecharger: loadTresorerie,
  });
}
