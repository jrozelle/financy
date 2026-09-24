// La synthese en Svelte : une racine (Synthese.svelte) rend la grille et ses
// douze cartes dans l'onglet ; static/modules/tabs/synthese.js lui passe les
// donnees a chaque rendu. La note de l'arrete, au-dessus de la grille, se
// monte a part.
import { mount } from 'svelte';
import Synthese from './Synthese.svelte';
import NoteArrete from './NoteArrete.svelte';

type Props = Record<string, any>;
let racine: any = null;
const etat = $state<{ onglet: HTMLElement | null; cartes: Props | null }>({ onglet: null, cartes: null });

export function afficherSynthese(onglet: HTMLElement, cartes: Props) {
  etat.cartes = cartes;
  if (!racine) {
    etat.onglet = onglet;
    racine = mount(Synthese, { target: onglet, props: etat as { onglet: HTMLElement; cartes: Props } });
  }
  return racine;
}

export function rechargerSynthese(options: { owner: string | null; date: string | null; dernier: string | null; cache: boolean }) {
  return racine?.recharger(options);
}

export function basculerEdition() { racine?.basculerEdition(); }

let note: { props: Props } | null = null;
export function afficherNote(hote: HTMLElement, props: Props) {
  if (!note) {
    const p = $state({ hote, ...props });
    note = { props: p };
    mount(NoteArrete, { target: hote, props: p as any });
  } else Object.assign(note.props, props);
}
