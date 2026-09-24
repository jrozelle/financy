// Types de static/modules/state.js (application existante, JavaScript), charge
// a l'execution par son URL. Seule la partie utilisee par les ecrans Svelte.
export declare const S: {
  syntheseOwner: string | null;
  entities: { name: string; type?: string | null; debt?: number | null }[] | null;
  positions: unknown[];
  sort: Record<string, { key: string | null; dir: number }>;
};
