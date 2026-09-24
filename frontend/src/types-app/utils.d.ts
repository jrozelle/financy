// Types de static/modules/utils.js (application existante, JavaScript), charge
// a l'execution par son URL. Seule la partie utilisee par les ecrans Svelte.
/** Montant en euros, arrondi, masque en mode discretion. */
export declare function fmt(n: number | null | undefined, dec?: number): string;
export declare function fmtDate(d: string | null | undefined): string;
export declare function fmtPct(n: number | null | undefined, dec?: number, signe?: boolean): string;
/** Badge HTML (deja echappe) d'une classe de liquidite. */
export declare function liqBadge(liq: string | null | undefined): string;
export declare function fmtAxis(n: number): string;
export declare function parseLocaleNumber(s: string, defaut?: number): number;
export declare function today(): string;
/** Tri stable, valeurs absentes en bas dans les deux sens. */
export declare function sortArr<T>(liste: T[], cle: string | null, sens: number): T[];
