// Point d'entree de l'onglet Outils, charge a la demande par
// static/modules/tabs/tools.js : monte le composant une fois, puis lui passe
// le mode discret et un numero de visite (une visite recharge la frise).
import { mount } from 'svelte';
import Outils from './Outils.svelte';

interface Props { masque: boolean; visite: number }
let props = $state<Props>({ masque: false, visite: 0 });
let monte = false;

export function afficher(cible: HTMLElement, valeurs: Props): void {
  Object.assign(props, valeurs);
  if (!monte) {
    cible.replaceChildren();
    mount(Outils, { target: cible, props });
    monte = true;
  }
}
