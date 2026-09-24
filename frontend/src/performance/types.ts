// Donnees de /api/performance (routes/performance.py).
export interface AlerteCours { name?: string; isin?: string; reason: string }
export interface Suspect { from: string; to: string; change: number; delta: number; flux: number | null }
export interface Groupe {
  key: string; label: string; envelope?: string | null; account_label?: string | null; establishment?: string | null;
  owner?: string | null; categories?: string[]; status: string; reason?: string | null; last_date?: string | null;
  value: number; tri: number | null; tri_periode: number | null; tri_jours: number | null;
  twr: number | null; twr_annualise: number | null; annualisable: boolean; days: number | null;
  flux_net: number; flux_count: number; dates_count: number; accounts?: number;
  price_warnings?: AlerteCours[]; suspect_periods?: Suspect[]; groups?: unknown[];
  serie?: { date: string; index: number | null }[];
}
export interface Perf {
  insufficient?: boolean; groups: Groupe[]; global: Groupe | null;
  marche?: (Groupe & { exclus?: number; exclus_valeur?: number }) | null;
  dates: string[]; first_date: string; date: string; excluded: unknown[]; min_days_annualise: number;
}
