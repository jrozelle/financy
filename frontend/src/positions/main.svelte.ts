// Point d'entree de l'onglet Positions (l'arborescence), charge a la demande
// par static/modules/tabs/positions.js : monte le composant une fois, puis
// lui passe les positions a chaque rendu.
import { mount } from 'svelte';
import Arbo from './Arbo.svelte';
import type { Position } from './types';

interface Instance { oublierTitres(id?: number | null): void }

let props = $state<{ positions: Position[] }>({ positions: [] });
let instance: Instance | null = null;

export function afficher(cible: HTMLElement, positions: Position[]): Instance {
  props.positions = positions;
  if (!instance) {
    cible.replaceChildren();
    instance = mount(Arbo, { target: cible, props }) as unknown as Instance;
  }
  return instance;
}
