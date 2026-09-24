// Types de static/modules/dialogs.js (application existante, JavaScript), charge
// a l'execution par son URL. Seule la partie utilisee par les ecrans Svelte.
export declare function toast(message: string, type?: 'success' | 'error'): void;
export declare function confirmDialog(titre: string, corps: string): Promise<boolean>;
