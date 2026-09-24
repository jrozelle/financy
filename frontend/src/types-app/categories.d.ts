// Types de static/modules/categories.js (application existante, JavaScript).
export interface Nature { id: 'liq' | 'fin' | 'immo' | 'biens'; nom: string; couleur: string; aide: string }
export declare const NATURES: Nature[];
export declare function natureDe(category: string | null, envelope: string | null): Nature['id'];
