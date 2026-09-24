// Donnees de /api/holdings/consolidated (routes/holdings.py).
export interface LigneActif {
  isin: string; name: string | null; asset_class: string | null; establishments: string[] | null; envelopes: string[] | null;
  quantity: number | null; avg_cost: number | null; last_price: number | null; currency: string | null;
  last_price_date: string | null; ticker: string | null; is_priceable: boolean;
  market_value: number; pnl: number | null; pnl_pct: number | null; weight_pct: number | null;
}
export interface Repartition { label: string; market_value: number; weight_pct: number | null }
export interface Consolide {
  totals: { market_value: number; cost_basis: number | null; pnl: number | null; pnl_pct: number | null; lines_count: number };
  lines: LigneActif[];
  breakdowns: { asset_class?: Repartition[]; envelope?: Repartition[] };
}
