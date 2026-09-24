// Une position telle que /api/positions la rend (compute_position), en euros.
export interface Position {
  id: number; date: string; owner: string; category: string; envelope: string | null;
  establishment: string | null; entity: string | null; label: string | null; notes: string | null;
  ownership_pct: number | null;
  gross_attributed: number; debt_attributed: number; net_attributed: number;
  gain_attributed: number | null; gain_pct: number | null; gain_lignes: number; holdings_count: number;
  has_holdings: boolean;
}

/** Une ligne de titres (/api/positions/<id>/holdings). */
export interface Titre {
  id: number; isin: string; name: string | null;
  market_value: number | null; cost_basis: number | null; effective_value?: number | null;
}

/** Un noeud de l'arborescence : groupe (nature, titulaire, etablissement,
 *  entite), compte (position) ou ligne de titres. Montants ATTRIBUES (la
 *  part du titulaire) : ce sont eux qui s'additionnent. */
export interface Noeud {
  cle: string; niveau: number; visuel?: number; nom: string; sous: string; chip: string;
  couleur?: string; pastille?: boolean;
  brut: number; dette: number; gain: number; mesures: number;
  enfants: Noeud[]; position?: Position; titres?: boolean;
  contexte?: { owner: string | null; establishment: string | null; entity: string | null };
  /** Ligne de titres : plus-value deja calculee (null = PRU inconnu). */
  gainTitre?: number | null;
}
