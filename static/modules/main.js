import { S } from './state.js';
import { initMask, toggleMask, isMasked, onMaskChange } from './mask.js';
import { wireTodo } from './todo.js';
import { wireReglages, estUnReglage, ouvrir as ouvrirReglages } from './reglages.js';
import { fmtDate, treeFilter, treeExpandCollapse, treeToggleRow, esc } from './utils.js';
import { api, buildSelects } from './api.js';
import { closeModal, trapModalFocus, installModalScrollLock } from './dialogs.js';
import { wireDrilldownEvents, drilldownHistory } from './drilldown.js';
import { wireTargetsEvents } from './targets.js';
import { loadUserAlertsAsync, saveUserAlerts } from './alerts.js';
import { loadTargets, saveTargets } from './targets.js';
import { wireSortableTable } from './utils.js';

import { loadSynthese, renderSynthese, renderSyntheseHistory, loadHistorique } from './tabs/synthese.js';
import { loadPositions, renderPositions, clearFilters, openPosModal, duplicateSnapshot, renameSnapshot, deleteSnapshot,
         onEntitySelectChange, updatePosInfo, savePosition, startInlineEdit, deletePosition,
         persistPositionFilters, persistPositionsTreeState, ensurePositionsTableScaffold } from './tabs/positions.js';
import { openHoldingsModal, wireHoldingsEvents, confirmCloseHoldings } from './tabs/holdings.js';
import { wireIsinPopoverEvents } from './isin-popover.js';
import { loadAdvisor, wireAdvisorEvents } from './tabs/advisor.js';
import { loadActifs, wireActifsEvents } from './tabs/actifs.js';
import { loadFlux, renderFlux, openFluxModal, saveFlux, persistFluxFilters, clearFluxFilters, wireFluxImport } from './tabs/flux.js';
import { loadEntities, renderEntities, openEntityModal, saveEntity, updateEntInfo } from './tabs/entities.js';
import { importXlsx, importJson, exportJson, resetDb, initDemoToggle, createBackup, updateDemoBadge } from './tabs/import-export.js';
import { loadReferential, saveReferential, initTemplateSelect } from './tabs/referentiel.js';
import { loadTimeline, wireSimulation, triggerAutoSnapshot, triggerPricesRefresh, loadSchedulerStatus } from './tabs/tools.js';
import { loadPerformance } from './tabs/performance.js';
import { wireGlobalSearch } from './search.js';
import { wireSettingsEvents } from './settings.js';
import { initColumnPicker, reapplyColumns } from './column-picker.js';

// ─── Init ─────────────────────────────────────────────────────────────────

async function init() {
  initMask();
  wireTodo(switchTab);   // la zone « À traiter » renvoie vers l'onglet concerne
  wireReglages(chargerEcranReglage);
  S.config = await api('GET', '/api/config');
  buildSelects();
  _buildGlobalOwnerFilter();
  wireEvents();
  wireDrilldownEvents();
  wireGlobalSearch(switchTab);
  await Promise.all([refreshDates(), loadEntities(), loadHistorique(), loadTargets(), loadUserAlertsAsync()]);
  await migrateLocalStorageToDB();
  await switchTab(_tabFromUrl() || 'synthese', { pushHistory: false });
  initDemoToggle();
}

export async function reloadAll() {
  S.config = await api('GET', '/api/config');
  buildSelects();
  await Promise.all([refreshDates(), loadEntities(), loadHistorique(), loadTargets(), loadUserAlertsAsync()]);
  await switchTab(S.currentTab || 'synthese');
}

async function migrateLocalStorageToDB() {
  const lsTargets = localStorage.getItem('patrimoine_targets');
  if (lsTargets) {
    try {
      const parsed = JSON.parse(lsTargets);
      if (Object.keys(parsed).length > 0) await saveTargets(parsed);
    } catch {}
  }
  const lsAlerts = localStorage.getItem('patrimoine_alerts');
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
  // Sync actifs filter
  const actifsSel = document.getElementById('actifs-owner-filter');
  if (actifsSel) actifsSel.value = S.syntheseOwner === 'Famille' ? '' : S.syntheseOwner;
  // Force reload current tab
  _lastLoadedTab = null;
  switchTab(S.currentTab, { pushHistory: false });
}

