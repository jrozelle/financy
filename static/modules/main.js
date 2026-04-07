import { S } from './state.js';
import { fmtDate, treeFilter, treeExpandCollapse, treeToggleRow } from './utils.js';
import { api, buildSelects } from './api.js';
import { closeModal } from './dialogs.js';
import { wireDrilldownEvents } from './drilldown.js';
import { wireTargetsEvents } from './targets.js';
import { loadUserAlertsAsync, saveUserAlerts } from './alerts.js';
import { loadTargets, saveTargets } from './targets.js';
import { wireSortableTable } from './utils.js';

import { loadSynthese, renderSynthese, renderSyntheseHistory, loadHistorique } from './tabs/synthese.js';
import { loadPositions, renderPositions, clearFilters, openPosModal, duplicateSnapshot,
         onEntitySelectChange, updatePosInfo, savePosition, startInlineEdit, deletePosition } from './tabs/positions.js';
import { loadFlux, renderFlux, openFluxModal, saveFlux } from './tabs/flux.js';
import { loadEntities, renderEntities, openEntityModal, saveEntity, updateEntInfo } from './tabs/entities.js';
import { importXlsx, importJson, exportJson, resetDb } from './tabs/import-export.js';
import { loadReferential, saveReferential, resetReferential } from './tabs/referentiel.js';

// ─── Init ─────────────────────────────────────────────────────────────────

async function init() {
  S.config = await api('GET', '/api/config');
  buildSelects();
  wireEvents();
  wireDrilldownEvents();
  await Promise.all([refreshDates(), loadEntities(), loadHistorique(), loadTargets(), loadUserAlertsAsync()]);
  await migrateLocalStorageToDB();
  await switchTab('synthese');
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

// ─── Tabs ─────────────────────────────────────────────────────────────────

export async function switchTab(tab) {
  S.currentTab = tab;
  document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById(`tab-${tab}`).classList.remove('hidden');
  const mainBtn = document.querySelector(`.nav-tabs .tab-btn[data-tab="${tab}"]`);
  if (mainBtn) mainBtn.classList.add('active');

  const dd = document.getElementById('settings-dropdown');
  if (dd) dd.classList.add('hidden');

  if (tab === 'synthese')    await loadSynthese();
  if (tab === 'positions')   await loadPositions();
  if (tab === 'flux')        await loadFlux();
  if (tab === 'entites')     await loadEntities();
  if (tab === 'referentiel') await loadReferential();
}

// ─── Events ───────────────────────────────────────────────────────────────

function wireEvents() {
  // Tabs
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Date selects
  document.getElementById('synthese-date-select').addEventListener('change', e => {
    S.syntheseDate = e.target.value;
    loadSynthese();
  });
  document.getElementById('positions-date-select').addEventListener('change', e => {
    S.positionsDate = e.target.value;
    loadPositions();
  });

  // Positions buttons
  document.getElementById('btn-add-position').addEventListener('click', () => openPosModal());
  document.getElementById('btn-duplicate').addEventListener('click', duplicateSnapshot);
  document.getElementById('filter-owner').addEventListener('change', renderPositions);
  document.getElementById('filter-envelope').addEventListener('change', renderPositions);
  document.getElementById('filter-establishment').addEventListener('change', renderPositions);
  document.getElementById('btn-clear-filters').addEventListener('click', clearFilters);

  // Tree delegation
  document.getElementById('positions-tree-wrap').addEventListener('click', ev => {
    const btn = ev.target.closest('[data-action]');
    if (btn) {
      const id = parseInt(btn.dataset.id);
      if (btn.dataset.action === 'edit-pos') openPosModal(id);
      if (btn.dataset.action === 'del-pos')  deletePosition(id);
      if (btn.dataset.action === 'add-pos-ctx') {
        openPosModal(null, {
          owner:         btn.dataset.owner         || undefined,
          establishment: btn.dataset.establishment || undefined,
          envelope:      btn.dataset.envelope      || undefined,
          entity:        btn.dataset.entity        || undefined,
        });
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

  // Positions tree search
  document.getElementById('pos-tree-search').addEventListener('input', e => treeFilter('positions-tree-body', e.target.value));

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
      switchTab(item.dataset.tab);
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
  ['flux-filter-owner','flux-filter-type','flux-filter-year'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', renderFlux);
  });
  const btnClearFlux = document.getElementById('btn-clear-flux-filters');
  if (btnClearFlux) btnClearFlux.addEventListener('click', () => {
    ['flux-filter-owner','flux-filter-type','flux-filter-year'].forEach(id => {
      document.getElementById(id).value = '';
    });
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

  // Tri des tableaux
  wireSortableTable('positions-thead', 'positions', renderPositions);
  wireSortableTable('flux-thead',      'flux',      renderFlux);
  wireSortableTable('entities-thead',  'entities',  renderEntities);

  // Référentiel
  document.getElementById('btn-save-referential')?.addEventListener('click', saveReferential);
  document.getElementById('btn-reset-referential')?.addEventListener('click', resetReferential);

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
}

// ─── Dark mode ────────────────────────────────────────────────────────────

function initTheme() {
  const saved = localStorage.getItem('financy_theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const theme = saved || (prefersDark ? 'dark' : 'light');
  applyTheme(theme);

  document.getElementById('theme-toggle')?.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    localStorage.setItem('financy_theme', next);
  });
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = theme === 'dark' ? '\u2600' : '\u263E';
  if (S.currentTab === 'synthese' && S.synthese) renderSynthese();
}

// Apply immediately to prevent flash
(function() {
  const saved = localStorage.getItem('financy_theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.dataset.theme = saved || (prefersDark ? 'dark' : 'light');
})();

// ─── Boot ─────────────────────────────────────────────────────────────────

initTheme();
init().catch(err => console.error('Init error:', err));
