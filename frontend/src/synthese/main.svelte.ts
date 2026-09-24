// Cartes de la synthese portees en Svelte, montees chacune dans son element
// (static/modules/tabs/synthese.js les appelle a chaque rendu). La grille de
// widgets (static/modules/widgets.js) continue de les deplacer et de les
// dimensionner : elle ne touche que les elements hotes, qui restent en place.
import { mount } from 'svelte';
import Chiffres from './Chiffres.svelte';
import Repartition from './Repartition.svelte';
import Comptes from './Comptes.svelte';

type Props = Record<string, any>;
const montes = new Map<HTMLElement, { props: Props; instance: any }>();

function afficher(Composant: any, hote: HTMLElement, props: Props) {
  let m = montes.get(hote);
  if (!m) {
    // Les commandes de la grille de widgets vivent aussi dans l'hote : on ne
    // retire que l'ancien contenu, avant le premier montage.
    [...hote.children].forEach(e => { if (!e.matches('.w-commandes, .w-bord')) e.remove(); });
    const etat = $state({ ...props });
    m = { props: etat, instance: mount(Composant, { target: hote, props: etat }) };
    montes.set(hote, m);
  } else {
    Object.assign(m.props, props);
  }
  return m.instance;
}

export const afficherChiffres = (hote: HTMLElement, props: Props) => afficher(Chiffres, hote, props);
export const afficherRepartition = (hote: HTMLElement, props: Props) => afficher(Repartition, hote, props);
export async function rechargerComptes(hote: HTMLElement, owner: string | null, date: string | null) {
  await afficher(Comptes, hote, { hote }).recharger(owner, date);
}