const VALID_TABS = new Set([
  'synthese', 'positions', 'actifs', 'flux', 'entites', 'performance', 'conseil',
  'referentiel', 'tools', 'import',
]);

function _normalizeLegacyLayout() {
  const menu = document.getElementById('settings-dropdown');
  const ownerFilter = document.querySelector('.nav-owner-filter');
  let dateFilter = document.querySelector('.nav-date-filter');
  const syntheseDate = document.getElementById('synthese-date-select');

  if (ownerFilter) {
    let btn = document.getElementById('nav-add-button');
    if (!btn) {
      btn = document.createElement('button');
      btn.id = 'nav-add-button';
    }
    btn.type = 'button';
    btn.className = 'nav-icon-btn hidden';
    btn.title = 'Ajouter';
    btn.setAttribute('aria-label', 'Ajouter');
    btn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 5v14M5 12h14"></path></svg>`;
    ownerFilter.prepend(btn);
  } else if (!document.getElementById('nav-add-button')) {
    const navActions = document.querySelector('.nav-actions');
    const btn = document.createElement('button');
    btn.id = 'nav-add-button';
    btn.type = 'button';
    btn.className = 'nav-icon-btn hidden';
    btn.title = 'Ajouter';
    btn.setAttribute('aria-label', 'Ajouter');
    btn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 5v14M5 12h14"></path></svg>`;
    navActions?.insertBefore(btn, navActions.firstChild);
  }

  if (ownerFilter && syntheseDate) {
    if (!dateFilter) {
      dateFilter = document.createElement('div');
      dateFilter.className = 'nav-date-filter';
      ownerFilter.after(dateFilter);
    }
    if (!dateFilter.contains(syntheseDate)) dateFilter.appendChild(syntheseDate);
    syntheseDate.setAttribute('aria-label', 'Date du snapshot');
    syntheseDate.closest('.date-selector')?.querySelector('label')?.remove();
  }

  // Old templates can remain cached by the running app process. Moving these
  // controls here keeps refreshed static JS/CSS compatible with that HTML.
  if (menu) {
    const ensureMenuButton = (id, html, attrs = {}) => {
      let btn = document.getElementById(id);
      if (!btn) {
        btn = document.createElement('button');
        btn.id = id;
      }
      btn.type = 'button';
      btn.className = 'settings-item';
      btn.innerHTML = html;
      btn.removeAttribute('onclick');
      for (const [name, value] of Object.entries(attrs)) btn.setAttribute(name, value);
      return btn;
    };
    const section = label => {
      const el = document.createElement('div');
      el.className = 'settings-section-label';
      el.textContent = label;
      return el;
    };

    const logout = menu.querySelector('a[href="/logout"]') || document.querySelector('a.logout-link[href="/logout"]');

    // Deux menus, deux natures. L'engrenage ne contient QUE ce qui se regle et
    // reste vrai d'un ecran a l'autre. Ce qui AGIT — dupliquer un arrete, le
    // supprimer, rafraichir des cours — part dans un menu d'actions accole au
    // selecteur de date, puisque ces operations portent sur l'arrete qu'il
    // designe. Melanger les deux obligeait a relire tout le menu pour trouver
    // un reglage, et faisait cotoyer « Thème » et « Supprimer ce snapshot ».
    const reglages = [
      section('Affichage'),
      ensureMenuButton('theme-toggle', 'Thème'),
      section('Colonnes'),
      ensureMenuButton('positions-col-picker', 'Colonnes des positions'),
      ensureMenuButton('actifs-col-picker', 'Colonnes des actifs'),
      section('Application'),
      ensureMenuButton('btn-open-settings', 'Clés API'),
      ensureMenuButton('btn-keyboard-help', 'Raccourcis clavier'),
    ];
    if (logout) {
      logout.className = 'settings-item settings-item-danger';
      logout.textContent = 'Déconnexion';
      reglages.push(section('Compte'), logout);
    }
    menu.replaceChildren(...reglages);

    const actions = document.getElementById('snapshot-dropdown');
    if (actions) {
      actions.replaceChildren(
        section('Cet arrêté'),
        ensureMenuButton('btn-add-snapshot-note', 'Note de l\u2019arrêté'),
        ensureMenuButton('btn-duplicate', 'Dupliquer'),
        ensureMenuButton('btn-rename-snapshot', 'Modifier la date'),
        ensureMenuButton('btn-delete-snapshot', 'Supprimer', { 'data-danger': '1' }),
        section('Données'),
        ensureMenuButton('actifs-refresh-prices', 'Rafraîchir les cours'),
        ensureMenuButton('btn-open-wealth-target', 'Objectif de patrimoine'),
        ensureMenuButton('btn-print', 'Imprimer la synthèse'),
      );
      actions.querySelector('[data-danger]')?.classList.add('settings-item-danger');
    }
  }

  const positionsDate = document.getElementById('positions-date-select');
  if (positionsDate) {
    positionsDate.classList.add('hidden');
    positionsDate.setAttribute('aria-hidden', 'true');
    positionsDate.setAttribute('tabindex', '-1');
    positionsDate.closest('#tab-positions .date-selector')?.classList.add('hidden');
  }

  const positionsOwner = document.getElementById('filter-owner');
  if (positionsOwner) {
    positionsOwner.classList.add('hidden');
    positionsOwner.setAttribute('aria-hidden', 'true');
    positionsOwner.setAttribute('tabindex', '-1');
  }

  const positionsTab = document.getElementById('tab-positions');
  const positionsHeader = positionsTab?.querySelector(':scope > .page-header');
  const positionsFilters = document.getElementById('positions-filters');
  if (positionsTab && positionsHeader && positionsFilters && !positionsTab.querySelector(':scope > .positions-toolbar')) {
    const toolbar = document.createElement('div');
    toolbar.className = 'page-toolbar positions-toolbar';
    positionsTab.insertBefore(toolbar, positionsHeader);
    toolbar.append(positionsHeader, positionsFilters);
  }
  document.querySelectorAll('#tab-positions #btn-add-position').forEach(el => el.remove());

  const fluxOwner = document.getElementById('flux-filter-owner');
  if (fluxOwner) {
    fluxOwner.classList.add('hidden');
    fluxOwner.setAttribute('aria-hidden', 'true');
    fluxOwner.setAttribute('tabindex', '-1');
  }
  const fluxTab = document.getElementById('tab-flux');
  const fluxHeader = fluxTab?.querySelector(':scope > .page-header');
  const fluxFilters = fluxTab?.querySelector(':scope > .filters-bar, :scope > #flux-filters');
  if (fluxTab && fluxHeader && fluxFilters && !fluxTab.querySelector(':scope > .page-toolbar')) {
    const toolbar = document.createElement('div');
    toolbar.className = 'page-toolbar';
    fluxTab.insertBefore(toolbar, fluxHeader);
    toolbar.append(fluxHeader, fluxFilters);
  }
  document.querySelectorAll('#tab-flux #btn-add-flux, #tab-entites #btn-add-entity').forEach(el => el.remove());

  document.getElementById('synthese-person-tabs')?.remove();
  document.querySelectorAll('#tab-synthese .analyse-person-tabs').forEach(el => el.remove());
  document.querySelector('#tab-actifs .page-filters')?.classList.add('hidden');
}

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
  return VALID_TABS.has(path) ? path : null;
}

