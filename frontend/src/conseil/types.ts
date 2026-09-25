// Donnees de /api/advisor/* (routes/advisor.py).
export interface Profil {
  horizon_years: number | null; risk_tolerance: number | null; employment_type: string | null; pension_age: number | null;
  children_count: number | null; reserve_eur: number | null; main_residence_owned: boolean | number; has_lbo: boolean | number;
  charges_mensuelles?: number | null; mois_precaution?: number | null;
  notes: string | null;
}
export interface Objectif { id: number; label: string | null; target_amount: number | null; horizon_years: number | null; priority: number }
export interface Ecart { category: string; target_pct: number; actual_pct: number; delta_pct: number; delta_eur: number; bloque_eur?: number }
export interface Allocation { adjustments?: string[]; gap: Ecart[]; total_eur: number; financier_eur?: number; bloque_eur?: number;
                              exclus?: { category: string; montant: number }[] }
export interface Proposition { id: number; kind: string; status: string; label: string; rationale: string | null }
export interface Constat { niveau: string; titre: string; detail: string; onglet?: string | null }
