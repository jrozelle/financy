import { S, setTargetsCache } from './state.js';
import { initMask, toggleMask, isMasked, onMaskChange } from './mask.js';
import { wireTodo } from './todo.js';
import { wireReglages, estUnReglage, ouvrir as ouvrirReglages } from './reglages.js';
import { initBarreMobile } from './barre-mobile.js';
import { etiqueter, dateCourte } from './select-etiquette.js';
import { fmtDate, esc, applyChartTheme, refreshChartsTheme } from './utils.js';
import { api, buildSelects } from './api.js';
import { closeModal, openModal, trapModalFocus, installModalScrollLock } from './dialogs.js';
import { wireDrilldownEvents, drilldownHistory } from './drilldown.js';
import { wireTargetsEvents } from './targets.js';
import { loadUserAlertsAsync, saveUserAlerts } from './alerts.js';
import { loadTargets, saveTargets } from './targets.js';
import { wireSortableTable } from './utils.js';

import { loadSynthese, renderSynthese, renderSyntheseHistory, loadHistorique, wireSyntheseMenu } from './tabs/synthese.js';
import { loadPositions, renderPositions, clearFilters, openPosModal, duplicateSnapshot, renameSnapshot, deleteSnapshot,
         onEntitySelectChange, updatePosInfo, savePosition, deletePosition,
         persistPositionFilters, ensurePositionsTableScaffold } from './tabs/positions.js';
import { openHoldingsModal, wireHoldingsEvents, confirmCloseHoldings } from './tabs/holdings.js';
import { loadPrets, ouvrirFormulaireCredit } from './tabs/prets.js';
import { loadTresorerie, initTresorerie } from './tabs/tresorerie.js';
import { wireIsinPopoverEvents, closeIsinPopover } from './isin-popover.js';
import { loadAdvisor, wireAdvisorEvents } from './tabs/advisor.js';
import { loadActifs, wireActifsEvents } from './tabs/actifs.js';
import { loadFlux, renderFlux, openFluxModal, saveFlux, persistFluxFilters, clearFluxFilters, wireFluxImport } from './tabs/flux.js';
import { loadEntities, renderEntities, openEntityModal, saveEntity, updateEntInfo } from './tabs/entities.js';
import { importXlsx, importJson, exportJson, resetDb, initDemoToggle, createBackup, updateDemoBadge } from './tabs/import-export.js';
import { loadReferential, saveReferential, initTemplateSelect } from './tabs/referentiel.js';
import { loadTimeline, wireSimulation, triggerAutoSnapshot, triggerPricesRefresh, loadSchedulerStatus } from './tabs/tools.js';
import { loadPerformance, renderPerformance } from './tabs/performance.js';
import { wireGlobalSearch, resetSearchCache } from './search.js';
import { wireMiseAJour, ouvrir as ouvrirMiseAJour } from './mise-a-jour.js';
import { wireSettingsEvents } from './settings.js';
import { initColumnPicker } from './column-picker.js';

// localStorage peut lever (Safari prive, stockage bloque) : lu au demarrage,
// il faisait echouer tout le chargement.
function _lsGet(cle) {
  try { return localStorage.getItem(cle); } catch { return null; }
}
function _lsSet(cle, valeur) {
  try { localStorage.setItem(cle, valeur); } catch { /* session privee */ }
}

// ─── Init ─────────────────────────────────────────────────────────────────

async function init() {
  initMask();
  wireTodo(switchTab);   // la zone « À traiter » renvoie vers l'onglet concerne
  wireReglages(chargerEcranReglage);
  initBarreMobile();
  S.config = await api('GET', '/api/config');
  buildSelects();
  _lireContexte({ avecArrete: false });
  _buildGlobalOwnerFilter();
  wireEvents();
  wireDrilldownEvents();
  wireGlobalSearch(switchTab);
  // Une fois enregistre, on se place sur l'arrete cree et on recharge l'ecran
  // courant — le nouvel arrete doit apparaitre la ou on l'a lance.
  wireMiseAJour(async cible => {
    S.syntheseDate = cible;
    S.positionsDate = cible;
    resetSearchCache();
    await refreshDates();
    ecrireContexte();
    await loadHistorique();
    _lastLoadedTab = null;
    await switchTab(S.currentTab, { pushHistory: false });
  });
  await Promise.all([refreshDates(), loadEntities(), loadHistorique(), loadTargets(), loadUserAlertsAsync()]);
  await migrateLocalStorageToDB();
  _lireContexte();
  _refleterContexte();
  ecrireContexte();          // une valeur ignoree disparait aussi de l'adresse
  await _ouvrirDepuisAdresse(_tabFromUrl());
  initDemoToggle();
}

/** Recharge tout apres un changement de base (mode demo) ou de referentiel
 *  (titulaire renomme). L'onglet courant se recharge vraiment : switchTab
 *  s'arretait, l'onglet etant « deja charge », et laissait les donnees de
 *  l'ancienne base a l'ecran. */
export async function reloadAll() {
  S.config = await api('GET', '/api/config');
  buildSelects();
  // Les donnees de l'ancienne base ne doivent plus servir nulle part.
  S.synthese = null;
  S.positions = [];
  S.flux = [];
  setTargetsCache(null);
  resetSearchCache();
  await Promise.all([refreshDates(), loadEntities(), loadHistorique(), loadTargets(), loadUserAlertsAsync()]);
  // Arrete et titulaire absents de la nouvelle base : retour aux defauts.
  if (!S.dates.includes(S.syntheseDate)) S.syntheseDate = S.dates[0] || null;
  if (!S.dates.includes(S.positionsDate)) S.positionsDate = S.syntheseDate;
  if (S.syntheseOwner !== 'Famille' && !(S.config.owners || []).includes(S.syntheseOwner)) {
    S.syntheseOwner = 'Famille';
  }
  _buildGlobalOwnerFilter();
  _refleterContexte();
  ecrireContexte();
  _lastLoadedTab = null;
  await switchTab(S.currentTab || 'synthese', { pushHistory: false });
}