let _lastLoadedTab = null;

function _updateNavAddButton(tab) {
  const btn = document.getElementById('nav-add-button');
  if (!btn) return;
  const labels = {
    positions: 'Ajouter une position',
    flux: 'Ajouter un flux',
    entites: 'Ajouter une entité',
  };
  const enabled = tab in labels;
  btn.classList.toggle('hidden', !enabled);
  btn.title = labels[tab] || 'Ajouter';
  btn.setAttribute('aria-label', btn.title);
}


const LABELS_ONGLET = {
  synthese: 'Synthèse', positions: 'Positions', actifs: 'Actifs', entites: 'Entités',
  performance: 'Performance', flux: 'Flux', conseil: 'Conseil',
  referentiel: 'Référentiel', import: 'Import / Export', tools: 'Outils',
};



/** Titre de la page courante, affiche dans la barre du haut.
 *  Le sous-titre rappelle l'arrete consulte : sur une application patrimoniale,
 *  « quelles donnees je regarde » est aussi important que « ou je suis ». */
function majTitrePage(tab) {
  const h = document.getElementById('page-title');
  const p = document.getElementById('page-sub');
  if (!h) return;
  const TITRES = {
    synthese: 'Synthèse du patrimoine', positions: 'Positions',
    actifs: 'Actifs détenus', entites: 'Entités', performance: 'Performance',
    flux: 'Flux et versements', conseil: 'Conseil patrimonial',
    referentiel: 'Référentiel', import: 'Import / Export', tools: 'Outils',
  };
  h.textContent = TITRES[tab] || 'Financy';
  if (!p) return;
  const d = S.syntheseDate || S.positionsDate || S.dates?.[0];
  const qui = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : 'Famille';
  const nb = Object.keys(S.synthese?.totals_by_owner || {}).length;
  const bouts = [];
  if (d) bouts.push(`Arrêté du ${fmtDate(d)}`);
  bouts.push(qui);
  // Le nombre de titulaires qualifie une vue famille ; sous un filtre nominatif
  // il annoncait « Paul · 4 titulaires », c'est-a-dire le contraire du filtre.
  if (qui === 'Famille' && nb > 1) bouts.push(`${nb} titulaires`);
  p.textContent = bouts.join(' · ');
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
    history.pushState({ tab }, '', `/${tab}`);
  }

  const dd = document.getElementById('settings-dropdown');
  if (dd) dd.classList.add('hidden');
  updateDemoBadge();
  _updateNavAddButton(tab);

  const tabId = `tab-${tab}`;
  // Eviter de recharger l'onglet si on y est deja et qu'on ne force pas
  if (tab === _lastLoadedTab && pushHistory) {
    return;
  }
  _lastLoadedTab = tab;
  showLoading(tabId);
  try {
    if (tab === 'synthese')    await loadSynthese();
    if (tab === 'positions')   await loadPositions();
    if (tab === 'flux')        await loadFlux();
    if (tab === 'entites')     await loadEntities();
    if (tab === 'referentiel') await loadReferential();
    if (tab === 'actifs')      await loadActifs();
    if (tab === 'performance') await loadPerformance();
    if (tab === 'conseil')     await loadAdvisor();
    if (tab === 'tools')       { await loadTimeline(); loadSchedulerStatus(); }
  } finally {
    hideLoading(tabId);
  }
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
    document.getElementById('keyboard-help-modal')?.classList.remove('hidden');
  });

  document.getElementById('btn-print')?.addEventListener('click', () => window.print());

  // Global owner filter
  document.getElementById('global-owner-filter')?.addEventListener('change', _onGlobalOwnerChange);

  // Browser back/forward
  window.addEventListener('popstate', e => {
    const tab = e.state?.tab || _tabFromUrl() || 'synthese';
    switchTab(tab, { pushHistory: false });
  });

  // Date selects (with spinner)
  document.getElementById('synthese-date-select').addEventListener('change', async e => {
    S.syntheseDate = e.target.value;
    S.positionsDate = e.target.value;
    const positionsSelect = document.getElementById('positions-date-select');
    if (positionsSelect) positionsSelect.value = e.target.value;
    if (S.currentTab === 'positions') {
      showLoading('tab-positions');
      try { await loadPositions(); } finally { hideLoading('tab-positions'); }
    } else if (S.currentTab === 'actifs') {
      showLoading('tab-actifs');
      try { await loadActifs(); } finally { hideLoading('tab-actifs'); }
    } else {
      showLoading('tab-synthese');
      try { await loadSynthese(); } finally { hideLoading('tab-synthese'); }
    }
  });
  document.getElementById('positions-date-select').addEventListener('change', async e => {
    S.positionsDate = e.target.value;
    S.syntheseDate = e.target.value;
    const syntheseSelect = document.getElementById('synthese-date-select');
    if (syntheseSelect) syntheseSelect.value = e.target.value;
    showLoading('tab-positions');
    try { await loadPositions(); } finally { hideLoading('tab-positions'); }
  });

  // Positions buttons
  document.getElementById('nav-add-button')?.addEventListener('click', () => {
    if (S.currentTab === 'positions') openPosModal();
    if (S.currentTab === 'flux') openFluxModal();
    if (S.currentTab === 'entites') openEntityModal();
  });
  document.getElementById('btn-add-position')?.addEventListener('click', () => openPosModal());
  document.getElementById('btn-duplicate').addEventListener('click', duplicateSnapshot);
  document.getElementById('btn-rename-snapshot')?.addEventListener('click', renameSnapshot);
  document.getElementById('btn-delete-snapshot')?.addEventListener('click', deleteSnapshot);
  document.getElementById('filter-owner').addEventListener('change', () => {
    const val = document.getElementById('filter-owner').value;
    S.syntheseOwner = val || 'Famille';
    persistPositionFilters();
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
        const f = { owner: btn.dataset.owner };
        if (btn.dataset.establishment) f.establishment = btn.dataset.establishment;
        if (btn.dataset.entity) f.entity = btn.dataset.entity;
        const label = btn.dataset.establishment || btn.dataset.entity || '';
        drilldownHistory({ subtitle: 'Évolution établissement', title: label, filters: f });
      }
      return;
    }
    const amt = ev.target.closest('.tree-inline-amount');
    if (amt) startInlineEdit(amt);
  });

  // Snapshot date
  document.getElementById('pos-snapshot-check').addEventListener('change', e => {
    document.getElementById('pos-snapshot-date').style.visibility = e.target.checked ? '' : 'hidden';
  });

  // Positions tree search (debounced)
  let _treeSearchTimer = null;
  document.getElementById('pos-tree-search').addEventListener('input', e => {
    clearTimeout(_treeSearchTimer);
    _treeSearchTimer = setTimeout(() => treeFilter('positions-tree-body', e.target.value), 150);
  });

  // Positions tree depth bar
  const depthBar = document.querySelector('.tree-depth-bar');
  if (depthBar) depthBar.addEventListener('click', e => {
    const btn = e.target.closest('.tree-depth-btn');
    if (!btn) return;
    const depth = btn.dataset.depth;
    const cid = 'positions-tree-body';
    const container = document.getElementById(cid);
    if (!container) return;

    depthBar.querySelectorAll('.tree-depth-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    treeExpandCollapse(cid, false);
    const levels = ['tree-owner', 'tree-etabl', 'tree-env'];
    const depthIndex = { owner: 0, etabl: 1, env: 2, all: 3 }[depth] ?? 3;
    for (let i = 0; i < Math.min(depthIndex, levels.length); i++) {
      treeExpandCollapse(cid, true, levels[i]);
    }
    if (depthIndex >= levels.length) {
      treeExpandCollapse(cid, true);
    }
    persistPositionsTreeState();
  });

  // Settings gear menu
  const settingsToggle = document.getElementById('settings-toggle');
  const settingsDropdown = document.getElementById('settings-dropdown');
  if (settingsToggle && settingsDropdown) {
    settingsToggle.addEventListener('click', e => {
      e.stopPropagation();
      settingsDropdown.classList.toggle('hidden');
    });
    settingsDropdown.addEventListener('click', e => {
      const item = e.target.closest('.settings-item');
      if (!item) return;
      settingsDropdown.classList.add('hidden');
      if (item.dataset.tab) switchTab(item.dataset.tab);
    });
    document.addEventListener('click', e => {
      if (!e.target.closest('#settings-menu')) {
        settingsDropdown.classList.add('hidden');
      }
    });
  }

  // Menu d'actions sur l'arrete courant. Meme mecanique que l'engrenage, mais
  // les deux ne peuvent pas rester ouverts ensemble : ouvrir l'un ferme l'autre.
  const snapToggle = document.getElementById('snapshot-toggle');
  const snapDropdown = document.getElementById('snapshot-dropdown');
  if (snapToggle && snapDropdown) {
    snapToggle.addEventListener('click', e => {
      e.stopPropagation();
      settingsDropdown?.classList.add('hidden');
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
    settingsToggle?.addEventListener('click', () => {
      snapDropdown.classList.add('hidden');
      snapToggle.setAttribute('aria-expanded', 'false');
    });
  }

  // ── Répartition des outils ──────────────────────────────────────────
  // Les noeuds sont DEPLACES, pas recrees : ils gardent leurs identifiants et
  // leurs ecouteurs, donc tout le code qui les cible continue de fonctionner
  // sans rien savoir de ce reamenagement. Fait en JS et non dans le gabarit
  // parce que ces blocs contiennent des elements auto-fermants qu'un decoupage
  // textuel du gabarit tronquait.
  const deplacer = (quoi, ou) => {
    const n = document.querySelector(quoi), h = document.getElementById(ou);
    if (n && h) h.appendChild(n);
  };
  deplacer('.nav-owner-filter', 'head-filtres');   // titulaire + bouton ajouter
  deplacer('.nav-date-filter', 'head-filtres');    // arrete + menu d'actions
  deplacer('.global-search', 'rail-recherche');    // la recherche est globale
  deplacer('#settings-menu', 'rail-reglages');     // les reglages aussi
  // Videe de tout, la barre du haut n'a plus lieu d'etre.

  // ── Barre du bas : le bouton « Plus » deplie le rail entier ─────────
  // Sur telephone le rail ne montre que cinq destinations ; les sous-entrees,
  // la recherche et les reglages vivent derriere ce bouton. C'est le meme
  // element qui change de geometrie, donc rien a recabler.
  const rail = document.getElementById('fin-rail');
  const plus = document.getElementById('rail-plus');
  const replierRail = () => {
    rail?.classList.remove('is-open');
    document.body.classList.remove('rail-ouvert');
    plus?.setAttribute('aria-expanded', 'false');
  };
  plus?.addEventListener('click', () => {
    const ouvert = rail.classList.toggle('is-open');
    document.body.classList.toggle('rail-ouvert', ouvert);
    plus.setAttribute('aria-expanded', String(ouvert));
  });
  // Choisir une destination referme la feuille ; le bouton lui-meme la bascule.
  rail?.addEventListener('click', e => {
    if (e.target.closest('#rail-plus')) return;
    if (e.target.closest('.tab-btn, #ouvrir-reglages, [data-tab-switch]')) replierRail();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && rail?.classList.contains('is-open')) replierRail();
  });

  // L'en-tete figé ne prend son filet qu'une fois decolle du haut : souligner
  // un en-tete au repos ajoute un trait qui ne separe rien.
  const tete = document.querySelector('.page-head');
  if (tete && 'IntersectionObserver' in window) {
    const sentinelle = document.createElement('div');
    sentinelle.style.cssText = 'position:absolute;top:0;height:1px;width:1px';
    tete.parentNode.insertBefore(sentinelle, tete);
    new IntersectionObserver(
      ([e]) => tete.classList.toggle('is-stuck', !e.isIntersecting),
      { threshold: 0 }
    ).observe(sentinelle);
  }

  // ── Contrôles de l'en-tête ──────────────────────────────────────────
  // Densite : segment visible plutot qu'entree de menu. Tout l'espacement
  // derive d'une variable unique, donc rien ne se desaligne.
  const DENSITES = [
    { cle: 'confortable', valeur: '1',   libelle: 'Densité : confortable' },
    { cle: 'compacte',    valeur: '.78', libelle: 'Densité : compacte' },
  ];
  const appliquerDensite = cle => {
    const d = DENSITES.find(x => x.cle === cle) || DENSITES[0];
    document.documentElement.style.setProperty('--d', d.valeur);
    document.querySelectorAll('[data-den]').forEach(b => {
      b.setAttribute('aria-pressed', String(b.dataset.den === d.cle));
    });
    try { localStorage.setItem('financy_density', d.cle); } catch { /* session privee */ }
  };
  let densite = 'confortable';
  try { densite = localStorage.getItem('financy_density') || 'confortable'; } catch { /* idem */ }
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
  document.getElementById('btn-add-flux')?.addEventListener('click', () => openFluxModal());
  ['flux-filter-owner','flux-filter-type','flux-filter-category','flux-filter-year'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', () => {
      if (id === 'flux-filter-owner') {
        const val = el.value;
        S.syntheseOwner = val || 'Famille';
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
  document.getElementById('btn-add-entity')?.addEventListener('click', () => openEntityModal());
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
    document.getElementById('pos-mob-override-field').style.display = this.checked ? '' : 'none';
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
    owner: 'Proprietaire', establishment: 'Etablissement', envelope: 'Enveloppe',
    category: 'Categorie', gross_attributed: 'Actif attribue',
    debt_attributed: 'Dette', net_attributed: 'Net attribue',
    liquidity: 'Liquidite', mobilizable_value: 'Mobilisable',
  });
  initColumnPicker('actifs', 'actifs-col-picker', 'actifs-thead', {
    isin: 'ISIN', name: 'Nom', establishments: 'Etablissement',
    asset_class: 'Classe', quantity: 'Qty',
    avg_cost: 'PRU', last_price: 'Cours', market_value: 'Valo',
    pnl: '+/-', weight_pct: 'Poids', envelopes: 'Enveloppes',
  });

  // Focus traps on static modals
  ['position-modal', 'flux-modal', 'entity-modal', 'targets-modal', 'holdings-modal', 'settings-modal'].forEach(trapModalFocus);

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
        popover.classList.add('hidden'); return;
      }
      const settingsDd = document.getElementById('settings-dropdown');
      if (settingsDd && !settingsDd.classList.contains('hidden')) {
        settingsDd.classList.add('hidden'); return;
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
      document.getElementById('keyboard-help-modal')?.classList.remove('hidden');
      return;
    }

    // / — focus global search
    if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      document.getElementById('global-search-input')?.focus();
      return;
    }

    // Arrow Left/Right — navigate between snapshots
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
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

