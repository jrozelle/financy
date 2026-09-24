// Types de static/modules/alerts.js : les alertes de seuil de la synthese.
export interface Alerte { label: string; metric: string; category?: string; op: string; threshold: number }
export declare function loadUserAlerts(): Alerte[];
export declare function saveUserAlerts(alertes: Alerte[]): Promise<void>;
