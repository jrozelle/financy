// Point d'entree du Referentiel (fenetre des Reglages), charge a la demande
// par static/modules/tabs/referentiel.js : monte le composant une fois, puis
// lui passe le mode discret et un numero de visite (une visite recharge).
import { mount } from 'svelte';
import Referentiel from './Referentiel.svelte';

interface Props { masque: boolean; visite: number }
let props = $state<Props>({ masque: false, visite: 0 });
let monte = false;

export function afficher(cible: HTMLElement, valeurs: Props): void {
  Object.assign(props, valeurs);
  if (!monte) {
    cible.replaceChildren();
    mount(Referentiel, { target: cible, props });
    monte = true;
  }
}