async function migrateLocalStorageToDB() {
  const lsTargets = _lsGet('patrimoine_targets');
  if (lsTargets) {
    try {
      const parsed = JSON.parse(lsTargets);
      if (Object.keys(parsed).length > 0) await saveTargets(parsed);
    } catch {}
  }
  const lsAlerts = _lsGet('patrimoine_alerts');
  if (lsAlerts) {
    try {
      const parsed = JSON.parse(lsAlerts);
      if (parsed.length > 0) await saveUserAlerts(parsed);
    } catch {}
  }
}

// ─── Dates ────────────────────────────────────────────────────────────────

export async function refreshDates() {
  S.dates = await api('GET', '/api/dates');
  renderDateSelects();
}

export function renderDateSelects() {
  const html = S.dates.map(d => `<option value="${d}">${fmtDate(d)}</option>`).join('');
  document.getElementById('synthese-date-select').innerHTML  = html;
  document.getElementById('positions-date-select').innerHTML = html;
  if (S.syntheseDate)  document.getElementById('synthese-date-select').value  = S.syntheseDate;
  if (S.positionsDate) document.getElementById('positions-date-select').value = S.positionsDate;
}

// ─── Loading spinner ──────────────────────────────────────────────────

function showLoading(tabId) {
  const el = document.getElementById(tabId);
  if (!el) return;
  let loader = el.querySelector('.tab-loading');
  if (!loader) {
    loader = document.createElement('div');
    loader.className = 'tab-loading';
    loader.innerHTML = '<div class="spinner"></div>';
    el.prepend(loader);
  }
  loader.style.display = '';
}

function hideLoading(tabId) {
  const el = document.getElementById(tabId);
  if (!el) return;
  const loader = el.querySelector('.tab-loading');
  if (loader) loader.style.display = 'none';
}

// ─── Tabs ─────────────────────────────────────────────────────────────────

// ─── Global owner filter ──────────────────────────────────────────────────

// ── Contexte de lecture dans l'adresse ───────────────────────────────
// Titulaire, arrete et periode se perdaient au rechargement. Ils vivent dans
// l'adresse : un rechargement, un favori ou un lien partage les gardent, et
// Precedent / Suivant restent coherents. Une valeur par defaut n'est pas
// ecrite — /synthese seul montre la famille au DERNIER arrete, y compris
// quand un nouvel arrete a ete cree depuis.
function _contexteQuery() {
  const q = new URLSearchParams();
  if (S.syntheseOwner && S.syntheseOwner !== 'Famille') q.set('titulaire', S.syntheseOwner);
  if (S.syntheseDate && S.dates?.length && S.syntheseDate !== S.dates[0]) q.set('arrete', S.syntheseDate);
  if (S.periodeComparaison && S.periodeComparaison !== 'periode') q.set('periode', S.periodeComparaison);
  const t = q.toString();
  return t ? `?${t}` : '';
}

export function ecrireContexte() {
  const url = location.pathname + _contexteQuery();
  if (url !== location.pathname + location.search) history.replaceState(history.state, '', url);
}

/** Lit l'adresse. Une valeur qui ne correspond plus a rien — titulaire
 *  retire du referentiel, arrete supprime — est ignoree, pas imposee. */
function _lireContexte({ avecArrete = true } = {}) {
  const q = new URLSearchParams(location.search);
  const t = q.get('titulaire');
  if (t && ['Famille', ...(S.config?.owners || [])].includes(t)) S.syntheseOwner = t;
  else if (!t) S.syntheseOwner = 'Famille';
  const p = q.get('periode');
  S.periodeComparaison = p === 'an' ? 'an' : 'periode';
  if (!avecArrete) return;
  const a = q.get('arrete');
  if (a && S.dates?.includes(a)) { S.syntheseDate = a; S.positionsDate = a; }
  else if (!a && S.dates?.length) { S.syntheseDate = S.dates[0]; S.positionsDate = S.dates[0]; }
}

/** Remet les controles de l'en-tete dans l'etat de S. */
function _refleterContexte() {
  const sel = document.getElementById('global-owner-filter');
  if (sel) sel.value = S.syntheseOwner || 'Famille';
  renderDateSelects();
  document.querySelectorAll('#seg-periode [data-periode]').forEach(b =>
    b.setAttribute('aria-pressed', String(b.dataset.periode === S.periodeComparaison)));
}

function _buildGlobalOwnerFilter() {
  const sel = document.getElementById('global-owner-filter');
  if (!sel) return;
  const owners = S.config?.owners || [];
  sel.innerHTML = '<option value="Famille">Famille</option>' +
    owners.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('');
  sel.value = S.syntheseOwner || 'Famille';
}

function _onGlobalOwnerChange(e) {
  S.syntheseOwner = e.target.value;
  ecrireContexte();
  resetSearchCache();
  // Force reload current tab
  _lastLoadedTab = null;
  switchTab(S.currentTab, { pushHistory: false });
}

const VALID_TABS = new Set([
  'synthese', 'positions', 'actifs', 'flux', 'entites', 'credits', 'performance', 'conseil',
  'referentiel', 'tools', 'import',
]);

// Ajoute/retire .has-overflow sur les .card-table selon leur scroll horizontal.
// Appele une fois au boot + a chaque resize + a chaque changement d'onglet.
function _installTableOverflowHints() {
  let resizeTimer = null;
  const update = () => {
    document.querySelectorAll('.card-table').forEach(el => {
      const overflows = el.scrollWidth > el.clientWidth + 2;
      el.classList.toggle('has-overflow', overflows);
    });
  };
  const resizeCharts = () => {
    if (!window.Chart?.getChart) return;
    document.querySelectorAll('canvas').forEach(canvas => {
      window.Chart.getChart(canvas)?.resize();
    });
  };
  update();
  window.addEventListener('resize', () => {
    update();
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(resizeCharts, 120);
  });
  // Re-check overflow apres chaque resize (pas de MutationObserver — risque de boucle)
  document.querySelectorAll('.card-table').forEach(el => {
    el.addEventListener('scroll', () => {
      const scrolledRight = el.scrollLeft + el.clientWidth >= el.scrollWidth - 2;
      el.classList.toggle('has-overflow', !scrolledRight && el.scrollWidth > el.clientWidth + 2);
    });
  });
}

