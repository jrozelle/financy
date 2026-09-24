// Point d'entree de la carte « Tresorerie et levier » de l'onglet Entites,
// charge a la demande par static/modules/tabs/tresorerie.js : monte le
// composant une fois, puis lui passe les donnees a chaque chargement.
import { mount } from 'svelte';
import Tresorerie from './Tresorerie.svelte';
import type { Tresorerie as Donnees } from './donnees-tresorerie';

interface Props { donnees: Donnees | null; entites: string[]; masque: boolean; onRecharger: () => Promise<void> }

let props = $state<Props>({ donnees: null, entites: [], masque: false, onRecharger: async () => {} });
let monte = false;

export function afficher(cible: HTMLElement, valeurs: Props): void {
  Object.assign(props, valeurs);
  if (!monte) {
    cible.replaceChildren();
    mount(Tresorerie, { target: cible, props });
    monte = true;
  }
}
