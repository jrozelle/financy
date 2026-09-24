/**
 * Referentiel (fenetre des Reglages). L'ecran est en Svelte
 * (frontend/src/referentiel/, compile dans /dist/referentiel.js), qui charge,
 * edite et enregistre lui-meme le referentiel ; ce module lui passe le mode
 * discret et un numero de visite — chaque ouverture relit la base.
 */
import { isMasked } from '../mask.js';

let _visite = 0;

export async function loadReferential() {
  _visite++;
  await renderReferential();
}

/** Redessine sans recharger (mode discret : seuils des alertes). */
export async function renderReferential() {
  const cible = document.getElementById('referentiel-app');
  if (!cible) return;
  const { afficher } = await import('/dist/referentiel.js');
  afficher(cible, { masque: isMasked(), visite: _visite });
}
