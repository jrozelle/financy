// Point d'entree d'Import / Export (fenetre des Reglages), monte au
// demarrage par static/modules/tabs/import-export.js (initDemoToggle) : le
// badge du mode demo doit etre juste avant toute visite de l'ecran.
import { mount } from 'svelte';
import ImportExport from './ImportExport.svelte';

type Props = { demo: { available: boolean; demo: boolean } | null; rappels: Record<string, (...a: never[]) => Promise<void>> };
let props = $state<Props>({ demo: null, rappels: {} });
let monte = false;

export function afficher(cible: HTMLElement, valeurs: Props): void {
  Object.assign(props, valeurs);
  if (!monte) {
    cible.replaceChildren();
    mount(ImportExport, { target: cible, props: props as never });
    monte = true;
  }
}
