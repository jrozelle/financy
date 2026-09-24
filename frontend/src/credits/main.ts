// Point d'entree de l'onglet Credits, charge a la demande par
// static/modules/tabs/prets.js : monte le composant une fois, puis le
// recharge a chaque visite de l'onglet ou changement de titulaire.
import { mount } from 'svelte';
import Credits from './Credits.svelte';

interface Instance { recharger(): Promise<void>; ouvrirFormulaire(): Promise<void> }

let instance: Instance | null = null;

export function monter(cible: HTMLElement): Instance {
  if (!instance) {
    cible.replaceChildren();
    instance = mount(Credits, { target: cible }) as unknown as Instance;
  }
  return instance;
}
