// Types de static/modules/courbe.js (application existante, JavaScript), charge
// a l'execution par son URL. Seule la partie utilisee par les ecrans Svelte.
export interface Serie { nom: string; couleur: string; points: { date: string; v: number }[];
                         aire?: boolean; pointille?: boolean }
export declare function dessinerCourbe(hote: HTMLElement, options: {
  series: Serie[]; formatY?: (v: number) => string; formatV: (v: number) => string; aide?: string;
  onPoint?: (date: string) => void;
}): void;
