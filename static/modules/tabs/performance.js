/**
 * Onglet Performance. L'ecran est en Svelte (frontend/src/performance/,
 * compile dans /dist/performance.js), qui charge lui-meme ses donnees : ce
 * module lui passe le titulaire, le mode discret, et un numero de visite —
 * chaque visite de l'onglet recharge les chiffres.
 */
import { S } from '../state.js';
import { isMasked } from '../mask.js';

let _visite = 0;

export async function loadPerformance() {
  _visite++;
  await renderPerformance();
}

export async function renderPerformance() {
  const cible = document.getElementById('perf-app');
  if (!cible) return;
  const { afficher } = await import('/dist/performance.js');
  afficher(cible, {
    owner: S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : null,
    masque: isMasked(), visite: _visite,
  });
}
