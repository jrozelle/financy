export const S = {
  config:        null,
  dates:         [],
  syntheseDate:  null,
  positionsDate: null,
  // Periode sur laquelle tous les deltas de la synthese sont calcules.
  periodeComparaison: 'periode',
  synthese:      null,
  syntheseOwner: 'Famille',
  positions:     [],
  flux:          [],
  historique:    [],
  entities:        [],
  entitySnapshots: [],
  positionsView:   localStorage.getItem('financy_positionsView') || 'tree',   // l'arborescence par defaut
  currentTab:      'synthese',
  editPosId:       null,
  editFluxId:      null,
  editEntityId:    null,
  sort: {
    positions: { key: null, dir: 1 },
    flux:      { key: null, dir: 1 },
    entities:  { key: null, dir: 1 },
  },
  referential: null,
  entityPositions: null,
};



export let _targetsCache = null;
export let _alertsCache  = null;
export function setTargetsCache(v) { _targetsCache = v; }
export function setAlertsCache(v)  { _alertsCache = v; }
