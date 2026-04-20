import { S } from './state.js';
import { fmtDate, treeFilter, treeExpandCollapse, treeToggleRow } from './utils.js';
import { api, buildSelects } from './api.js';
import { closeModal, trapModalFocus, installModalScrollLock } from './dialogs.js';
import { wireDrilldownEvents, drilldownHistory } from './drilldown.js';
import { wireTargetsEvents } from './targets.js';
import { loadUserAlertsAsync, saveUserAlerts } from './alerts.js';
import { loadTargets, saveTargets } from './targets.js';
import { wireSortableTable } from './utils.js';

import { loadSynthese, renderSynthese, renderSyntheseHistory, loadHistorique } from './tabs/synthese.js';
import { loadPositions, renderPositions, clearFilters, openPosModal, duplicateSnapshot,
         onEntitySelectChange, updatePosInfo, savePosition, startInlineEdit, deletePosition,
         persistPositionFilters, persistPositionsTreeState } from './tabs/positions.js';
import { openHoldingsModal, wireHoldingsEvents, confirmCloseHoldings } from './tabs/holdings.js';
import { wireIsinPopoverEvents } from './isin-popover.js';
import { loadAdvisor, wireAdvisorEvents } from './tabs/advisor.js';
import { loadActifs, wireActifsEvents } from './tabs/actifs.js';
import { loadFlux, renderFlux, openFluxModal, saveFlux, persistFluxFilters, clearFluxFilters } from './tabs/flux.js';
import { loadEntities, renderEntities, openEntityModal, saveEntity, updateEntInfo } from './tabs/entities.js';
import { importXlsx, importJson, exportJson, resetDb, initDemoToggle, createBackup } from './tabs/import-export.js';
import { loadReferential, saveReferential, initTemplateSelect } from './tabs/referentiel.js';
import { loadTimeline, wireSimulation, triggerAutoSnapshot, triggerPricesRefresh, loadSchedulerStatus } from './tabs/tools.js';
import { wireGlobalSearch } from './search.js';
import { wireSettingsEvents } from './settings.js';

// ─── Init ─────────────────────────────────────────────────────────────────

async function init() {
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
    owners.map(o => `<option value="${o}">${o}</option>`).join('');
  sel.value = S.syntheseOwner || 'Famille';
}

function _onGlobalOwnerChange(e) {
  S.syntheseOwner = e.target.value;
  // Sync person tabs in synthese
  const container = document.getElementById('synthese-person-tabs');
  if (container) {
    container.querySelectorAll('.person-tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.owner === S.syntheseOwner);
    });
  }
  // Sync actifs filter
  const actifsSel = document.getElementById('actifs-owner-filter');
  if (actifsSel) actifsSel.value = S.syntheseOwner === 'Famille' ? '' : S.syntheseOwner;
  // Reload current tab
  switchTab(S.currentTab, { pushHistory: false });
}

const VALID_TABS = new Set([
  'synthese', 'positions', 'actifs', 'flux', 'entites', 'conseil',
  'referentiel', 'tools', 'import',
]);

function _closeNavDrawer() {
  const navTabs = document.getElementById('nav-tabs');
  const navToggle = document.getElementById('navbar-toggle');
  if (navTabs?.classList.contains('is-open')) {
    navTabs.classList.remove('is-open');
    navToggle?.setAttribute('aria-expanded', 'false');
  }
}

