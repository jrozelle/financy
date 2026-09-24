// Point d'entree de l'onglet Conseil, charge a la demande par
// static/modules/tabs/advisor.js : monte le composant une fois, puis lui
// passe titulaires, contexte et numero de visite (une visite recharge).
import { mount } from 'svelte';
import Conseil from './Conseil.svelte';

interface Props { titulaires: string[]; owner: string | null; date: string | null; masque: boolean; visite: number }
let props = $state<Props>({ titulaires: [], owner: null, date: null, masque: false, visite: 0 });
let monte = false;

export function afficher(cible: HTMLElement, valeurs: Props): void {
  Object.assign(props, valeurs);
  if (!monte) {
    cible.replaceChildren();
    mount(Conseil, { target: cible, props });
    monte = true;
  }
}
