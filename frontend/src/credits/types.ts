// Reponses de /api/prets*, en euros (le serveur convertit les centimes).

export interface Echeance {
  pret_id: number; rang: number; date: string;
  capital: number; interets: number; assurance: number; crd: number;
  pret?: string;
}

export interface Pret {
  id: number; libelle: string; preteur: string | null; entity: string | null;
  montant: number; taux: number | null; debut: string | null; fin: string;
  crd: number; rembourse: number; echeances: number; restantes: number;
  prochaine: Echeance | null; echeance_du_mois: number | null; mensualite: number | null;
  differe: { type: 'total' | 'partiel'; jusqu_au: string | null } | null;
  taux_retenu: number | null; taux_deduit: boolean;
  ira: number; ira_contrat: 'legale' | 'aucune'; ira_mode?: 'legale' | 'aucune';
  interets_restants: number;
  part?: number;                    // vu par un titulaire : sa part de dette
}

export interface AutreDette { libelle: string; montant: number; notes: string | null; date: string }

export interface Resume { date: string; prets: Pret[]; autres_dettes?: AutreDette[] }

export interface Projection {
  dates: string[]; total: number[]; total_amortissable?: number[];
  prets: { id: number; libelle: string; fin: string; points: number[] }[];
}

export interface Annee { annee: string; capital: number; interets: number; assurance: number;
                         crd_fin: number; echeances: number }

export interface Calendrier { prochaines: Echeance[]; annees: Annee[] }

export interface ApercuImport {
  libelle: string; preteur: string; emprunteur: string | null; montant: number; taux: number | null;
  echeances: number; debut: string; fin: string; controles?: string[];
  deja: { id: number; libelle: string } | null; entite_proposee?: string | null;
}
