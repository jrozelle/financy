// Point d'entree de l'onglet Flux, charge a la demande par
// static/modules/tabs/flux.js : monte le composant une fois, puis lui passe
// les flux a chaque rendu.
import { mount } from 'svelte';
import Flux from './Flux.svelte';
import type { Flux as UnFlux } from './types';

interface Props {
  flux: UnFlux[]; owner: string | null; masque: boolean; titulaires: string[]; titulaireDefaut: string;
  onEditer: (id: number) => void; onSupprimer: (id: number) => void; onEnregistre: () => void;
}

let props = $state<Props>({ flux: [], owner: null, masque: false, titulaires: [], titulaireDefaut: '',
  onEditer: () => {}, onSupprimer: () => {}, onEnregistre: () => {} });
let monte = false;

export function afficher(cible: HTMLElement, valeurs: Props): void {
  Object.assign(props, valeurs);
  if (!monte) {
    cible.replaceChildren();
    mount(Flux, { target: cible, props });
    monte = true;
  }
}
