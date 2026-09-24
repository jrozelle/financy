// Donnees de /api/entites/tresorerie (services/tresorerie_entite.py).
export interface Mois { mois: string; revenu: number; revenu_exceptionnel: number; echeance: number; frais: number;
                        apport: number; interne: number; autre: number }
export interface Operation { id: number; date: string; libelle: string; nature: string; montant: number;
                             banque: string | null; source: string }
export interface Part { nom: string; parts: number | null; montant_souscrit: number | null; prix_souscription: number | null;
                        prix_retrait: number | null; prix_retrait_retenu?: number | null; retrait_estime?: boolean;
                        valeur_retrait?: number | null; date_prix: string | null }
export interface Exercice { fin?: string; resultat?: number | null; source?: string | null }
export interface Bloc {
  entite: string; periode: { debut: string; fin: string; mois: number } | null;
  indicateurs: { couverture: number | null; effort_mensuel: number; apports: number; capital_par_euro_apporte: number | null;
                 rendement: number | null; cash_flow_net: number | null };
  credit: { capital: number; interets: number; assurance: number; taux: number | null } | null;
  totaux: { revenu: number; revenu_exceptionnel: number; echeance: number };
  parts: { lignes: Part[]; valeur_retrait: number; montant_souscrit: number } | null;
  fiscal: { annee: string; impot: number; deficit_reportable: number; deficit_apres: number; exercices: Exercice[];
            projection: { revenus: number; interets: number; frais: number; resultat: number } } | null;
  frais_latents: number; tresorerie: number; valeur: number; mensuel: Mois[]; operations: Operation[];
}
export interface Tresorerie { entites: Bloc[]; natures: Record<string, string> }

export const MOIS_COURTS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
export const moisLib = (m: string) => `${MOIS_COURTS[+m.slice(5, 7) - 1]} ${m.slice(0, 4)}`;
export const virgule = (v: number | string) => String(v).replace('.', ',');