// ─── Dark mode ────────────────────────────────────────────────────────────

function _systemTheme() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function _resolveTheme(mode) {
  return mode === 'auto' ? _systemTheme() : mode;
}

function initTheme() {
  const saved = localStorage.getItem('financy_theme') || 'auto';
  applyTheme(saved);

  // Follow system changes in auto mode
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if ((localStorage.getItem('financy_theme') || 'auto') === 'auto') {
      applyTheme('auto');
    }
  });

  document.getElementById('theme-toggle')?.addEventListener('click', () => {
    const current = localStorage.getItem('financy_theme') || 'auto';
    const next = current === 'auto' ? 'light' : current === 'light' ? 'dark' : 'auto';
    localStorage.setItem('financy_theme', next);
    applyTheme(next);
  });

  document.getElementById('mask-toggle')?.addEventListener('click', toggleMask);

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
  // Chart.js : il faut redessiner l'onglet courant a chaque bascule.
  onMaskChange(() => {
    const btn = document.getElementById('mask-toggle');
    if (btn) btn.textContent = isMasked() ? 'Afficher les montants' : 'Masquer les montants';
    switchTab(S.currentTab || 'synthese', { pushHistory: false });
  });
}

function applyTheme(mode) {
  document.documentElement.dataset.theme = _resolveTheme(mode);
  const btn = document.getElementById('theme-toggle');
  if (btn) {
    const label = mode === 'auto' ? 'Thème : auto (système)' : mode === 'dark' ? 'Thème : sombre' : 'Thème : clair';
    if (btn.classList.contains('settings-item') || btn.closest('#settings-dropdown')) {
      btn.textContent = label;
    }
    btn.title = label;
    btn.setAttribute('aria-label', label);
    btn.dataset.themeMode = mode;
  }
  if (S.currentTab === 'synthese' && S.synthese) renderSynthese();
}

// Apply immediately to prevent flash
(function() {
  const saved = localStorage.getItem('financy_theme') || 'auto';
  document.documentElement.dataset.theme = _resolveTheme(saved);
})();

// ─── Boot ─────────────────────────────────────────────────────────────────

_normalizeLegacyLayout();
initTheme();
init().catch(err => console.error('Init error:', err));