function _tabFromUrl() {
  const path = location.pathname.replace(/^\//, '');
  if (path === 'reglages') return 'preferences';
  return VALID_TABS.has(path) ? path : null;
}

/** Une adresse de reglage (/referentiel, /reglages...) designe une FENETRE,
 *  pas un ecran : ouverte seule, elle laissait la synthese vide derriere elle,
 *  « — » partout une fois fermee, et un rafraichissement la rouvrait. L'ecran
 *  de fond se charge d'abord ; l'adresse revient a lui. */
async function _ouvrirDepuisAdresse(tab) {
  if (tab && (tab === 'preferences' || estUnReglage(tab))) {
    history.replaceState(history.state, '', '/' + location.search);
    await switchTab('synthese', { pushHistory: false });
    ouvrirReglages(tab);
    return;
  }
  await switchTab(tab || 'synthese', { pushHistory: false });
}

let _lastLoadedTab = null;
let ouvrirRecherche = () => {};

/** Ce que « Ajouter » cree sur chaque onglet. Un onglet absent d'ici n'a pas
 *  de bouton : rien ne s'y ajoute a la main. */
const AJOUTS = {
  positions: { libelle: 'Ajouter une position', ouvrir: () => openPosModal() },
  flux:      { libelle: 'Ajouter un flux',      ouvrir: () => openFluxModal() },
  entites:   { libelle: 'Ajouter une entité',   ouvrir: () => openEntityModal() },
  credits:   { libelle: 'Ajouter un crédit',    ouvrir: () => ouvrirFormulaireCredit() },
};

/** Onglets ou « Mettre a jour » est l'action principale : ceux qui montrent
 *  les soldes. Sur Positions, il cede la couleur pleine a « Ajouter ». */
const MISE_A_JOUR = new Set(['synthese', 'positions']);

/** Sur telephone, la periode de comparaison quitte la barre du haut pour le
 *  menu « ··· » : une seule rangee de controles, de meme gabarit. */
function _placerPeriode(seg) {
  if (!seg || seg._place) return;
  seg._place = true;
  const origine = seg.parentElement, suivant = seg.nextSibling;
  const menu = document.getElementById('snapshot-dropdown');
  // Meme gabarit que les autres sections du menu : l'etiquette, puis le
  // segment au retrait des entrees.
  const etiquette = document.createElement('div');
  etiquette.className = 'settings-section-label';
  etiquette.textContent = 'Comparer à';
  const bloc = document.createElement('div');
  bloc.className = 'menu-periode';
  const mq = window.matchMedia('(max-width: 780px)');
  const placer = () => {
    if (mq.matches && menu) { bloc.appendChild(seg); menu.prepend(etiquette, bloc); }
    else { origine.insertBefore(seg, suivant); etiquette.remove(); bloc.remove(); }
  };
  placer();
  mq.addEventListener('change', placer);
}

function _majBoutonAjouter(tab) {
  const btn = document.getElementById('head-ajouter');
  const maj = document.getElementById('head-maj');
  const a = AJOUTS[tab];
  if (btn) {
    btn.classList.toggle('hidden', !a);
    // « Ajouter » seul en mode etroit : le complement reste lu par les
    // lecteurs d'ecran, et la barre du haut garde deux rangs.
    // Un seul element de texte : dans le flex du bouton, deux noeuds freres
    // perdaient l'espace qui les separait (« Ajouterune position »).
    if (a) {
      btn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 5v14M5 12h14"/></svg>`
        + `<span class="head-lib">${a.libelle.replace(/^Ajouter (.+)$/, 'Ajouter<span class="head-complement"> $1</span>')}</span>`;
      btn.setAttribute('aria-label', a.libelle);
    }
  }
  // « Periode / 1 an » ne regle que la synthese : ailleurs, il n'agissait sur
  // rien.
  document.getElementById('seg-periode')?.classList.toggle('hidden', tab !== 'synthese');
  if (maj) {
    maj.classList.toggle('hidden', !MISE_A_JOUR.has(tab));
    maj.classList.toggle('btn-primary', !a);
    maj.classList.toggle('btn-secondary', !!a);
  }
}


const LABELS_ONGLET = {
  synthese: 'Synthèse', positions: 'Positions', actifs: 'Actifs', entites: 'Entités', credits: 'Crédits',
  performance: 'Performance', flux: 'Flux', conseil: 'Conseil',
  referentiel: 'Référentiel', import: 'Import / Export', tools: 'Outils',
};



/** Titre de la page courante : pour les lecteurs d'ecran et l'onglet du
 *  navigateur. Il n'est plus affiche — le rail dit ou l'on est, et les
 *  selecteurs de l'en-tete disent deja l'arrete et le perimetre ; les repeter
 *  au-dessus d'eux ne faisait que repousser les chiffres. */
function majTitrePage(tab) {
  const h = document.getElementById('page-title');
  if (!h) return;
  const TITRES = {
    synthese: 'Synthèse du patrimoine', positions: 'Positions',
    actifs: 'Actifs détenus', entites: 'Entités', credits: 'Crédits', performance: 'Performance',
    flux: 'Flux et versements', conseil: 'Conseil patrimonial',
    referentiel: 'Référentiel', import: 'Import / Export', tools: 'Outils',
  };
  h.textContent = TITRES[tab] || 'Financy';
  document.title = TITRES[tab] ? `${TITRES[tab]} · Financy` : 'Financy';
}


/** Charge le contenu d'un ecran de reglages, sans rien changer a la navigation.
 *  `switchTab` ferait bien plus : masquer les autres onglets — dont celui qu'on
 *  voit derriere la fenetre —, changer le titre de page et deplacer la marque
 *  du rail. Ouvrir une fenetre n'est pas naviguer. */
export async function chargerEcranReglage(tab) {
  if (tab === 'referentiel') await loadReferential();
  if (tab === 'tools')       { await loadTimeline(); loadSchedulerStatus(); }
  // « import » n'a pas de chargement : son ecran est entierement statique.
}

export async function switchTab(tab, { pushHistory = true } = {}) {
  // Referentiel, Import et Outils sont desormais des onglets de la fenetre de
  // reglages : y « naviguer » revient a l'ouvrir. Si elle est deja ouverte,
  // l'appel vient d'elle et on poursuit le chargement normalement.
  const fenetre = document.getElementById('reglages-modal');
  const fenetreFermee = fenetre?.classList.contains('hidden') !== false;
  if (estUnReglage(tab) && fenetreFermee) {
    ouvrirReglages(tab);
    return;
  }
  S.currentTab = tab;
  document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById(`tab-${tab}`).classList.remove('hidden');
  // Le rail marque l'entree courante ; il porte les memes `data-tab`.
  document.querySelector(`.fin-rail [data-tab="${tab}"]`)?.classList.add('active');
  majTitrePage(tab);

  if (pushHistory && location.pathname !== `/${tab}`) {
    history.pushState({ tab }, '', `/${tab}${_contexteQuery()}`);
  }

  updateDemoBadge();
  _majBoutonAjouter(tab);

  const tabId = `tab-${tab}`;
  // Eviter de recharger l'onglet si on y est deja et qu'on ne force pas
  if (tab === _lastLoadedTab && pushHistory) {
    return;
  }
  _lastLoadedTab = tab;
  showLoading(tabId);
  _effacerErreur(tabId);
  try {
    if (tab === 'synthese')    await loadSynthese();
    if (tab === 'positions')   await loadPositions();
    if (tab === 'flux')        await loadFlux();
    if (tab === 'entites')     { await loadEntities(); initTresorerie(); loadTresorerie(); }
    if (tab === 'credits')     { if (!S.entities?.length) await loadEntities(); await loadPrets(); }
    if (tab === 'referentiel') await loadReferential();
    if (tab === 'actifs')      await loadActifs();
    if (tab === 'performance') await loadPerformance();
    if (tab === 'conseil')     await loadAdvisor();
    if (tab === 'tools')       { await loadTimeline(); loadSchedulerStatus(); }
  } catch (err) {
    // Un chargement echoue ne laisse pas l'ecran precedent se faire passer
    // pour le bon : l'onglet le dit, et propose de reessayer.
    console.error(`Chargement de l'onglet ${tab} :`, err);
    // L'onglet n'est pas « charge » : y revenir doit le redemander.
    if (_lastLoadedTab === tab) _lastLoadedTab = null;
    _afficherErreur(tabId, tab);
  } finally {
    hideLoading(tabId);
  }
}

/** Etat d'erreur d'un onglet : le contenu est masque, un message et un
 *  bouton Reessayer le remplacent. Retire au chargement suivant. */
function _afficherErreur(tabId, tab) {
  const el = document.getElementById(tabId);
  if (!el) return;
  _effacerErreur(tabId);
  [...el.children].forEach(c => {
    if (c.classList.contains('tab-loading')) return;
    if (!c.hidden) { c.hidden = true; c.dataset.masqueErreur = '1'; }
  });
  const box = document.createElement('div');
  box.className = 'card tab-erreur';
  box.setAttribute('role', 'alert');
  box.innerHTML = `
    <h2>Chargement impossible</h2>
    <p class="text-muted">Les données de cet écran n'ont pas pu être chargées. Vérifiez la connexion puis réessayez.</p>
    <button type="button" class="btn btn-primary">Réessayer</button>`;
  box.querySelector('button').addEventListener('click', () => {
    _lastLoadedTab = null;
    switchTab(tab, { pushHistory: false });
  });
  el.prepend(box);
}

function _effacerErreur(tabId) {
  const el = document.getElementById(tabId);
  if (!el) return;
  el.querySelector(':scope > .tab-erreur')?.remove();
  el.querySelectorAll(':scope > [data-masque-erreur]').forEach(c => {
    c.hidden = false;
    delete c.dataset.masqueErreur;
  });
}

// ─── Events ───────────────────────────────────────────────────────────────

function wireEvents() {
  // Tabs (ferment aussi le drawer mobile s'il est ouvert)
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Delegation globale : tout bouton avec data-tab-switch (CTA des empty states)
  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-tab-switch]');
    if (!btn) return;
    e.preventDefault();
    switchTab(btn.dataset.tabSwitch);
  });

  // Bouton d'aide raccourcis clavier
  document.getElementById('btn-keyboard-help')?.addEventListener('click', () => {
    openModal('keyboard-help-modal');
  });

  // Menu de l'arrete : note et objectif, actifs quel que soit l'onglet ouvert.
  wireSyntheseMenu();

  document.getElementById('btn-print')?.addEventListener('click', () => window.print());

  // Global owner filter
  document.getElementById('global-owner-filter')?.addEventListener('change', _onGlobalOwnerChange);
  etiqueter(document.getElementById('global-owner-filter'));
  etiqueter(document.getElementById('synthese-date-select'), dateCourte);

  // Browser back/forward
  window.addEventListener('popstate', e => {
    const tab = e.state?.tab || _tabFromUrl() || 'synthese';
    _lireContexte();
    _refleterContexte();
    resetSearchCache();
    _lastLoadedTab = null;
    _ouvrirDepuisAdresse(tab);
  });

  // Selecteurs d'arrete : l'onglet COURANT se recharge. Seuls Positions et
  // Actifs etaient traites ; ailleurs, c'est la synthese — cachee — qui se
  // rechargeait, et l'onglet visible gardait l'arrete precedent.
  const changerArrete = date => {
    S.syntheseDate = date;
    S.positionsDate = date;
    ecrireContexte();
    ['synthese-date-select', 'positions-date-select'].forEach(id => {
      const sel = document.getElementById(id);
      if (sel && sel.value !== date) sel.value = date;
    });
    resetSearchCache();
    _lastLoadedTab = null;
    return switchTab(S.currentTab || 'synthese', { pushHistory: false });
  };
  document.getElementById('synthese-date-select').addEventListener('change', e => changerArrete(e.target.value));
  document.getElementById('positions-date-select').addEventListener('change', e => changerArrete(e.target.value));

  // Positions buttons
  document.getElementById('pos-supprimer')?.addEventListener('click', () => {
    if (S.editPosId) deletePosition(S.editPosId);
  });
  document.getElementById('head-ajouter')?.addEventListener('click', () => {
    AJOUTS[S.currentTab]?.ouvrir();
  });
  document.getElementById('head-maj')?.addEventListener('click', () => ouvrirMiseAJour());
  document.getElementById('btn-maj')?.addEventListener('click', () => ouvrirMiseAJour());
  document.getElementById('btn-duplicate').addEventListener('click', duplicateSnapshot);
  document.getElementById('btn-rename-snapshot')?.addEventListener('click', renameSnapshot);
  document.getElementById('btn-delete-snapshot')?.addEventListener('click', deleteSnapshot);
  document.getElementById('filter-owner').addEventListener('change', () => {
    const val = document.getElementById('filter-owner').value;
    S.syntheseOwner = val || 'Famille';
    ecrireContexte();
    persistPositionFilters();
    resetSearchCache();
    const globalSel = document.getElementById('global-owner-filter');
    if (globalSel) globalSel.value = S.syntheseOwner;
    renderPositions();
  });
  document.getElementById('filter-envelope').addEventListener('change', () => {
    persistPositionFilters();
    renderPositions();
  });
  document.getElementById('filter-establishment').addEventListener('change', () => {
    persistPositionFilters();
    renderPositions();
  });
  document.getElementById('btn-clear-filters').addEventListener('click', clearFilters);

  // Tree delegation
  document.getElementById('positions-tree-wrap').addEventListener('click', ev => {
    const btn = ev.target.closest('[data-action]');
    if (btn) {
      const id = parseInt(btn.dataset.id);
      if (btn.dataset.action === 'edit-pos') openPosModal(id);
      if (btn.dataset.action === 'del-pos')  deletePosition(id);
      if (btn.dataset.action === 'manage-holdings') {
        const p = S.positions.find(x => x.id === id);
        const label = p ? `${p.envelope || p.category} (${p.owner})` : '';
        openHoldingsModal(id, label);
      }
      if (btn.dataset.action === 'add-pos-ctx') {
        openPosModal(null, {
          owner:         btn.dataset.owner         || undefined,
          establishment: btn.dataset.establishment || undefined,
          envelope:      btn.dataset.envelope      || undefined,
          entity:        btn.dataset.entity        || undefined,
        });
      }
      if (btn.dataset.action === 'history-pos') {
        drilldownHistory({
          subtitle: 'Évolution position',
          title: S.positions.find(p => p.id === parseInt(btn.dataset.id))?.category || '',
          filters: { position_id: btn.dataset.id },
        });
      }
      if (btn.dataset.action === 'history-env') {
        const f = { owner: btn.dataset.owner, envelope: btn.dataset.envelope };
        if (btn.dataset.establishment) f.establishment = btn.dataset.establishment;
        if (btn.dataset.entity) f.entity = btn.dataset.entity;
        drilldownHistory({ subtitle: 'Évolution enveloppe', title: btn.dataset.envelope, filters: f });
      }
      if (btn.dataset.action === 'history-etabl') {
        // Sans titulaire (etablissement partage), l'historique couvre tous.
        const f = btn.dataset.owner ? { owner: btn.dataset.owner } : {};
        if (btn.dataset.establishment) f.establishment = btn.dataset.establishment;
        if (btn.dataset.entity) f.entity = btn.dataset.entity;
        const label = btn.dataset.establishment || btn.dataset.entity || '';
        drilldownHistory({ subtitle: 'Évolution établissement', title: label, filters: f });
      }
    }
  });

  // Snapshot date
  document.getElementById('pos-snapshot-check').addEventListener('change', e => {
    document.getElementById('pos-snapshot-date').style.visibility = e.target.checked ? '' : 'hidden';
  });

  // Menu d'actions sur l'arrete courant.
  const snapToggle = document.getElementById('snapshot-toggle');
  const snapDropdown = document.getElementById('snapshot-dropdown');
  if (snapToggle && snapDropdown) {
    snapToggle.addEventListener('click', e => {
      e.stopPropagation();
      const ouvert = snapDropdown.classList.toggle('hidden');
      snapToggle.setAttribute('aria-expanded', String(!ouvert));
    });
    snapDropdown.addEventListener('click', e => {
      if (!e.target.closest('.settings-item')) return;
      snapDropdown.classList.add('hidden');
      snapToggle.setAttribute('aria-expanded', 'false');
    });
    document.addEventListener('click', e => {
      if (!e.target.closest('#snapshot-menu')) {
        snapDropdown.classList.add('hidden');
        snapToggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  // ── Recherche : une loupe dans la barre du haut ─────────────────────
  // Le champ ne s'ouvre qu'a la demande : il occupait en permanence une ligne
  // du rail pour un geste occasionnel. La touche / l'ouvre aussi.
  const loupe = document.getElementById('head-loupe');
  const recherche = document.getElementById('head-recherche-pop');
  const champ = document.getElementById('global-search-input');
  const fermerRecherche = () => {
    recherche?.classList.add('hidden');
    loupe?.setAttribute('aria-expanded', 'false');
  };
  ouvrirRecherche = () => {
    recherche?.classList.remove('hidden');
    loupe?.setAttribute('aria-expanded', 'true');
    champ?.focus();
    champ?.select();
  };
  loupe?.addEventListener('click', e => {
    e.stopPropagation();
    recherche.classList.contains('hidden') ? ouvrirRecherche() : fermerRecherche();
  });
  // search.js vide et quitte le champ sur Echap ; la surimpression suit.
  champ?.addEventListener('keydown', e => { if (e.key === 'Escape') fermerRecherche(); });
  document.addEventListener('click', e => {
    if (!e.target.closest('#global-search')) fermerRecherche();
  });
  // Choisir un resultat mene ailleurs : la surimpression n'a plus lieu d'etre.
  document.getElementById('search-results')?.addEventListener('click', e => {
    if (e.target.closest('.search-item')) fermerRecherche();
  });

  // ── Barre du bas : le bouton « Plus » deplie le rail entier ─────────
  // Sur telephone le rail ne montre que cinq destinations ; les sous-entrees,
  // la recherche et les reglages vivent derriere ce bouton. C'est le meme
  // element qui change de geometrie, donc rien a recabler.
  const rail = document.getElementById('fin-rail');
  const plus = document.getElementById('rail-plus');
  // Dans la feuille depliee, le bouton qui l'a ouverte est celui qui la ferme :
  // il le dit, plutot que de s'afficher « Plus » au milieu de la liste.
  const libPlus = plus?.querySelector('.fin-rail-lib');
  const majPlus = ouvert => {
    plus?.setAttribute('aria-expanded', String(ouvert));
    if (libPlus) libPlus.textContent = ouvert ? 'Fermer' : 'Plus';
  };
  const replierRail = () => {
    rail?.classList.remove('is-open');
    document.body.classList.remove('rail-ouvert');
    majPlus(false);
  };
  plus?.addEventListener('click', () => {
    const ouvert = rail.classList.toggle('is-open');
    document.body.classList.toggle('rail-ouvert', ouvert);
    majPlus(ouvert);
  });
  // Choisir une destination referme la feuille ; le bouton lui-meme la bascule.
  rail?.addEventListener('click', e => {
    if (e.target.closest('#rail-plus')) return;
    if (e.target.closest('.tab-btn, #ouvrir-reglages, [data-tab-switch]')) replierRail();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && rail?.classList.contains('is-open')) replierRail();
  });

  // ── Densité d'affichage ─────────────────────────────────────────────
  // Compacte par defaut : sur un patrimoine, on vient lire des chiffres et les
  // comparer, pas contempler des marges. Tout l'espacement derive d'une seule
  // variable, donc rien ne se desaligne quand elle change.
  //
  // Le reglage a quitte l'en-tete pour la fenetre Reglages — on le touche une
  // fois. La CLE de stockage change avec lui : l'ancienne avait ete ecrite au
  // premier chargement de chaque navigateur, si bien qu'un nouveau defaut n'y
  // serait jamais arrive.
  const DENSITES = [
    { cle: 'compacte',    valeur: '.78', libelle: 'Densité : compacte' },
    { cle: 'confortable', valeur: '1',   libelle: 'Densité : confortable' },
  ];
  const appliquerDensite = cle => {
    const d = DENSITES.find(x => x.cle === cle) || DENSITES[0];
    document.documentElement.style.setProperty('--d', d.valeur);
    document.querySelectorAll('[data-den]').forEach(b => {
      b.setAttribute('aria-pressed', String(b.dataset.den === d.cle));
    });
    try { localStorage.setItem('financy_densite', d.cle); } catch { /* session privee */ }
  };
  let densite = 'compacte';
  try { densite = localStorage.getItem('financy_densite') || 'compacte'; } catch { /* idem */ }
  appliquerDensite(densite);
  document.querySelectorAll('[data-den]').forEach(b => {
    b.addEventListener('click', () => appliquerDensite(b.dataset.den));
  });

  // Masquage : bouton visible, l'oeil dit l'etat sans avoir a ouvrir un menu.
  // Deux boutons, un seul etat : celui de l'en-tete et celui de la fenetre de
  // reglages. Les laisser diverger serait pire que de n'en avoir qu'un.
  const majBoutonMasque = () => {
    ['mask-btn', 'pref-mask-btn'].forEach(id => {
      const b = document.getElementById(id);
      if (b) b.setAttribute('aria-pressed', String(isMasked()));
    });
    ['mask-btn-label', 'pref-mask-label'].forEach(id => {
      const l = document.getElementById(id);
      if (l) l.textContent = isMasked() ? 'Afficher' : 'Masquer';
    });
  };
  document.getElementById('mask-btn')?.addEventListener('click', toggleMask);
  document.getElementById('pref-mask-btn')?.addEventListener('click', toggleMask);
  onMaskChange(majBoutonMasque);
  majBoutonMasque();

  // Periode de comparaison : un seul jeu de deltas sur toute la page, plutot
  // que variation et variation annuelle cote a cote sur chaque indicateur.
  const PERIODES = [
    { cle: 'periode', libelle: 'Période' },
    { cle: 'an',      libelle: '1 an' },
  ];
  const segPeriode = document.getElementById('seg-periode');
  _placerPeriode(segPeriode);
  if (segPeriode) {
    segPeriode.replaceChildren(...PERIODES.map(p => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'seg-btn';
      b.dataset.periode = p.cle;
      b.textContent = p.libelle;
      b.setAttribute('aria-pressed', String(p.cle === S.periodeComparaison));
      b.addEventListener('click', () => {
        S.periodeComparaison = p.cle;
        ecrireContexte();
        segPeriode.querySelectorAll('[data-periode]').forEach(o => {
          o.setAttribute('aria-pressed', String(o.dataset.periode === p.cle));
        });
        loadSynthese();
      });
      return b;
    }));
  }

  // Synthèse — évolution groupée
  document.getElementById('synthese-history-group').addEventListener('change', renderSyntheseHistory);

  // Flux buttons
  ['flux-filter-owner','flux-filter-type','flux-filter-category','flux-filter-year'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', () => {
      if (id === 'flux-filter-owner') {
        const val = el.value;
        S.syntheseOwner = val || 'Famille';
        ecrireContexte();
        const globalSel = document.getElementById('global-owner-filter');
        if (globalSel) globalSel.value = S.syntheseOwner;
      }
      persistFluxFilters();
      renderFlux();
    });
  });
  const btnClearFlux = document.getElementById('btn-clear-flux-filters');
  if (btnClearFlux) btnClearFlux.addEventListener('click', () => {
    clearFluxFilters();
    renderFlux();
  });

  // Targets
  wireTargetsEvents();

  // Entités
  document.getElementById('entity-form').addEventListener('submit', saveEntity);
  document.getElementById('entity-modal-overlay').addEventListener('click', () => closeModal('entity-modal'));
  ['ent-gross','ent-debt'].forEach(id =>
    document.getElementById(id).addEventListener('input', updateEntInfo)
  );

  // Import / Export / Reset
  document.getElementById('btn-import').addEventListener('click', importXlsx);
  document.getElementById('btn-import-json').addEventListener('click', importJson);
  document.getElementById('btn-export').addEventListener('click', exportJson);
  document.getElementById('btn-reset').addEventListener('click', resetDb);
  document.getElementById('btn-backup')?.addEventListener('click', createBackup);

  // Tri des tableaux
  ensurePositionsTableScaffold();
  wireSortableTable('positions-thead', 'positions', renderPositions);
  wireSortableTable('flux-thead',      'flux',      renderFlux);
  wireSortableTable('entities-thead',  'entities',  renderEntities);

  // Référentiel
  document.getElementById('btn-save-referential')?.addEventListener('click', saveReferential);
  initTemplateSelect();

  // Tools
  wireSimulation();
  document.getElementById('btn-auto-snapshot')?.addEventListener('click', triggerAutoSnapshot);
  document.getElementById('btn-refresh-prices')?.addEventListener('click', () => triggerPricesRefresh(false));
  document.getElementById('btn-refresh-prices-stale')?.addEventListener('click', () => triggerPricesRefresh(true));

  // Position form
  document.getElementById('position-form').addEventListener('submit', savePosition);
  ['pos-value','pos-debt','pos-ownership','pos-debt-pct','pos-mob-override-pct'].forEach(id =>
    document.getElementById(id).addEventListener('input', updatePosInfo)
  );
  document.getElementById('pos-mob-override-check').addEventListener('change', function() {
    document.getElementById('pos-mob-override-field').style.display = this.checked ? 'flex' : 'none';
    updatePosInfo();
  });
  ['pos-envelope','pos-category'].forEach(id =>
    document.getElementById(id).addEventListener('change', updatePosInfo)
  );
  document.getElementById('pos-entity-select').addEventListener('change', onEntitySelectChange);

  // Flux form
  document.getElementById('flux-form').addEventListener('submit', saveFlux);

  // Modal close buttons
  document.querySelectorAll('[data-close]').forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.dataset.close));
  });
  document.getElementById('position-modal-overlay').addEventListener('click', () => closeModal('position-modal'));
  document.getElementById('flux-modal-overlay').addEventListener('click', () => closeModal('flux-modal'));

  // Holdings + popover ISIN + advisor + actifs
  wireHoldingsEvents();
  wireFluxImport();
  wireIsinPopoverEvents();
  wireAdvisorEvents();
  wireActifsEvents();
  wireSettingsEvents();

  // Column pickers
  initColumnPicker('positions', 'positions-col-picker', 'positions-thead', {
    owner: 'Titulaire', establishment: 'Établissement', envelope: 'Enveloppe',
    category: 'Catégorie', gross_attributed: 'Valeur',
    debt_attributed: 'Dette', net_attributed: 'Net', gain_attributed: 'Plus-value',
    liquidity: 'Liquidité', mobilizable_value: 'Mobilisable',
  });
  initColumnPicker('actifs', 'actifs-col-picker', 'actifs-thead', {
    name: 'Nom', establishments: 'Établissement',
    asset_class: 'Classe', quantity: 'Qté',
    avg_cost: 'PRU', last_price: 'Cours', market_value: 'Valeur',
    pnl: '+/-', weight_pct: 'Poids',
  });

  // Focus traps on static modals
  ['position-modal', 'flux-modal', 'entity-modal', 'targets-modal', 'settings-modal', 'keyboard-help-modal']
    .forEach(id => trapModalFocus(id));
  // Les lignes de titres ont un brouillon : Echap demande avant de le perdre.
  trapModalFocus('holdings-modal', { onEscape: confirmCloseHoldings });

  // Body scroll-lock : observe toutes les modales statiques + popover ISIN
  installModalScrollLock();

  // Indicateur visuel de scroll horizontal sur les tables
  _installTableOverflowHints();

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    // Ignore shortcuts when typing in an input/textarea/select
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
      if (e.key === 'Escape') document.activeElement.blur();
      return;
    }

    // Escape — close any open modal or confirm dialog
    if (e.key === 'Escape') {
      const confirm = document.querySelector('.confirm-overlay');
      if (confirm) { confirm.querySelector('.confirm-cancel')?.click(); return; }
      const popover = document.getElementById('isin-popover');
      if (popover && !popover.classList.contains('hidden')) {
        closeIsinPopover(); return;
      }
      const snapDd = document.getElementById('snapshot-dropdown');
      if (snapDd && !snapDd.classList.contains('hidden')) {
        snapDd.classList.add('hidden');
        document.getElementById('snapshot-toggle')?.setAttribute('aria-expanded', 'false');
        return;
      }
      // Holdings : warning si brouillon dirty (intercepte Escape)
      const holdingsModal = document.getElementById('holdings-modal');
      if (holdingsModal && !holdingsModal.classList.contains('hidden')) {
        confirmCloseHoldings();
        return;
      }
      for (const id of ['keyboard-help-modal', 'position-modal', 'flux-modal', 'entity-modal', 'targets-modal']) {
        const m = document.getElementById(id);
        if (m && !m.classList.contains('hidden')) { closeModal(id); return; }
      }
    }

    // Ctrl+N / Cmd+N — new position
    if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
      e.preventDefault();
      if (S.currentTab !== 'positions') switchTab('positions');
      openPosModal();
    }

    // Shift+? — affiche la modale d'aide raccourcis
    if (e.key === '?') {
      e.preventDefault();
      openModal('keyboard-help-modal');
      return;
    }

    // / — ouvre la recherche
    if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      ouvrirRecherche();
      return;
    }

    // Fleches gauche/droite : arrete precedent / suivant. Seulement quand rien
    // n'a le focus : sur une zone defilante, un bouton, ou dans une fenetre,
    // la fleche a son sens propre et ne doit pas changer l'arrete.
    if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (e.target !== document.body || _surcoucheOuverte()) return;
      const selectId = S.currentTab === 'positions' ? 'positions-date-select' : 'synthese-date-select';
      const sel = document.getElementById(selectId);
      if (!sel || sel.options.length < 2) return;
      const idx = sel.selectedIndex;
      const next = e.key === 'ArrowLeft' ? idx + 1 : idx - 1; // left = older, right = newer
      if (next >= 0 && next < sel.options.length) {
        sel.selectedIndex = next;
        sel.dispatchEvent(new Event('change'));
      }
    }
  });
}

