// Un flux tel que /api/flux le rend, en euros.
export interface Flux {
  id: number; date: string; owner: string; envelope: string | null; establishment: string | null;
  category: string | null; type: string | null; amount: number; notes: string | null;
}
