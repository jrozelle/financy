export const S = {
  config:        null,
  dates:         [],
  syntheseDate:  null,
  positionsDate: null,
  synthese:      null,
  syntheseOwner: 'Famille',
  positions:     [],
  flux:          [],
  historique:    [],
  entities:        [],
  entitySnapshots: [],
  positionsView:   localStorage.getItem('financy_positionsView') || 'table',
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

export let catChart          = null;
export let histChart         = null;
export let syntheseEnvChart  = null;
export let syntheseHistChart = null;

export function setCatChart(v)          { catChart = v; }
export function setHistChart(v)         { histChart = v; }
export function setSyntheseEnvChart(v)  { syntheseEnvChart = v; }
export function setSyntheseHistChart(v) { syntheseHistChart = v; }

export let _targetsCache = null;
export let _alertsCache  = null;
export function setTargetsCache(v) { _targetsCache = v; }
export function setAlertsCache(v)  { _alertsCache = v; }