/** Une fenetre, un panneau lateral ou une surimpression est-il ouvert ? */
function _surcoucheOuverte() {
  if (document.querySelector('.confirm-overlay')) return true;
  const ouverts = ['.modal', '.drilldown', '.isin-popover', '#head-recherche-pop', '#snapshot-dropdown'];
  return ouverts.some(sel => [...document.querySelectorAll(sel)].some(el => !el.classList.contains('hidden')));
}

// ─── Dark mode ────────────────────────────────────────────────────────────

function _systemTheme() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function _resolveTheme(mode) {
  return mode === 'auto' ? _systemTheme() : mode;
}

function initTheme() {
  const saved = _lsGet('financy_theme') || 'auto';
  applyTheme(saved);

  // Follow system changes in auto mode
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if ((_lsGet('financy_theme') || 'auto') === 'auto') {
      applyTheme('auto');
    }
  });

  document.getElementById('theme-toggle')?.addEventListener('click', () => {
    const current = _lsGet('financy_theme') || 'auto';
    const next = current === 'auto' ? 'light' : current === 'light' ? 'dark' : 'auto';
    _lsSet('financy_theme', next);
    applyTheme(next);
  });

  // Ctrl/Cmd + M : bascule sans ouvrir le menu, pour couper court quand
  // quelqu'un arrive derriere l'ecran.
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'm') {
      const cible = e.target;
      const saisie = cible instanceof HTMLElement &&
        (cible.tagName === 'INPUT' || cible.tagName === 'TEXTAREA' || cible.isContentEditable);
      if (saisie) return;
      e.preventDefault();
      toggleMask();
    }
  });

  // Les montants sont figes dans le HTML deja rendu et dans les graphes
  // Chart.js : il faut redessiner l'onglet courant a chaque bascule. Les
  // donnees, elles, n'ont pas change : on redessine sans rien redemander
  // quand l'onglet sait le faire, sinon on recharge — une seule fois pour
  // une rafale de bascules.
  let attente = 0;
  onMaskChange(() => {
    if (_redessinerSansRecharger(S.currentTab || 'synthese')) return;
    clearTimeout(attente);
    attente = setTimeout(() => {
      _lastLoadedTab = null;
      switchTab(S.currentTab || 'synthese', { pushHistory: false });
    }, 150);
  });
}