// Ajoute/retire .has-overflow sur les .card-table selon leur scroll horizontal.
// Appele une fois au boot + a chaque resize + a chaque changement d'onglet.
function _installTableOverflowHints() {
  const update = () => {
    document.querySelectorAll('.card-table').forEach(el => {
      const overflows = el.scrollWidth > el.clientWidth + 2;
      el.classList.toggle('has-overflow', overflows);
    });
  };
  update();
  window.addEventListener('resize', update);
  // Mutation observer : re-check quand une table est rerender
  const obs = new MutationObserver(() => {
    requestAnimationFrame(update);
  });
  document.querySelectorAll('.card-table').forEach(el => {
    obs.observe(el, { childList: true, subtree: true });
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

export async function switchTab(tab, { pushHistory = true } = {}) {
  S.currentTab = tab;
  document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById(`tab-${tab}`).classList.remove('hidden');
  const mainBtn = document.querySelector(`.nav-tabs .tab-btn[data-tab="${tab}"]`);
  if (mainBtn) mainBtn.classList.add('active');

  if (pushHistory && location.pathname !== `/${tab}`) {
    history.pushState({ tab }, '', `/${tab}`);
  }

  const dd = document.getElementById('settings-dropdown');
  if (dd) dd.classList.add('hidden');

  const tabId = `tab-${tab}`;
  showLoading(tabId);
  try {
    if (tab === 'synthese')    await loadSynthese();
    if (tab === 'positions')   await loadPositions();
    if (tab === 'flux')        await loadFlux();
    if (tab === 'entites')     await loadEntities();
    if (tab === 'referentiel') await loadReferential();
    if (tab === 'actifs')      await loadActifs();
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
    btn.addEventListener('click', () => {
      _closeNavDrawer();
      switchTab(btn.dataset.tab);
    });
  });

  // Delegation globale : tout bouton avec data-tab-switch (CTA des empty states)
  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-tab-switch]');
    if (!btn) return;
    e.preventDefault();
    switchTab(btn.dataset.tabSwitch);
  });

  // Navbar hamburger mobile
  const navToggle = document.getElementById('navbar-toggle');
  const navTabs = document.getElementById('nav-tabs');
  if (navToggle && navTabs) {
    navToggle.addEventListener('click', e => {
      e.stopPropagation();
      const open = navTabs.classList.toggle('is-open');
      navToggle.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', e => {
      if (!navTabs.classList.contains('is-open')) return;
      if (e.target.closest('#nav-tabs') || e.target.closest('#navbar-toggle')) return;
      _closeNavDrawer();
    });
  }

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
    showLoading('tab-synthese');
    try { await loadSynthese(); } finally { hideLoading('tab-synthese'); }
  });
  document.getElementById('positions-date-select').addEventListener('change', async e => {
    S.positionsDate = e.target.value;
    showLoading('tab-positions');
    try { await loadPositions(); } finally { hideLoading('tab-positions'); }
  });

  // Positions buttons
  document.getElementById('btn-add-position').addEventListener('click', () => openPosModal());
  document.getElementById('btn-duplicate').addEventListener('click', duplicateSnapshot);
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

  // Synthèse — évolution groupée
  document.getElementById('synthese-history-group').addEventListener('change', renderSyntheseHistory);

  // Flux buttons
  document.getElementById('btn-add-flux').addEventListener('click', () => openFluxModal());
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
  document.getElementById('btn-add-entity').addEventListener('click', () => openEntityModal());
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
  wireIsinPopoverEvents();
  wireAdvisorEvents();
  wireActifsEvents();
  wireSettingsEvents();

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
      // Settings dropdown + eventuel drawer navbar mobile
      const settingsDd = document.getElementById('settings-dropdown');
      if (settingsDd && !settingsDd.classList.contains('hidden')) {
        settingsDd.classList.add('hidden'); return;
      }
      const navTabs = document.querySelector('.nav-tabs.is-open');
      if (navTabs) {
        navTabs.classList.remove('is-open');
        document.getElementById('navbar-toggle')?.setAttribute('aria-expanded', 'false');
        return;
      }
      // Holdings : warning si brouillon dirty (intercepte Escape)
      const holdingsModal = document.getElementById('holdings-modal');
      if (holdingsModal && !holdingsModal.classList.contains('hidden')) {
        confirmCloseHoldings();
        return;
      }
      for (const id of ['position-modal', 'flux-modal', 'entity-modal', 'targets-modal']) {
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
}

function applyTheme(mode) {
  document.documentElement.dataset.theme = _resolveTheme(mode);
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = mode === 'auto' ? '\u25D0' : mode === 'dark' ? '\u2600' : '\u263E';
  if (btn) btn.title = mode === 'auto' ? 'Thème : auto (système)' : mode === 'dark' ? 'Thème : sombre' : 'Thème : clair';
  if (S.currentTab === 'synthese' && S.synthese) renderSynthese();
}

// Apply immediately to prevent flash
(function() {
  const saved = localStorage.getItem('financy_theme') || 'auto';
  document.documentElement.dataset.theme = _resolveTheme(saved);
})();

// ─── Boot ─────────────────────────────────────────────────────────────────

initTheme();
init().catch(err => console.error('Init error:', err));
