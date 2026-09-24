// Point d'entree de l'onglet Performance, charge a la demande par
// static/modules/tabs/performance.js : monte le composant une fois, puis lui
// passe titulaire, mode discret et numero de visite (une visite recharge).
import { mount } from 'svelte';
import Performance from './Performance.svelte';

interface Props { owner: string | null; masque: boolean; visite: number }
let props = $state<Props>({ owner: null, masque: false, visite: 0 });
let monte = false;

export function afficher(cible: HTMLElement, valeurs: Props): void {
  Object.assign(props, valeurs);
  if (!monte) {
    cible.replaceChildren();
    mount(Performance, { target: cible, props });
    monte = true;
  }
}