/** Redessine l'onglet avec les donnees deja en main. Faux si l'onglet ne sait
 *  pas le faire (ou n'a rien en main) : il faut alors le recharger. */
function _redessinerSansRecharger(tab) {
  if (tab === 'synthese' && S.synthese) { renderSynthese({ cache: true }); return true; }
  if (tab === 'positions' && S.positions?.length) { renderPositions(); return true; }
  if (tab === 'flux' && S.flux?.length) { renderFlux(); return true; }
  if (tab === 'performance') { renderPerformance(); return true; }
  return false;
}

function applyTheme(mode) {
  document.documentElement.dataset.theme = _resolveTheme(mode);
  applyChartTheme();
  const btn = document.getElementById('theme-toggle');
  if (btn) {
    const label = mode === 'auto' ? 'Thème : auto (système)' : mode === 'dark' ? 'Thème : sombre' : 'Thème : clair';
    btn.textContent = label;
    btn.title = label;
    btn.setAttribute('aria-label', label);
    btn.dataset.themeMode = mode;
  }
  // Seules les couleurs changent : les graphes Chart.js se repeignent, sans
  // relancer les requetes de la synthese. Les courbes SVG suivent seules les
  // variables CSS.
  refreshChartsTheme();
}

// Apply immediately to prevent flash
(function() {
  const saved = _lsGet('financy_theme') || 'auto';
  document.documentElement.dataset.theme = _resolveTheme(saved);
})();

// ─── Boot ─────────────────────────────────────────────────────────────────

initTheme();
init().catch(err => console.error('Init error:', err));
