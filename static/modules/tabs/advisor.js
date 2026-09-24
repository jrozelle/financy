/**
 * Onglet Conseil patrimonial. L'ecran est en Svelte (frontend/src/conseil/,
 * compile dans /dist/conseil.js), qui charge lui-meme ses donnees : ce module
 * lui passe les titulaires du referentiel, le contexte de la barre du haut et
 * un numero de visite — chaque visite de l'onglet recharge.
 */
import { S } from '../state.js';
import { isMasked } from '../mask.js';

let _visite = 0;

export async function loadAdvisor() {
  _visite++;
  await renderAdvisor();
}

/** Redessine sans recharger (mode discret). */
export async function renderAdvisor() {
  const cible = document.getElementById('conseil-app');
  if (!cible) return;
  const { afficher } = await import('/dist/conseil.js');
  afficher(cible, {
    titulaires: (S.config && S.config.owners) || [],
    owner: S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : null,
    date: S.syntheseDate || null, masque: isMasked(), visite: _visite,
  });
}
