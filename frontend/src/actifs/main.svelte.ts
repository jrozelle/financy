// Point d'entree de l'onglet Actifs, charge a la demande par
// static/modules/tabs/actifs.js : monte le composant une fois, puis lui
// passe les lignes consolidees a chaque chargement.
import { mount } from 'svelte';
import Actifs from './Actifs.svelte';
import type { Consolide } from './types';

let props = $state<{ donnees: Consolide | null; masque: boolean }>({ donnees: null, masque: false });
let monte = false;

export function afficher(cible: HTMLElement, valeurs: { donnees: Consolide | null; masque: boolean }): void {
  Object.assign(props, valeurs);
  if (!monte) {
    cible.replaceChildren();
    mount(Actifs, { target: cible, props });
    monte = true;
  }
}
