// Point d'entree du tableau des entites, charge a la demande par
// static/modules/tabs/entities.js : monte le composant une fois, puis lui
// passe les donnees a chaque rendu.
import { mount } from 'svelte';
import Entites from './Entites.svelte';
import type { Entite, ArreteEntite, PositionLiee } from './types';

interface Props {
  entites: Entite[]; arretes: ArreteEntite[]; positions: PositionLiee[]; owner: string | null; masque: boolean;
  onEditer: (id: number) => void; onSupprimer: (id: number) => void;
  onHistorique: (nom: string) => void; onAjouterPosition: (nom: string) => void;
}

let props = $state<Props>({ entites: [], arretes: [], positions: [], owner: null, masque: false,
  onEditer: () => {}, onSupprimer: () => {}, onHistorique: () => {}, onAjouterPosition: () => {} });
let monte = false;

export function afficher(cible: HTMLElement, valeurs: Props): void {
  Object.assign(props, valeurs);
  if (!monte) {
    cible.replaceChildren();
    mount(Entites, { target: cible, props });
    monte = true;
  }
}
