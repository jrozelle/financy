import { esc, fmt } from '/static/modules/utils.js';

// Les montants des constats et des propositions arrivent marques ⟦v⟧ :
// formates ici, ils suivent le mode discretion comme tous les autres. Ecrits
// en clair par le serveur, ils s'affichaient meme masques. Rend du HTML echappe.
export const montants = (t: string | null | undefined) => esc(t || '').replace(/⟦(-?[\d.]+)⟧/g, (_, v) => fmt(Number(v)));
