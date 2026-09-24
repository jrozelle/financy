// Cartes de la synthese portees en Svelte, montees chacune dans son element
// (static/modules/tabs/synthese.js les appelle a chaque rendu). La grille de
// widgets (static/modules/widgets.js) continue de les deplacer et de les
// dimensionner : elle ne touche que les elements hotes, qui restent en place.
import { mount } from 'svelte';
import Chiffres from './Chiffres.svelte';
import Repartition from './Repartition.svelte';
import Comptes from './Comptes.svelte';
import Contribution from './Contribution.svelte';
import Projection from './Projection.svelte';
import Fiscalite from './Fiscalite.svelte';
import HistoriqueNet from './HistoriqueNet.svelte';
import EvolutionGroupes from './EvolutionGroupes.svelte';
import Mouvements from './Mouvements.svelte';

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
export async function rechargerContribution(hote: HTMLElement, masque: boolean, cache: boolean,
                                           owner: string | null, consulte: string | null, dernier: string | null) {
  const instance = afficher(Contribution, hote, { hote, masque });
  // Bascule du mode discretion : on redessine sans redemander.
  if (!cache) await instance.recharger(owner, consulte, dernier);
}
export const afficherProjection = (hote: HTMLElement, props: Props) => afficher(Projection, hote, { hote, ...props });
export async function rechargerFiscalite(hote: HTMLElement, masque: boolean, owner: string | null, date: string | null) {
  await afficher(Fiscalite, hote, { hote, masque }).recharger(owner, date);
}
export const afficherHistoriqueNet = (hote: HTMLElement, props: Props) => afficher(HistoriqueNet, hote, props);
export const afficherEvolutionGroupes = (hote: HTMLElement, props: Props) => afficher(EvolutionGroupes, hote, { hote, ...props });
export const afficherMouvements = (hote: HTMLElement, props: Props) => afficher(Mouvements, hote, props);
