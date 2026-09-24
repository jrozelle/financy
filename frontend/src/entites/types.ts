export interface Entite {
  id: number; name: string; type: string | null; valuation_mode: string | null;
  gross_assets: number; debt: number; net_assets: number; comment: string | null;
}
export interface ArreteEntite { id: number; entity_name: string; date: string; gross_assets: number; debt: number }
export interface PositionLiee { entity: string | null; owner: string; ownership_pct: number | null; debt_pct: number | null }
