// Types de static/modules/api.js (application existante, JavaScript), charge
// a l'execution par son URL. Seule la partie utilisee par les ecrans Svelte.
export declare function api<T = unknown>(methode: string, chemin: string, corps?: unknown,
                                 options?: { silent?: boolean }): Promise<T>;
export declare function buildSelects(): void;
export declare function refreshEntitySelect(): void;
