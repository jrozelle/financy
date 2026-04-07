'use strict';

// ─── State ────────────────────────────────────────────────────────────────

const S = {
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
  positionsView:   localStorage.getItem('financy_positionsView') || 'table',   // 'table' | 'tree'
  currentTab:      'synthese',
  editPosId:       null,
  editFluxId:      null,
  editEntityId:    null,
  sort: {
    positions: { key: null, dir: 1 },
    flux:      { key: null, dir: 1 },
    entities:  { key: null, dir: 1 },
  },
};

let catChart          = null;
let histChart         = null;
let syntheseEnvChart  = null;
let syntheseHistChart = null;

// ─── Utilities ────────────────────────────────────────────────────────────

const fmt = (n, dec = 0) => {
  if (n == null) return '—';
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  }).format(n) + '\u202f€';
};

const fmtDate = d => {
  if (!d) return '—';
  const [y, m, day] = d.split('-');
  return `${day}/${m}/${y}`;
};

const liqBadge = liq => {
  const map = {
    'J0\u2013J1':  'badge-j01',
    'J2\u2013J7':  'badge-j27',
    'J8\u2013J30': 'badge-j830',
    '30J+':        'badge-30',
    'Bloqu\u00e9': 'badge-blk',
  };
  return `<span class="badge ${map[liq] || 'badge-blk'}">${liq || '—'}</span>`;
};

const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

const fmtDelta = (n, dec = 0) => {
  if (n == null || n === 0) return '';
  const sign = n > 0 ? '+' : '';
  return sign + new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  }).format(n) + '\u202f\u20ac';
};

function kpiDelta(variation, deltaKey, pctKey = null, { invert = false } = {}) {
  if (!variation) return '';
  const delta = variation[deltaKey];
  if (delta == null || delta === 0) return '';
  const positive = invert ? delta < 0 : delta > 0;
  const cls = positive ? 'kpi-delta-pos' : 'kpi-delta-neg';
  const arrow = delta > 0 ? '\u25b2' : '\u25bc';
  let pctStr = '';
  if (pctKey && variation[pctKey] != null) {
    const pct = variation[pctKey];
    pctStr = ` (${pct > 0 ? '+' : ''}${pct.toFixed(1)}\u202f%)`;
  }
  return `<div class="${cls}">${arrow} ${fmtDelta(delta)}${pctStr}</div>`;
}

// ─── Confirm dialog ──────────────────────────────────────────────────────

function confirmDialog(title, message, { confirmText = 'Supprimer', danger = true } = {}) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = `
      <div class="confirm-dialog">
        <h3>${esc(title)}</h3>
        <p>${message}</p>
        <div class="confirm-actions">
          <button class="btn btn-secondary confirm-cancel">Annuler</button>
          <button class="btn ${danger ? 'btn-danger' : 'btn-primary'} confirm-ok">${esc(confirmText)}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    const cleanup = (result) => { overlay.remove(); resolve(result); };
    overlay.querySelector('.confirm-cancel').addEventListener('click', () => cleanup(false));
    overlay.querySelector('.confirm-ok').addEventListener('click',     () => cleanup(true));
    overlay.addEventListener('click', e => { if (e.target === overlay) cleanup(false); });
    // Focus le bouton annuler pour éviter les suppressions accidentelles
    overlay.querySelector('.confirm-cancel').focus();
  });
}

// ─── Toast ────────────────────────────────────────────────────────────────

function toast(msg, type = 'success', duration = 2500) {
  const container = document.getElementById('toast');
  const el = document.createElement('div');
  el.className = `toast-msg toast-${type}`;
  el.textContent = msg;
  container.appendChild(el);
  requestAnimationFrame(() => {
    requestAnimationFrame(() => el.classList.add('toast-show'));
  });
  setTimeout(() => {
    el.classList.remove('toast-show');
    el.addEventListener('transitionend', () => el.remove(), { once: true });
  }, duration);
}

// ─── Tri de tableaux ──────────────────────────────────────────────────────

function sortArr(arr, key, dir) {
  if (!key) return arr;
  return [...arr].sort((a, b) => {
    const va = a[key] ?? '';
    const vb = b[key] ?? '';
    if (typeof va === 'number' && typeof vb === 'number') return dir * (va - vb);
    return dir * String(va).localeCompare(String(vb), 'fr', { sensitivity: 'base' });
  });
}

// Branche les <th data-sort> d'un thead sur le tri.
// stateKey : 'positions' | 'flux' | 'entities'
// rerenderFn : appelé sans argument après mise à jour de S.sort
function wireSortableTable(theadId, stateKey, rerenderFn) {
  const thead = document.getElementById(theadId);
  if (!thead) return;
  thead.querySelectorAll('th[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      const st  = S.sort[stateKey];
      if (st.key === key) {
        st.dir = -st.dir;
      } else {
        st.key = key;
        st.dir = 1;
      }
      rerenderFn();
    });
  });
}

// Met à jour les classes CSS des <th> après un rendu
function updateSortIndicators(theadId, stateKey) {
  const thead = document.getElementById(theadId);
  if (!thead) return;
  const { key, dir } = S.sort[stateKey];
  thead.querySelectorAll('th[data-sort]').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.sort === key) th.classList.add(dir === 1 ? 'sort-asc' : 'sort-desc');
  });
}

// ─── API ──────────────────────────────────────────────────────────────────

async function api(method, path, body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

// ─── Init ─────────────────────────────────────────────────────────────────

async function init() {
  S.config = await api('GET', '/api/config');
  buildSelects();
  wireEvents();
  wireDrilldownEvents();
  // Précharger targets et alertes depuis la DB
  await Promise.all([refreshDates(), loadEntities(), loadHistorique(), loadTargets(), loadUserAlertsAsync()]);
  // Migration automatique : si localStorage a des données et pas la DB, pousser vers la DB
  await migrateLocalStorageToDB();
  await switchTab('synthese');
}

async function migrateLocalStorageToDB() {
  // Targets
  const lsTargets = localStorage.getItem('patrimoine_targets');
  if (lsTargets && (!_targetsCache || Object.keys(_targetsCache).length === 0)) {
    try {
      const parsed = JSON.parse(lsTargets);
      if (Object.keys(parsed).length > 0) await saveTargets(parsed);
    } catch {}
  }
  // Alerts
  const lsAlerts = localStorage.getItem('patrimoine_alerts');
  if (lsAlerts && (!_alertsCache || _alertsCache.length === 0)) {
    try {
      const parsed = JSON.parse(lsAlerts);
      if (parsed.length > 0) await saveUserAlerts(parsed);
    } catch {}
  }
}

function buildSelects() {
  const { owners, categories, envelopes, flux_types, entity_types, valuation_modes } = S.config;
  fill('pos-owner',    owners);
  fill('pos-category', categories);
  fill('pos-envelope', ['', ...envelopes]);
  fill('flux-owner',   owners);
  fill('flux-envelope',['', ...envelopes]);
  fill('flux-type',    flux_types);
  fill('ent-type',      ['', ...entity_types]);
  fill('ent-valuation', ['', ...valuation_modes]);
}

function refreshEntitySelect() {
  const names = S.entities.map(e => e.name);
  fill('pos-entity-select', ['', ...names]);
}

function fill(id, opts) {
  document.getElementById(id).innerHTML =
    opts.map(o => `<option value="${esc(o)}">${esc(o) || '—'}</option>`).join('');
}

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

  // Délégation clics boutons arbre positions (une seule fois ici, pas dans le renderer)
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
    // Édition inline : clic sur le montant
    const amt = ev.target.closest('.tree-inline-amount');
    if (amt) startInlineEdit(amt);
  });

  // Snapshot date : visible seulement si checkbox cochée
  document.getElementById('pos-snapshot-check').addEventListener('change', e => {
    document.getElementById('pos-snapshot-date').style.visibility = e.target.checked ? '' : 'hidden';
  });

  // Positions tree search
  document.getElementById('pos-tree-search').addEventListener('input', e => treeFilter('positions-tree-body', e.target.value));

  // Positions tree depth bar (expand/collapse)
  const depthBar = document.querySelector('.tree-depth-bar');
  if (depthBar) depthBar.addEventListener('click', e => {
    const btn = e.target.closest('.tree-depth-btn');
    if (!btn) return;
    const depth = btn.dataset.depth;
    const cid = 'positions-tree-body';
    const container = document.getElementById(cid);
    if (!container) return;

    // Update active state
    depthBar.querySelectorAll('.tree-depth-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    // Collapse everything first, then expand to the requested depth
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

// ─── Dates ────────────────────────────────────────────────────────────────

async function refreshDates() {
  S.dates = await api('GET', '/api/dates');
  renderDateSelects();
}

function renderDateSelects() {
  const opts = S.dates.length
    ? S.dates.map(d => `<option value="${d}">${fmtDate(d)}</option>`).join('')
    : '<option value="">Aucune date</option>';

  document.getElementById('synthese-date-select').innerHTML  = opts;
  document.getElementById('positions-date-select').innerHTML = opts;

  if (S.dates.length) {
    if (!S.syntheseDate  || !S.dates.includes(S.syntheseDate))  S.syntheseDate  = S.dates[0];
    if (!S.positionsDate || !S.dates.includes(S.positionsDate)) S.positionsDate = S.dates[0];
    document.getElementById('synthese-date-select').value  = S.syntheseDate;
    document.getElementById('positions-date-select').value = S.positionsDate;
  }
}

// ─── Tabs ─────────────────────────────────────────────────────────────────

async function switchTab(tab) {
  S.currentTab = tab;
  document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById(`tab-${tab}`).classList.remove('hidden');
  const mainBtn = document.querySelector(`.nav-tabs .tab-btn[data-tab="${tab}"]`);
  if (mainBtn) mainBtn.classList.add('active');

  // Close settings dropdown when switching tabs
  const dd = document.getElementById('settings-dropdown');
  if (dd) dd.classList.add('hidden');

  if (tab === 'synthese')    await loadSynthese();
  if (tab === 'positions')   await loadPositions();
  if (tab === 'flux')        await loadFlux();
  if (tab === 'entites')     await loadEntities();
  if (tab === 'referentiel') await loadReferential();
}

// ─── Synthèse ─────────────────────────────────────────────────────────────

async function loadSynthese() {
  if (!S.syntheseDate && S.dates.length) S.syntheseDate = S.dates[0];
  if (!S.syntheseDate) return;
  const [syn, positions] = await Promise.all([
    api('GET', `/api/synthese?date=${S.syntheseDate}`),
    api('GET', `/api/positions?date=${S.syntheseDate}`),
  ]);
  // Cache des positions par owner pour les filtres de liquidité
  syn._positions_cache = {};
  for (const o of S.config.owners) {
    syn._positions_cache[o] = positions.filter(p => p.owner === o);
  }
  S.synthese = syn;
  renderSynthesePersonTabs();
  renderSynthese();
}

function renderSynthesePersonTabs() {
  const container = document.getElementById('synthese-person-tabs');
  container.innerHTML = ['Famille', ...S.config.owners].map(o => `
    <button class="person-tab-btn ${S.syntheseOwner === o ? 'active' : ''}"
            data-owner="${esc(o)}">${esc(o)}</button>
  `).join('');
  container.querySelectorAll('.person-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      S.syntheseOwner = btn.dataset.owner;
      renderSynthesePersonTabs();
      renderSynthese();
    });
  });
}

function renderSynthese() {
  const syn = S.synthese;
  if (!syn?.date) {
    ['kpi-net','kpi-gross','kpi-debt','kpi-mobilizable'].forEach(id => {
      document.getElementById(id).textContent = '—';
    });
    return;
  }

  const { family, totals_by_owner, totals_by_category, mobilizable_by_liquidity } = syn;
  const owner = S.syntheseOwner;
  const isFamily = (owner === 'Famille');

  // KPI : famille ou personne
  const kpi = isFamily
    ? { gross: family.gross, debt: family.debt, net: family.net,
        mob: Object.values(totals_by_owner).reduce((s, o) => s + o.mobilizable, 0) }
    : { gross: totals_by_owner[owner]?.gross      || 0,
        debt:  totals_by_owner[owner]?.debt       || 0,
        net:   totals_by_owner[owner]?.net        || 0,
        mob:   totals_by_owner[owner]?.mobilizable|| 0 };

  document.getElementById('kpi-net').innerHTML         = fmt(kpi.net) + kpiDelta(syn.variation, 'net_delta', 'net_pct');
  document.getElementById('kpi-gross').innerHTML       = fmt(kpi.gross) + kpiDelta(syn.variation, 'gross_delta');
  document.getElementById('kpi-debt').innerHTML        = fmt(kpi.debt) + kpiDelta(syn.variation, 'debt_delta', null, { invert: true });
  document.getElementById('kpi-mobilizable').innerHTML = fmt(kpi.mob) + kpiDelta(syn.variation, 'mob_delta');

  // Adapter les libellés KPI selon le filtre personne
  document.getElementById('kpi-net-label').textContent   = isFamily ? 'Patrimoine net famille' : `Patrimoine net — ${owner}`;
  document.getElementById('kpi-gross-label').textContent = isFamily ? 'Actifs bruts' : `Actifs bruts — ${owner}`;
  document.getElementById('kpi-debt-label').textContent  = isFamily ? 'Dettes' : `Dettes — ${owner}`;
  document.getElementById('kpi-mob-label').textContent   = isFamily ? 'Mobilisable' : `Mobilisable — ${owner}`;

  // Catégories filtrées par personne
  const catFiltered = isFamily
    ? totals_by_category
    : Object.fromEntries(
        Object.entries(totals_by_category).map(([cat, v]) => [
          cat, { net: v.by_owner?.[owner] || 0, by_owner: v.by_owner }
        ]).filter(([, v]) => v.net > 0)
      );

  // Liquidité filtrée par personne
  const liqFiltered = isFamily
    ? mobilizable_by_liquidity
    : (() => {
        // On recalcule depuis les positions déjà dans S.positions (chargées à la même date)
        // Si pas encore chargées, fallback famille
        const pos = S.synthese._positions_cache?.[owner];
        if (!pos) return mobilizable_by_liquidity; // fallback
        const byLiq = {};
        for (const p of pos) byLiq[p.liquidity] = (byLiq[p.liquidity] || 0) + (p.mobilizable_value || 0);
        return byLiq;
      })();

  renderEntityWarnings(syn.entity_warnings || []);
  renderOwnersTable(totals_by_owner, family, Object.values(totals_by_owner).reduce((s,o)=>s+o.mobilizable,0));
  renderCatChart(catFiltered);
  renderEnvChart(syn._positions_cache, owner);
  renderHistChart(owner);
  renderSyntheseHistory();
  renderLiqBars(liqFiltered);
  renderEntitiesSynthese();
  renderAllocationTargets();
  renderPerf();
}

function renderOwnersTable(byOwner, family, totalMob) {
  const activeOwner = S.syntheseOwner;
  const familyNet = family.net || 0;
  const rows = S.config.owners.map(o => {
    const t = byOwner[o] || { gross: 0, debt: 0, net: 0, mobilizable: 0 };
    const pct = familyNet !== 0 ? ((t.net / familyNet) * 100).toFixed(1) : '—';
    const highlight = (activeOwner !== 'Famille' && activeOwner === o)
      ? ' style="background:var(--primary-light);font-weight:700"' : '';
    return `<tr class="clickable" data-dd-owner="${esc(o)}"${highlight}>
      <td>${esc(o)}</td>
      <td>${fmt(t.gross)}</td>
      <td class="${t.debt > 0 ? 'neg' : ''}">${t.debt > 0 ? fmt(t.debt) : '—'}</td>
      <td class="${t.net < 0 ? 'neg' : 'pos'}">${fmt(t.net)}</td>
      <td style="text-align:right;font-size:12px;color:var(--text-muted)">${pct !== '—' ? pct + '\u202f%' : '—'}</td>
      <td>${fmt(t.mobilizable)}</td>
    </tr>`;
  }).join('');

  document.getElementById('owners-table').innerHTML = `
    <table class="owners-table">
      <thead><tr>
        <th>Personne</th><th>Actifs</th><th>Dettes</th><th>Net</th><th>% du total</th><th>Mobilisable</th>
      </tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr class="total-row clickable" data-dd-owner="Famille">
        <td>TOTAL FAMILLE</td>
        <td>${fmt(family.gross)}</td>
        <td class="${family.debt > 0 ? 'neg' : ''}">${family.debt > 0 ? fmt(family.debt) : '—'}</td>
        <td class="${family.net < 0 ? 'neg' : 'pos'}">${fmt(family.net)}</td>
        <td style="text-align:right;font-size:12px;color:var(--text-muted)">100\u202f%</td>
        <td>${fmt(totalMob)}</td>
      </tr></tfoot>
    </table>`;

  // Wire owner clicks
  document.getElementById('owners-table').querySelectorAll('[data-dd-owner]').forEach(tr => {
    tr.addEventListener('click', () => {
      const owner = tr.dataset.ddOwner;
      api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
        const filtered = owner === 'Famille' ? positions : positions.filter(p => p.owner === owner);
        drilldownPositions(filtered, owner, 'Patrimoine net');
      });
    });
  });
}

const COLORS = [
  '#2563eb','#7c3aed','#db2777','#dc2626','#ea580c',
  '#d97706','#65a30d','#16a34a','#0891b2','#0284c7','#4f46e5',
];

function renderCatChart(byCat) {
  const cats = Object.keys(byCat).filter(c => byCat[c].net > 0);
  const vals = cats.map(c => byCat[c].net);

  if (catChart) catChart.destroy();
  const ctx = document.getElementById('category-chart').getContext('2d');
  catChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: cats,
      datasets: [{
        data: vals,
        backgroundColor: COLORS.slice(0, cats.length),
        borderWidth: 2,
        borderColor: '#fff',
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      onClick: (_, elements) => {
        if (!elements.length) return;
        const cat = cats[elements[0].index];
        api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
          drilldownPositions(positions.filter(p => p.category === cat), cat, 'Catégorie');
        });
      },
      plugins: {
        legend: {
          position: 'right',
          labels: { font: { size: 11 }, padding: 10, boxWidth: 12 },
          onClick: (e, item, legend) => {
            const cat = cats[item.index];
            api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
              drilldownPositions(positions.filter(p => p.category === cat), cat, 'Catégorie');
            });
          },
        },
        tooltip: {
          callbacks: {
            label: ctx => {
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const pct = ((ctx.parsed / total) * 100).toFixed(1);
              return ` ${new Intl.NumberFormat('fr-FR').format(Math.round(ctx.parsed))}\u202f€  (${pct}%)`;
            },
            afterLabel: () => 'Cliquer pour détailler',
          },
        },
      },
    },
  });
}

function renderEnvChart(posCache, owner) {
  const positions = owner === 'Famille'
    ? Object.values(posCache || {}).flat()
    : (posCache?.[owner] || []);

  const byEnv = {};
  for (const p of positions) {
    const k = p.envelope || 'Autre';
    byEnv[k] = (byEnv[k] || 0) + (p.net_attributed || 0);
  }
  const labels = Object.keys(byEnv).filter(k => byEnv[k] > 0);
  const vals   = labels.map(k => byEnv[k]);

  if (syntheseEnvChart) syntheseEnvChart.destroy();
  const ctx = document.getElementById('synthese-env-chart').getContext('2d');
  syntheseEnvChart = new Chart(ctx, doughnutConfig(labels, vals));
}

async function renderSyntheseHistory() {
  const card = document.getElementById('synthese-history-detail-card');
  if (!card) return;
  if (S.historique.length < 2) { card.style.display = 'none'; return; }
  card.style.display = '';

  const groupBy = document.getElementById('synthese-history-group').value;
  const owner   = S.syntheseOwner === 'Famille' ? null : S.syntheseOwner;
  const url     = `/api/historique?group_by=${groupBy}${owner ? `&owner=${encodeURIComponent(owner)}` : ''}`;

  const history = await api('GET', url);
  const dates   = history.map(h => fmtDate(h.date));

  const groups = new Set();
  history.forEach(h => Object.keys(h.by_group || {}).forEach(k => groups.add(k)));
  const groupList = [...groups].sort();

  const datasets = groupList.map((g, i) => ({
    label: g,
    data:  history.map(h => Math.round(h.by_group?.[g] || 0)),
    backgroundColor: COLORS[i % COLORS.length] + 'cc',
    borderColor:     COLORS[i % COLORS.length],
    borderWidth: 1.5,
    fill: true,
  }));

  if (syntheseHistChart) syntheseHistChart.destroy();
  syntheseHistChart = new Chart(
    document.getElementById('synthese-history-detail-chart').getContext('2d'),
    {
      type: 'bar',
      data: { labels: dates, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true, ticks: { font: { size: 11 } } },
          y: { stacked: true, ticks: {
            font: { size: 11 },
            callback: v => new Intl.NumberFormat('fr-FR', { notation: 'compact' }).format(v) + '\u202f€'
          }},
        },
        plugins: {
          legend: { position: 'bottom', labels: { font: { size: 11 }, padding: 8, boxWidth: 12 } },
          tooltip: { callbacks: {
            label: ctx => ` ${ctx.dataset.label} : ${new Intl.NumberFormat('fr-FR').format(ctx.raw)}\u202f€`,
          }},
        },
      },
    }
  );
}

async function loadHistorique() {
  S.historique = await api('GET', '/api/historique');
  if (S.currentTab === 'synthese') renderHistChart();
}

function renderHistChart(filterOwner = 'Famille') {
  if (!S.historique.length) return;
  const labels = S.historique.map(h => fmtDate(h.date));

  let datasets;
  if (filterOwner === 'Famille') {
    // Vue famille : courbe famille en gras + toutes les personnes
    const famData = S.historique.map(h => h.family_net);
    const ownerSets = S.config.owners.map((o, i) => ({
      label: o,
      data: S.historique.map(h => h.by_owner[o] || 0),
      borderColor: COLORS[i],
      backgroundColor: COLORS[i] + '18',
      tension: .35, borderWidth: 2, pointRadius: 4, fill: false,
    }));
    datasets = [
      { label: 'Famille', data: famData, borderColor: '#111827',
        backgroundColor: 'rgba(17,24,39,.06)', tension: .35,
        borderWidth: 3, pointRadius: 5, fill: true },
      ...ownerSets,
    ];
  } else {
    // Vue personne : une seule courbe
    const i = S.config.owners.indexOf(filterOwner);
    datasets = [{
      label: filterOwner,
      data: S.historique.map(h => h.by_owner[filterOwner] || 0),
      borderColor: COLORS[i] || '#2563eb',
      backgroundColor: (COLORS[i] || '#2563eb') + '18',
      tension: .35, borderWidth: 3, pointRadius: 5, fill: true,
    }];
  }

  if (histChart) histChart.destroy();
  const ctx = document.getElementById('history-chart').getContext('2d');
  histChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { font: { size: 11 }, boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: ctx =>
              ` ${ctx.dataset.label} : ${new Intl.NumberFormat('fr-FR').format(Math.round(ctx.parsed.y))}\u202f€`,
          },
        },
      },
      scales: {
        y: {
          ticks: {
            callback: v =>
              new Intl.NumberFormat('fr-FR', { notation: 'compact' }).format(v) + '\u202f€',
          },
        },
      },
    },
  });
}

function renderEntityWarnings(warnings) {
  const bar = document.getElementById('entity-warnings-bar');
  const entityHtml = warnings.map(w => {
    const msg = w.type === 'debt'
      ? `⚠ <strong>${esc(w.entity)}</strong> : total % dette = ${w.total_pct}% — double-comptage sur la dette`
      : `⚠ <strong>${esc(w.entity)}</strong> : total % détention = ${w.total_pct}% — double-comptage probable`;
    return `<div class="alert alert-error" style="margin-bottom:.5rem">${msg}</div>`;
  }).join('');

  // Alertes configurables
  const alertHtml = evalUserAlerts();

  bar.innerHTML = entityHtml + alertHtml;
}

function evalUserAlerts() {
  const alerts = loadUserAlerts();
  if (!alerts.length || !S.synthese) return '';
  const syn   = S.synthese;
  const owner = S.syntheseOwner;
  const isFamily = owner === 'Famille';

  const family = syn.family || {};
  const byOwner = syn.totals_by_owner || {};
  const byCat   = syn.totals_by_category || {};

  const net   = isFamily ? (family.net   || 0) : (byOwner[owner]?.net   || 0);
  const gross = isFamily ? (family.gross || 0) : (byOwner[owner]?.gross || 0);

  return alerts.map(a => {
    let actual = null;
    if (a.metric === 'cat_pct' && a.category) {
      const catNet = byCat[a.category]?.net || 0;
      actual = net > 0 ? (catNet / net) * 100 : 0;
    } else if (a.metric === 'cat_abs' && a.category) {
      actual = byCat[a.category]?.net || 0;
    } else if (a.metric === 'net')   actual = net;
    else if (a.metric === 'gross')   actual = gross;

    if (actual === null) return '';
    const triggered = a.op === '<' ? actual < a.threshold : actual > a.threshold;
    if (!triggered) return '';

    const fmtActual = a.metric.endsWith('pct') ? actual.toFixed(1) + ' %' : fmt(actual);
    const fmtThresh = a.metric.endsWith('pct') ? a.threshold + ' %' : fmt(a.threshold);
    return `<div class="alert alert-warning" style="margin-bottom:.5rem">
      ⚡ <strong>${esc(a.label || a.category || a.metric)}</strong> : ${fmtActual} ${a.op === '<' ? '&lt;' : '&gt;'} seuil ${fmtThresh}
    </div>`;
  }).join('');
}

// ─── Alertes (DB-backed) ─────────────────────────────────────────────────

let _alertsCache = null;

async function loadUserAlertsAsync() {
  if (_alertsCache !== null) return _alertsCache;
  try {
    _alertsCache = await api('GET', '/api/alerts');
    if (!Array.isArray(_alertsCache)) _alertsCache = [];
  } catch {
    try { _alertsCache = JSON.parse(localStorage.getItem('patrimoine_alerts')) || []; } catch { _alertsCache = []; }
  }
  return _alertsCache;
}

function loadUserAlerts() {
  // Retour synchrone du cache (chargé à l'init)
  return _alertsCache || [];
}

async function saveUserAlerts(a) {
  _alertsCache = a;
  try {
    await api('PUT', '/api/alerts', a);
    localStorage.removeItem('patrimoine_alerts');
  } catch {
    localStorage.setItem('patrimoine_alerts', JSON.stringify(a));
  }
}

function renderEntitiesSynthese() {
  const card = document.getElementById('entities-synthese-card');
  if (!S.entities.length) { card.style.display = 'none'; return; }
  card.style.display = '';

  const owner    = S.syntheseOwner;
  const isFamily = owner === 'Famille';
  const cache    = S.synthese?._positions_cache || {};

  // Toutes les positions liées aux entités, tous owners confondus
  const allPositions = Object.values(cache).flat();

  // Pour chaque entité : quote-part famille et quote-part personne sélectionnée
  const rows = S.entities.map(e => {
    const linked = allPositions.filter(p => p.entity === e.name);

    const familyNet  = linked.reduce((s, p) => s + (p.net_attributed || 0), 0);
    const familyGross= linked.reduce((s, p) => s + (p.gross_attributed || 0), 0);
    const familyDebt = linked.reduce((s, p) => s + (p.debt_attributed || 0), 0);
    const familyPct  = e.gross_assets > 0 ? (familyGross / e.gross_assets * 100).toFixed(0) : '—';

    const ownerNet   = !isFamily
      ? linked.filter(p => p.owner === owner).reduce((s, p) => s + (p.net_attributed || 0), 0)
      : null;
    const ownerPct   = !isFamily && e.gross_assets > 0
      ? linked.filter(p => p.owner === owner).reduce((s, p) => s + (p.ownership_pct || 0), 0)
      : null;

    return { e, familyGross, familyDebt, familyNet, familyPct, ownerNet, ownerPct };
  });

  const personCol = !isFamily
    ? `<th style="text-align:right">${esc(owner)}</th>` : '';

  document.getElementById('entities-synthese').innerHTML = `
    <table class="owners-table">
      <thead><tr>
        <th>Entité</th>
        <th>Type</th>
        <th style="text-align:right">Actif brut total</th>
        <th style="text-align:right">Dette totale</th>
        <th style="text-align:right">Net total</th>
        <th style="text-align:right">Quote-part famille</th>
        ${personCol}
      </tr></thead>
      <tbody>${rows.map(({ e, familyGross, familyDebt, familyNet, familyPct, ownerNet, ownerPct }) => `
        <tr>
          <td><strong>${esc(e.name)}</strong></td>
          <td>${esc(e.type || '—')}</td>
          <td style="text-align:right">${fmt(e.gross_assets)}</td>
          <td style="text-align:right" class="${e.debt > 0 ? 'neg' : ''}">${e.debt > 0 ? fmt(e.debt) : '—'}</td>
          <td style="text-align:right;font-weight:600">${fmt(e.net_assets)}</td>
          <td style="text-align:right">
            ${fmt(familyNet)}
            <span style="font-size:11px;color:var(--text-muted);margin-left:4px">${familyPct !== '—' ? familyPct + '%' : ''}</span>
          </td>
          ${!isFamily ? `<td style="text-align:right;font-weight:700;color:var(--primary)">
            ${fmt(ownerNet)}
            ${ownerPct !== null ? `<span style="font-size:11px;color:var(--text-muted);margin-left:4px">${(ownerPct*100).toFixed(0)}%</span>` : ''}
          </td>` : ''}
        </tr>`).join('')}
      </tbody>
    </table>`;
}

function renderLiqBars(byLiq) {
  const total = Object.values(byLiq).reduce((s, v) => s + v, 0);
  const rows = S.config.liquidity_order.map(liq => {
    const val = byLiq[liq] || 0;
    const pct = total > 0 ? (val / total) * 100 : 0;
    return `<div class="liq-row">
      <div>${liqBadge(liq)}</div>
      <div class="liq-bar-bg"><div class="liq-bar" style="width:${pct.toFixed(1)}%"></div></div>
      <div class="liq-value">${fmt(val)}</div>
    </div>`;
  }).join('');
  document.getElementById('liquidity-bars').innerHTML = `<div class="liq-grid">${rows}</div>`;
}

// ─── Positions ────────────────────────────────────────────────────────────

async function loadPositions() {
  if (!S.positionsDate && S.dates.length) S.positionsDate = S.dates[0];
  if (!S.positionsDate) {
    renderPositionsEmpty('Aucune donnée. Importez votre fichier Excel ou ajoutez une position.');
    return;
  }
  S.positions = await api('GET', `/api/positions?date=${S.positionsDate}`);
  populateFilters();
  renderPositions();
}

function populateFilters() {
  const owners    = [...new Set(S.positions.map(p => p.owner))].sort();
  const envelopes = [...new Set(S.positions.map(p => p.envelope).filter(Boolean))].sort();
  const estabs    = [...new Set(S.positions.map(p => p.establishment).filter(Boolean))].sort();

  const cur = {
    owner:         document.getElementById('filter-owner').value,
    envelope:      document.getElementById('filter-envelope').value,
    establishment: document.getElementById('filter-establishment').value,
  };

  fillFilter('filter-owner',         'Toutes les personnes',       owners);
  fillFilter('filter-envelope',      'Toutes les enveloppes',      envelopes);
  fillFilter('filter-establishment', 'Tous les établissements',    estabs);

  // Restore selection if still valid
  if (cur.owner    && owners.includes(cur.owner))    document.getElementById('filter-owner').value = cur.owner;
  if (cur.envelope && envelopes.includes(cur.envelope)) document.getElementById('filter-envelope').value = cur.envelope;
  if (cur.establishment && estabs.includes(cur.establishment)) document.getElementById('filter-establishment').value = cur.establishment;
}

function fillFilter(id, placeholder, options) {
  document.getElementById(id).innerHTML =
    `<option value="">${placeholder}</option>` +
    options.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('');
}

function clearFilters() {
  document.getElementById('filter-owner').value         = '';
  document.getElementById('filter-envelope').value      = '';
  document.getElementById('filter-establishment').value = '';
  renderPositions();
}

function filteredPositions() {
  const owner  = document.getElementById('filter-owner').value;
  const env    = document.getElementById('filter-envelope').value;
  const estab  = document.getElementById('filter-establishment').value;
  return S.positions.filter(p =>
    (!owner  || p.owner         === owner) &&
    (!env    || p.envelope      === env)   &&
    (!estab  || p.establishment === estab)
  );
}

function renderPositionsEmpty(msg) {
  document.getElementById('positions-tbody').innerHTML =
    `<tr class="empty-row"><td colspan="10">${esc(msg)}</td></tr>`;
  document.getElementById('positions-tfoot').innerHTML = '';
}

function renderPosViewToggle() {
  const existing = document.getElementById('pos-view-toggle');
  if (existing) {
    // Mettre à jour l'état actif sans recréer
    existing.querySelectorAll('.view-toggle-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.view === S.positionsView);
    });
    return;
  }
  const toggle = document.createElement('div');
  toggle.id = 'pos-view-toggle';
  toggle.className = 'analyse-view-toggle';
  toggle.style.marginLeft = '.5rem';
  toggle.innerHTML = `
    <button class="view-toggle-btn ${S.positionsView === 'table' ? 'active' : ''}" data-view="table">&#9776; Tableau</button>
    <button class="view-toggle-btn ${S.positionsView === 'tree'  ? 'active' : ''}" data-view="tree">&#9638; Arborescence</button>`;
  toggle.addEventListener('click', e => {
    const btn = e.target.closest('.view-toggle-btn');
    if (!btn) return;
    S.positionsView = btn.dataset.view;
    localStorage.setItem('financy_positionsView', S.positionsView);
    renderPositions();
  });
  // Insérer dans la barre d'actions, après le bouton dupliquer
  const headerActions = document.querySelector('#tab-positions .header-actions');
  if (headerActions) headerActions.insertBefore(toggle, headerActions.firstChild);
}

function startInlineEdit(span) {
  if (span.querySelector('input')) return; // déjà en cours
  const posId  = parseInt(span.dataset.id);
  const curVal = parseFloat(span.dataset.val) || 0;
  const pos    = S.positions.find(p => p.id === posId);
  if (!pos) return;

  const input = document.createElement('input');
  input.type  = 'number';
  input.step  = '0.01';
  input.min   = '0';
  input.value = curVal;
  input.className = 'tree-inline-input';
  span.innerHTML = '';
  span.appendChild(input);
  input.focus();
  input.select();

  const commit = async () => {
    const newVal = parseFloat(input.value);
    if (isNaN(newVal) || newVal === curVal) {
      await loadPositions(); return;
    }
    // Sauvegarde via snapshot-update si on est en mode édition snapshot, sinon PUT direct
    const useSnapshot = false; // édition inline = modification directe du snapshot courant
    try {
      await api('PUT', `/api/positions/${posId}`, {
        ...pos,
        value: newVal,
        debt:  pos.debt || 0,
      });
      await loadPositions();
    } catch (err) {
      alert(`Erreur : ${err.message}`);
      await loadPositions();
    }
  };

  input.addEventListener('blur',  commit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { input.removeEventListener('blur', commit); loadPositions(); }
  });
}

function renderPositionsTree(allPositions) {
  const container = document.getElementById('positions-tree-body');
  if (!allPositions.length) {
    container.innerHTML = '<p class="text-muted" style="padding:.75rem">Aucune position pour ce snapshot.</p>';
    return;
  }

  const etablKey = p => p.entity ? `Entité : ${p.entity}` : (p.establishment || '(Sans établissement)');

  let html = '';
  for (const owner of S.config.owners) {
    const ops = allPositions.filter(p => p.owner === owner);
    if (!ops.length) continue;
    const ownerNet   = ops.reduce((s, p) => s + (p.net_attributed || 0), 0);
    const ownerGross = ops.reduce((s, p) => s + (p.gross_attributed || 0), 0);

    const byEtabl = {};
    for (const p of ops) {
      const k = etablKey(p);
      if (!byEtabl[k]) byEtabl[k] = [];
      byEtabl[k].push(p);
    }

    const etablHtml = Object.entries(byEtabl)
      .sort((a, b) => b[1].reduce((s, p) => s + (p.net_attributed||0), 0) - a[1].reduce((s, p) => s + (p.net_attributed||0), 0))
      .map(([etabl, ePoses]) => {
        const etablNet   = ePoses.reduce((s, p) => s + (p.net_attributed || 0), 0);
        const etablGross = ePoses.reduce((s, p) => s + (p.gross_attributed || 0), 0);
        const isEntity   = etabl.startsWith('Entité : ');
        const etablIcon  = isEntity ? '🏢' : '🏦';

        const byEnv = {};
        for (const p of ePoses) {
          const k = p.envelope || '(Sans enveloppe)';
          if (!byEnv[k]) byEnv[k] = [];
          byEnv[k].push(p);
        }

        const envHtml = Object.entries(byEnv)
          .sort((a, b) => b[1].reduce((s, p) => s + (p.net_attributed||0), 0) - a[1].reduce((s, p) => s + (p.net_attributed||0), 0))
          .map(([env, envPoses]) => {
            const envNet   = envPoses.reduce((s, p) => s + (p.net_attributed || 0), 0);
            const envGross = envPoses.reduce((s, p) => s + (p.gross_attributed || 0), 0);
            const envDebt  = envPoses.reduce((s, p) => s + (p.debt_attributed || 0), 0);

            const catHtml = [...envPoses]
              .sort((a, b) => (b.net_attributed||0) - (a.net_attributed||0))
              .map(p => {
                const ownPct = p.ownership_pct ?? 1;
                const pctBadge = ownPct < 0.999
                  ? `<span class="badge badge-j27" style="font-size:10px">${Math.round(ownPct*100)}%</span>` : '';
                const notesMark = p.notes
                  ? `<span title="${esc(p.notes)}" style="font-size:11px;cursor:default;margin-left:3px">📋</span>` : '';
                const mobMark = p.mobilizable_pct_override != null
                  ? `<span title="Mobilisabilité surchargée : ${Math.round(p.mobilizable_pct_override*100)} %" style="font-size:11px;cursor:default;margin-left:3px;color:var(--warning)">⚠</span>` : '';
                const hasEntity = !!p.entity;
                const inlineVal = hasEntity
                  ? `<span class="tree-amount ${p.net_attributed < 0 ? 'neg' : ''}">${fmt(p.net_attributed)}</span>`
                  : `<span class="tree-inline-amount ${p.net_attributed < 0 ? 'neg' : ''}" title="Cliquer pour éditer la valeur" data-id="${p.id}" data-field="value" data-val="${p.value || 0}">${fmt(p.net_attributed)}</span>`;
                return `
                  <div class="tree-row tree-pos-leaf" data-pos-id="${p.id}">
                    <span class="tree-dot"></span>
                    <span class="tree-label">${esc(p.category)}${pctBadge}${notesMark}${mobMark}</span>
                    <span class="tree-badges">${liqBadge(p.liquidity)}</span>
                    ${inlineVal}
                    <span class="tree-actions">
                      <button class="btn-icon edit" data-id="${p.id}" data-action="edit-pos">Éditer</button>
                      <button class="btn-icon del"  data-id="${p.id}" data-action="del-pos">Suppr.</button>
                    </span>
                  </div>`;
              }).join('');

            const envDebtStr = envDebt > 0 ? `<span style="color:var(--danger);font-size:11px;margin-left:.5rem">dette ${fmt(envDebt)}</span>` : '';
            const envEntity  = isEntity ? etabl.replace(/^Entité : /, '') : '';
            const envEtabl   = isEntity ? '' : etabl;
            return `
              <div class="tree-row tree-env" data-key="penv-${esc(owner)}-${esc(etabl)}-${esc(env)}">
                <span class="tree-toggle">▾</span>
                <span class="tree-label">${esc(env)}${envDebtStr}</span>
                <span class="tree-amount ${envNet < 0 ? 'neg' : ''}">${fmt(envNet)}</span>
                <span class="tree-actions">
                  <button class="btn-icon add" data-action="add-pos-ctx"
                    data-owner="${esc(owner)}"
                    data-establishment="${esc(envEtabl)}"
                    data-envelope="${esc(env)}"
                    data-entity="${esc(envEntity)}"
                    title="Ajouter une position dans cette enveloppe">+</button>
                </span>
              </div>
              <div class="tree-children">${catHtml}</div>`;
          }).join('');

        const etablDebt    = ePoses.reduce((s, p) => s + (p.debt_attributed || 0), 0);
        const etablDebtStr = etablDebt > 0 ? `<span style="color:var(--danger);font-size:11px;margin-left:.5rem">dette ${fmt(etablDebt)}</span>` : '';
        const etablEntityName = isEntity ? etabl.replace(/^Entité : /, '') : '';
        const etablRealName   = isEntity ? '' : etabl;
        return `
          <div class="tree-row tree-etabl" data-key="petabl-${esc(owner)}-${esc(etabl)}">
            <span class="tree-toggle">▾</span>
            <span class="tree-icon">${etablIcon}</span>
            <span class="tree-label">${esc(etabl)}${etablDebtStr}</span>
            <span class="tree-amount ${etablNet < 0 ? 'neg' : ''}">${fmt(etablNet)}</span>
            <span class="tree-actions">
              <button class="btn-icon add" data-action="add-pos-ctx"
                data-owner="${esc(owner)}"
                data-establishment="${esc(etablRealName)}"
                data-envelope=""
                data-entity="${esc(etablEntityName)}"
                title="Ajouter une position dans cet établissement">+</button>
            </span>
          </div>
          <div class="tree-children">${envHtml}</div>`;
      }).join('');

    html += `
      <div class="tree-owner-section">
        <div class="tree-row tree-owner" data-key="powner-${esc(owner)}">
          <span class="tree-toggle">▾</span>
          <span class="tree-label">${esc(owner)}</span>
          <span class="tree-amount">${fmt(ownerNet)}</span>
          <span class="tree-actions">
            <button class="btn-icon add" data-action="add-pos-ctx"
              data-owner="${esc(owner)}"
              data-establishment="" data-envelope="" data-entity=""
              title="Ajouter une position pour ${esc(owner)}">+</button>
          </span>
        </div>
        <div class="tree-children">${etablHtml}</div>
      </div>`;
  }

  container.innerHTML = html;

  wireTreeAccordion(container);
  // La délégation des clics éditer/suppr est gérée une seule fois dans wireEvents
}

function renderPositions() {
  // Bascule vue
  const isTree = S.positionsView === 'tree';
  document.getElementById('positions-table-wrap').style.display = isTree ? 'none' : '';
  document.getElementById('positions-tree-wrap').style.display  = isTree ? '' : 'none';
  document.getElementById('positions-filters').style.display    = isTree ? 'none' : '';
  // Rendre le toggle si pas encore présent
  renderPosViewToggle();

  if (isTree) {
    renderPositionsTree(S.positions);
    return;
  }

  const positions = sortArr(filteredPositions(), S.sort.positions.key, S.sort.positions.dir);
  updateSortIndicators('positions-thead', 'positions');
  if (!positions.length) {
    renderPositionsEmpty(S.positions.length ? 'Aucune position pour ce filtre.' : 'Aucune position pour ce snapshot.');
    return;
  }

  document.getElementById('positions-tbody').innerHTML = positions.map(p => {
    const ownPct  = p.ownership_pct ?? 1;
    const debtPct = p.debt_pct ?? 1;
    const pctBadge = ownPct < 0.999
      ? `<span class="badge badge-j27" style="margin-left:4px;font-size:10px;vertical-align:middle">${Math.round(ownPct*100)}%</span>`
      : '';
    const debtBadge = p.debt_attributed > 0 && debtPct < 0.999
      ? `<span class="badge badge-30" style="margin-left:4px;font-size:10px;vertical-align:middle">${Math.round(debtPct*100)}%</span>`
      : '';
    const entitySub = p.entity
      ? `<div style="font-size:11px;color:var(--text-muted);margin-top:1px">↳ ${esc(p.entity)}</div>` : '';
    const notesMark = p.notes
      ? `<span title="${esc(p.notes)}" style="color:var(--text-muted);font-size:11px;margin-left:4px;cursor:default">📋</span>` : '';
    return `<tr>
      <td><strong>${esc(p.owner)}</strong></td>
      <td>${esc(p.category)}${notesMark}</td>
      <td>${esc(p.envelope || '—')}</td>
      <td>${esc(p.establishment || '—')}${entitySub}</td>
      <td class="num">${fmt(p.gross_attributed)}${pctBadge}</td>
      <td class="num ${p.debt_attributed > 0 ? 'neg' : ''}">${p.debt_attributed > 0 ? fmt(p.debt_attributed) : '—'}${debtBadge}</td>
      <td class="num ${p.net_attributed < 0 ? 'neg' : ''}">${fmt(p.net_attributed)}</td>
      <td>${liqBadge(p.liquidity)}</td>
      <td class="num">${fmt(p.mobilizable_value)}${p.mobilizable_pct_override != null ? ` <span title="Mobilisabilité surchargée : ${Math.round(p.mobilizable_pct_override*100)} %" style="color:var(--warning);font-size:11px">⚠</span>` : ''}</td>
      <td style="white-space:nowrap">
        <button class="btn-icon edit" data-id="${p.id}" data-action="edit-pos">Éditer</button>
        <button class="btn-icon del"  data-id="${p.id}" data-action="del-pos">Suppr.</button>
      </td>
    </tr>`;
  }).join('');

  // Totals footer (sur les positions filtrées)
  const totGross = positions.reduce((s, p) => s + (p.gross_attributed || 0), 0);
  const totDebt  = positions.reduce((s, p) => s + (p.debt_attributed  || 0), 0);
  const totNet   = positions.reduce((s, p) => s + (p.net_attributed   || 0), 0);
  const totMob   = positions.reduce((s, p) => s + (p.mobilizable_value|| 0), 0);
  document.getElementById('positions-tfoot').innerHTML = `
    <tr>
      <td colspan="4">TOTAL</td>
      <td class="num">${fmt(totGross)}</td>
      <td class="num neg">${totDebt > 0 ? fmt(totDebt) : '—'}</td>
      <td class="num">${fmt(totNet)}</td>
      <td></td>
      <td class="num">${fmt(totMob)}</td>
      <td></td>
    </tr>`;

  // Delegate click events
  document.getElementById('positions-tbody').addEventListener('click', onPosTableClick, { once: true });
}

function onPosTableClick(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const id = parseInt(btn.dataset.id);
  if (btn.dataset.action === 'edit-pos') openPosModal(id);
  if (btn.dataset.action === 'del-pos')  deletePosition(id);
  // re-attach
  document.getElementById('positions-tbody').addEventListener('click', onPosTableClick, { once: true });
}

async function duplicateSnapshot() {
  if (!S.positionsDate) return;
  const newDate = prompt('Nouvelle date pour le snapshot (format AAAA-MM-JJ) :');
  if (!newDate) return;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(newDate)) {
    alert('Format invalide. Utilisez AAAA-MM-JJ (ex: 2026-04-01)');
    return;
  }
  if (S.dates.includes(newDate) && !confirm(`Un snapshot du ${newDate} existe déjà. L'écraser ?`)) return;
  const src = await api('GET', `/api/positions?date=${S.positionsDate}`);
  await Promise.all(src.map(p => {
    const { id, created_at, net_value, gross_attributed, debt_attributed,
            net_attributed, liquidity, friction, mobilizable_pct, mobilizable_value, ...rest } = p;
    return api('POST', '/api/positions', { ...rest, date: newDate });
  }));
  S.positionsDate = newDate;
  await refreshDates();
  await loadPositions();
  await loadHistorique();
}

// Position modal
// prefill : { owner, establishment, envelope, entity } — optionnel, pour création contextuelle
function openPosModal(id = null, prefill = {}) {
  S.editPosId = id;
  document.getElementById('position-modal-title').textContent =
    id ? 'Modifier la position' : 'Ajouter une position';

  if (id) {
    const p = S.positions.find(x => x.id === id);
    if (!p) return;
    document.getElementById('pos-date').value          = p.date;
    document.getElementById('pos-owner').value         = p.owner;
    document.getElementById('pos-category').value      = p.category;
    document.getElementById('pos-envelope').value      = p.envelope || '';
    document.getElementById('pos-establishment').value = p.establishment || '';
    document.getElementById('pos-value').value         = p.value || 0;
    document.getElementById('pos-debt').value          = p.debt || 0;
    document.getElementById('pos-ownership').value     = Math.round((p.ownership_pct ?? 1) * 100);
    document.getElementById('pos-debt-pct').value      = Math.round((p.debt_pct ?? 1) * 100);
    document.getElementById('pos-entity-select').value = p.entity || '';
    document.getElementById('pos-notes').value         = p.notes || '';
    const hasOverride = p.mobilizable_pct_override != null;
    document.getElementById('pos-mob-override-check').checked = hasOverride;
    document.getElementById('pos-mob-override-field').style.display = hasOverride ? '' : 'none';
    document.getElementById('pos-mob-override-pct').value = hasOverride ? Math.round(p.mobilizable_pct_override * 100) : 100;
    // Sync état des champs entité
    const hasPctFields = document.getElementById('pos-pct-fields');
    if (hasPctFields) hasPctFields.style.display = p.entity ? 'contents' : 'none';
    document.getElementById('pos-value').disabled = !!p.entity;
    document.getElementById('pos-debt').disabled  = !!p.entity;
    // Option snapshot : visible en édition, date cible = aujourd'hui, décochée par défaut
    document.getElementById('pos-snapshot-option').classList.remove('hidden');
    document.getElementById('pos-snapshot-date').value = today();
    document.getElementById('pos-snapshot-check').checked = false;
    document.getElementById('pos-snapshot-date').style.visibility = 'hidden';
  } else {
    document.getElementById('pos-date').value         = S.positionsDate || today();
    document.getElementById('pos-owner').value        = S.config.owners[0];
    document.getElementById('pos-category').value     = S.config.categories[0];
    document.getElementById('pos-envelope').value     = '';
    document.getElementById('pos-establishment').value= '';
    document.getElementById('pos-value').value        = 0;
    document.getElementById('pos-debt').value         = 0;
    document.getElementById('pos-ownership').value    = 100;
    document.getElementById('pos-debt-pct').value     = 100;
    document.getElementById('pos-notes').value          = '';
    document.getElementById('pos-mob-override-check').checked = false;
    document.getElementById('pos-mob-override-field').style.display = 'none';
    document.getElementById('pos-mob-override-pct').value = 100;
    // Pré-remplissage contextuel
    if (prefill.owner)         document.getElementById('pos-owner').value         = prefill.owner;
    if (prefill.establishment) document.getElementById('pos-establishment').value  = prefill.establishment;
    if (prefill.envelope)      document.getElementById('pos-envelope').value       = prefill.envelope;
    if (prefill.entity) {
      document.getElementById('pos-entity-select').value = prefill.entity;
      onEntitySelectChange();  // déclenche auto-fill valeur, % etc.
    } else {
      document.getElementById('pos-entity-select').value = '';
      // Pas d'entité → champs valeur actifs, % cachés
      const hasPctFields = document.getElementById('pos-pct-fields');
      if (hasPctFields) hasPctFields.style.display = 'none';
      document.getElementById('pos-value').disabled = false;
      document.getElementById('pos-debt').disabled  = false;
    }
    // Pas d'option snapshot en création
    document.getElementById('pos-snapshot-option').classList.add('hidden');
  }
  updatePosInfo();
  document.getElementById('position-modal').classList.remove('hidden');
  document.getElementById('pos-date').focus();
}

function onEntitySelectChange() {
  const name = document.getElementById('pos-entity-select').value;
  const pctFields = document.getElementById('pos-pct-fields');

  // Champs valeur/dette : en lecture seule si entité (valeur vient de l'entité, non stockée)
  document.getElementById('pos-value').disabled = !!name;
  document.getElementById('pos-debt').disabled  = !!name;
  // % propriété et % dette : visibles uniquement si entité sélectionnée
  if (pctFields) pctFields.style.display = name ? 'contents' : 'none';

  const etablInput = document.getElementById('pos-establishment');
  if (!name) {
    document.getElementById('pos-value').value = 0;
    document.getElementById('pos-debt').value  = 0;
    document.getElementById('pos-ownership').value = 100;
    document.getElementById('pos-debt-pct').value  = 100;
    etablInput.placeholder = 'ex : Boursorama';
    updatePosInfo();
    return;
  }
  // Guider l'établissement : suggérer le nom de l'entité si vide
  if (!etablInput.value) etablInput.value = name;
  etablInput.placeholder = `Établissement gestionnaire de "${name}"`;

  const entity = S.entities.find(e => e.name === name);
  if (!entity) return;

  // Auto-fill value and debt from entity (affichage informatif uniquement)
  document.getElementById('pos-value').value = entity.gross_assets || 0;
  document.getElementById('pos-debt').value  = entity.debt || 0;

  // Calcul de la détention déjà saisie sur cette entité (positions existantes du snapshot)
  const existingPct = S.positions
    .filter(p => p.entity === name && p.id !== S.editPosId)
    .reduce((s, p) => s + (p.ownership_pct || 0), 0);
  const remaining = Math.max(0, 1 - existingPct);

  // Suggérer le % restant pour la détention
  if (remaining < 1) {
    document.getElementById('pos-ownership').value = Math.round(remaining * 100);
    // Ne pas forcer debt_pct : peut être différent (ex: un seul emprunteur)
  }

  updatePosInfo();

  // Afficher un résumé des détenteurs existants
  const byOwner = S.positions
    .filter(p => p.entity === name && p.id !== S.editPosId)
    .map(p => `${p.owner} ${Math.round((p.ownership_pct || 0) * 100)} %`);
  const hint = byOwner.length
    ? `Entité : ${entity.name} — Actif net ${fmt(entity.net_assets)}\nDétention déjà attribuée : ${byOwner.join(', ')} (total ${Math.round(existingPct * 100)} %)\nSuggestion détention : ${Math.round(remaining * 100)} %\n% dette indépendant — ex: 100% si emprunteur unique, 0% sinon.`
    : `Entité : ${entity.name} — Actif net ${fmt(entity.net_assets)}\nIndiquez votre % de détention et votre % de la dette (peuvent différer).`;
  document.getElementById('pos-computed-info').textContent = hint;
}

function updatePosInfo() {
  const value       = parseFloat(document.getElementById('pos-value').value) || 0;
  const debt        = parseFloat(document.getElementById('pos-debt').value) || 0;
  const ownerPct    = (parseFloat(document.getElementById('pos-ownership').value) || 100) / 100;
  const debtPct     = (parseFloat(document.getElementById('pos-debt-pct').value) || 100) / 100;
  const envelope    = document.getElementById('pos-envelope').value;
  const category    = document.getElementById('pos-category').value;

  const gross    = value * ownerPct;
  const debtAttr = debt * debtPct;
  const net      = gross - debtAttr;

  const envMeta    = S.config.envelope_meta[envelope] || { liquidity: '30J+', friction: 'Mixte' };
  const useOverride = document.getElementById('pos-mob-override-check').checked;
  const mobPct     = useOverride
    ? (parseFloat(document.getElementById('pos-mob-override-pct').value) || 0) / 100
    : (S.config.category_mobilizable[category] ?? 0.8);
  const mob      = net > 0 ? net * mobPct : 0;
  const overrideLabel = useOverride ? ' ⚠ surchargé' : '';

  document.getElementById('pos-computed-info').textContent =
    `Net attribué : ${fmt(net)}  ·  Liquidité : ${envMeta.liquidity}  ·  Mobilisable : ${fmt(mob)} (${(mobPct * 100).toFixed(0)} %${overrideLabel})`;
}

async function savePosition(e) {
  e.preventDefault();
  const data = {
    date:          document.getElementById('pos-date').value,
    owner:         document.getElementById('pos-owner').value,
    category:      document.getElementById('pos-category').value,
    envelope:      document.getElementById('pos-envelope').value || null,
    establishment: document.getElementById('pos-establishment').value || null,
    value:         parseFloat(document.getElementById('pos-value').value) || 0,
    debt:          parseFloat(document.getElementById('pos-debt').value) || 0,
    ownership_pct: (parseFloat(document.getElementById('pos-ownership').value) || 100) / 100,
    debt_pct:      (parseFloat(document.getElementById('pos-debt-pct').value) || 100) / 100,
    entity:        document.getElementById('pos-entity-select').value || null,
    notes:         document.getElementById('pos-notes').value || null,
    mobilizable_pct_override: document.getElementById('pos-mob-override-check').checked
      ? (parseFloat(document.getElementById('pos-mob-override-pct').value) || 0) / 100
      : null,
  };

  if (S.editPosId) {
    const useSnapshot = document.getElementById('pos-snapshot-check').checked;
    const targetDate  = document.getElementById('pos-snapshot-date').value;

    if (useSnapshot && targetDate) {
      const sourceDate = S.positions.find(p => p.id === S.editPosId)?.date;
      if (targetDate !== sourceDate && S.dates.includes(targetDate) &&
          !confirm(`Un snapshot du ${targetDate} existe déjà. Il sera remplacé par une copie du ${sourceDate} avec cette modification. Continuer ?`)) {
        return;
      }
      await api('POST', `/api/positions/${S.editPosId}/snapshot-update`, {
        source_date: sourceDate,
        target_date: targetDate,
        position:    data,
      });
      // Bascule sur le nouveau snapshot
      S.positionsDate = targetDate;
      S.syntheseDate  = targetDate;
    } else {
      // Modification en place
      await api('PUT', `/api/positions/${S.editPosId}`, data);
    }
  } else {
    await api('POST', '/api/positions', data);
  }

  closeModal('position-modal');
  toast(S.editPosId ? 'Position mise à jour' : 'Position ajoutée');
  await refreshDates();
  await loadPositions();
  await loadSynthese();
  await loadHistorique();
}

async function deletePosition(id) {
  const pos = S.positions.find(p => p.id === id);
  const label = pos ? `${pos.category} — ${pos.owner}` : `Position #${id}`;
  if (!await confirmDialog('Supprimer la position ?', `<strong>${esc(label)}</strong><br>Cette action est irréversible.`)) return;
  await api('DELETE', `/api/positions/${id}`);
  toast('Position supprimée');
  await loadPositions();
  await loadSynthese();
  await loadHistorique();
}

// ─── Flux ─────────────────────────────────────────────────────────────────

async function loadFlux() {
  S.flux = await api('GET', '/api/flux');
  populateFluxFilters();
  renderFlux();
}

function populateFluxFilters() {
  const owners = [...new Set(S.flux.map(f => f.owner))].sort();
  const types  = [...new Set(S.flux.map(f => f.type).filter(Boolean))].sort();
  const years  = [...new Set(S.flux.map(f => f.date?.slice(0, 4)).filter(Boolean))].sort().reverse();

  const sel = (id, placeholder, opts) => {
    const cur = document.getElementById(id)?.value;
    document.getElementById(id).innerHTML =
      `<option value="">${placeholder}</option>` +
      opts.map(o => `<option value="${esc(o)}"${o === cur ? ' selected' : ''}>${esc(o)}</option>`).join('');
  };
  sel('flux-filter-owner', 'Toutes les personnes', owners);
  sel('flux-filter-type',  'Tous les types',       types);
  sel('flux-filter-year',  'Toutes les années',    years);
}

function filteredFlux() {
  const owner = document.getElementById('flux-filter-owner')?.value;
  const type  = document.getElementById('flux-filter-type')?.value;
  const year  = document.getElementById('flux-filter-year')?.value;
  return S.flux.filter(f =>
    (!owner || f.owner === owner) &&
    (!type  || f.type  === type)  &&
    (!year  || f.date?.startsWith(year))
  );
}

function renderFlux() {
  const tbody  = document.getElementById('flux-tbody');
  const tfoot  = document.getElementById('flux-tfoot');
  const flux = sortArr(filteredFlux(), S.sort.flux.key, S.sort.flux.dir);
  updateSortIndicators('flux-thead', 'flux');

  if (!flux.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="7">Aucun flux enregistré.</td></tr>';
    if (tfoot) tfoot.innerHTML = '';
    return;
  }
  tbody.innerHTML = flux.map(f => `
    <tr>
      <td>${fmtDate(f.date)}</td>
      <td>${esc(f.owner)}</td>
      <td>${esc(f.envelope || '—')}</td>
      <td>${esc(f.type || '—')}</td>
      <td class="num ${f.amount >= 0 ? 'pos' : 'neg'}">${f.amount >= 0 ? '+' : ''}${fmt(f.amount)}</td>
      <td>${esc(f.notes || '—')}</td>
      <td style="white-space:nowrap">
        <button class="btn-icon edit" data-id="${f.id}" data-action="edit-flux">Éditer</button>
        <button class="btn-icon del"  data-id="${f.id}" data-action="del-flux">Suppr.</button>
      </td>
    </tr>`).join('');

  // Total et sous-totaux
  const total = flux.reduce((s, f) => s + (f.amount || 0), 0);
  const byType  = {};
  const byOwner = {};
  for (const f of flux) {
    const t = f.type || 'Autre';
    byType[t]   = (byType[t]   || 0) + (f.amount || 0);
    byOwner[f.owner] = (byOwner[f.owner] || 0) + (f.amount || 0);
  }
  const ownersActive = Object.keys(byOwner);
  if (tfoot) {
    tfoot.innerHTML = `
      <tr>
        <td colspan="4" style="font-size:11px;color:var(--text-muted)">
          ${Object.entries(byType).map(([t, v]) =>
            `${esc(t)} : <strong class="${v >= 0 ? 'pos' : 'neg'}">${v >= 0 ? '+' : ''}${fmt(v)}</strong>`
          ).join(' &nbsp;·&nbsp; ')}
        </td>
        <td class="num ${total >= 0 ? 'pos' : 'neg'}" style="font-weight:700">${total >= 0 ? '+' : ''}${fmt(total)}</td>
        <td colspan="2"></td>
      </tr>
      ${ownersActive.length > 1 ? `<tr>
        <td colspan="4" style="font-size:11px;color:var(--text-muted)">
          ${ownersActive.map(o =>
            `${esc(o)} : <strong class="${byOwner[o] >= 0 ? 'pos' : 'neg'}">${byOwner[o] >= 0 ? '+' : ''}${fmt(byOwner[o])}</strong>`
          ).join(' &nbsp;·&nbsp; ')}
        </td>
        <td colspan="3"></td>
      </tr>` : ''}`;
  }

  tbody.addEventListener('click', onFluxTableClick, { once: true });
}

function onFluxTableClick(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const id = parseInt(btn.dataset.id);
  if (btn.dataset.action === 'edit-flux') openFluxModal(id);
  if (btn.dataset.action === 'del-flux')  deleteFlux(id);
  document.getElementById('flux-tbody').addEventListener('click', onFluxTableClick, { once: true });
}

function openFluxModal(id = null) {
  S.editFluxId = id;
  document.getElementById('flux-modal-title').textContent =
    id ? 'Modifier le flux' : 'Ajouter un flux';

  if (id) {
    const f = S.flux.find(x => x.id === id);
    if (!f) return;
    document.getElementById('flux-date').value    = f.date;
    document.getElementById('flux-owner').value   = f.owner;
    document.getElementById('flux-envelope').value= f.envelope || '';
    document.getElementById('flux-type').value    = f.type || '';
    document.getElementById('flux-amount').value  = f.amount;
    document.getElementById('flux-notes').value   = f.notes || '';
  } else {
    document.getElementById('flux-date').value    = today();
    document.getElementById('flux-owner').value   = S.config.owners[0];
    document.getElementById('flux-envelope').value= '';
    document.getElementById('flux-type').value    = S.config.flux_types[0];
    document.getElementById('flux-amount').value  = '';
    document.getElementById('flux-notes').value   = '';
  }
  document.getElementById('flux-modal').classList.remove('hidden');
  document.getElementById('flux-amount').focus();
}

async function saveFlux(e) {
  e.preventDefault();
  const data = {
    date:     document.getElementById('flux-date').value,
    owner:    document.getElementById('flux-owner').value,
    envelope: document.getElementById('flux-envelope').value || null,
    type:     document.getElementById('flux-type').value || null,
    amount:   parseFloat(document.getElementById('flux-amount').value),
    notes:    document.getElementById('flux-notes').value || null,
  };
  if (S.editFluxId) {
    await api('PUT', `/api/flux/${S.editFluxId}`, data);
  } else {
    await api('POST', '/api/flux', data);
  }
  closeModal('flux-modal');
  toast(S.editFluxId ? 'Flux mis à jour' : 'Flux ajouté');
  await loadFlux();
}

async function deleteFlux(id) {
  const f = S.flux.find(x => x.id === id);
  const label = f ? `${f.type || 'Flux'} — ${fmt(f.amount)} (${f.owner})` : `Flux #${id}`;
  if (!await confirmDialog('Supprimer ce flux ?', `<strong>${esc(label)}</strong><br>Cette action est irréversible.`)) return;
  await api('DELETE', `/api/flux/${id}`);
  toast('Flux supprimé');
  await loadFlux();
}

// ─── Import / Export ──────────────────────────────────────────────────────

async function importXlsx() {
  const file = document.getElementById('import-file').files[0];
  if (!file) { showImportResult('Sélectionne un fichier .xlsx.', false); return; }

  const fd = new FormData();
  fd.append('file', file);
  try {
    const res  = await fetch('/api/import', { method: 'POST', body: fd });
    const data = await res.json();
    if (res.ok) {
      const parts = [`✓ ${data.imported} position(s)`];
      if (data.entities) parts.push(`${data.entities} entité(s)`);
      showImportResult(parts.join(' · ') + ' importée(s).', true);
      await refreshDates();
      await loadHistorique();
    } else {
      showImportResult(`Erreur : ${data.error}`, false);
    }
  } catch (err) {
    showImportResult(`Erreur : ${err.message}`, false);
  }
}

function showImportResult(msg, ok) {
  document.getElementById('import-result').innerHTML =
    `<div class="alert alert-${ok ? 'success' : 'error'}">${esc(msg)}</div>`;
}

async function importJson() {
  const file = document.getElementById('import-json-file').files[0];
  if (!file) { showJsonImportResult('Sélectionne un fichier .json.', false); return; }

  try {
    const text = await file.text();
    const data = JSON.parse(text);

    // Restaurer les allocations cibles si présentes
    if (data.allocation_targets && typeof data.allocation_targets === 'object') {
      await saveTargets(data.allocation_targets);
    }

    const result = await api('POST', '/api/import-json', data);
    const parts = [];
    if (result.positions)        parts.push(`${result.positions} position(s)`);
    if (result.flux)             parts.push(`${result.flux} flux`);
    if (result.entities)         parts.push(`${result.entities} entité(s)`);
    if (result.entity_snapshots) parts.push(`${result.entity_snapshots} snapshot(s) entité`);
    showJsonImportResult('✓ Importé : ' + (parts.join(', ') || 'rien de nouveau') + '.', true);
    await refreshDates();
    await loadHistorique();
    await loadEntities();
  } catch (err) {
    showJsonImportResult(`Erreur : ${err.message}`, false);
  }
}

function showJsonImportResult(msg, ok) {
  document.getElementById('import-json-result').innerHTML =
    `<div class="alert alert-${ok ? 'success' : 'error'}">${esc(msg)}</div>`;
}

async function resetDb() {
  if (!await confirmDialog(
    'Vider TOUTE la base ?',
    'Positions, flux et entités seront supprimés <strong>définitivement</strong>.<br>Faites un export JSON avant si vous souhaitez conserver vos données.',
    { confirmText: 'Tout supprimer', danger: true }
  )) return;
  await api('POST', '/api/reset');
  S.dates = []; S.syntheseDate = null; S.positionsDate = null;
  S.positions = []; S.flux = []; S.entities = []; S.historique = [];
  await refreshDates();
  renderDateSelects();
  renderEntities();
  renderFlux();
  renderSynthese();
  document.getElementById('reset-result').innerHTML =
    '<div class="alert alert-success">Base vidée. Vous pouvez réimporter.</div>';
  setTimeout(() => { document.getElementById('reset-result').innerHTML = ''; }, 4000);
}

async function exportJson() {
  const data = await api('GET', '/api/export');
  data.allocation_targets = await loadTargets();
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url;
  a.download = `patrimoine_${today()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Modals ───────────────────────────────────────────────────────────────

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

// ─── Allocation cible ─────────────────────────────────────────────────────

// ─── Allocation cible (DB-backed) ────────────────────────────────────────

let _targetsCache = null;

async function loadTargets() {
  if (_targetsCache !== null) return _targetsCache;
  try {
    _targetsCache = await api('GET', '/api/targets');
  } catch {
    // Fallback localStorage pour migration
    try { _targetsCache = JSON.parse(localStorage.getItem('patrimoine_targets')) || {}; } catch { _targetsCache = {}; }
  }
  return _targetsCache;
}

async function saveTargets(targets) {
  _targetsCache = targets;
  try {
    await api('PUT', '/api/targets', targets);
    // Nettoyer localStorage après migration réussie
    localStorage.removeItem('patrimoine_targets');
  } catch {
    // Fallback localStorage
    localStorage.setItem('patrimoine_targets', JSON.stringify(targets));
  }
}

function wireTargetsEvents() {
  document.getElementById('btn-edit-targets').addEventListener('click', openTargetsModal);
  document.getElementById('btn-save-targets').addEventListener('click', async () => {
    const targets = {};
    document.querySelectorAll('.target-input').forEach(inp => {
      const val = parseFloat(inp.value);
      if (!isNaN(val) && val > 0) targets[inp.dataset.cat] = val;
    });
    await saveTargets(targets);
    closeModal('targets-modal');
    renderAllocationTargets();
  });
  document.getElementById('targets-modal-overlay').addEventListener('click', () => closeModal('targets-modal'));
}

async function openTargetsModal() {
  const targets = await loadTargets();
  document.getElementById('targets-form-grid').innerHTML =
    S.config.categories.map(cat => `
      <div class="target-row">
        <label>${esc(cat)}</label>
        <input class="target-input" type="number" min="0" max="100" step="1"
               data-cat="${esc(cat)}" value="${targets[cat] || ''}">
        <span style="font-size:12px;color:var(--text-muted)">%</span>
      </div>`).join('');
  document.getElementById('targets-modal').classList.remove('hidden');
}

async function renderAllocationTargets() {
  const syn = S.synthese;
  if (!syn?.totals_by_category) {
    document.getElementById('allocation-targets').innerHTML =
      '<p class="text-muted" style="font-size:13px">Aucune donnée.</p>';
    return;
  }
  const targets  = await loadTargets();
  const owner    = S.syntheseOwner;
  const isFamily = owner === 'Famille';
  const totalNet = isFamily
    ? syn.family.net
    : (syn.totals_by_owner[owner]?.net || 0);

  const rows = S.config.categories
    .map(cat => {
      const net = isFamily
        ? (syn.totals_by_category[cat]?.net || 0)
        : (syn.totals_by_category[cat]?.by_owner?.[owner] || 0);
      const actual = totalNet > 0 ? (net / totalNet) * 100 : 0;
      const target = targets[cat] || 0;
      const delta  = actual - target;
      return { cat, net, actual, target, delta };
    })
    .filter(r => r.net > 0 || r.target > 0)
    .sort((a, b) => b.net - a.net);

  if (!rows.length) {
    document.getElementById('allocation-targets').innerHTML =
      '<p class="text-muted" style="font-size:13px">Cliquez sur "Modifier cibles" pour configurer.</p>';
    return;
  }

  document.getElementById('allocation-targets').innerHTML = `
    <div style="display:grid;grid-template-columns:130px 1fr 55px 55px 55px;gap:.5rem;padding:.35rem 0;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);border-bottom:2px solid var(--border)">
      <div>Catégorie</div><div></div><div style="text-align:right">Réel</div><div style="text-align:right">Cible</div><div style="text-align:right">Écart</div>
    </div>
    ${rows.map(r => {
      const barActual = Math.min(100, r.actual);
      const barTarget = r.target ? Math.min(100, r.target) : null;
      const deltaClass = r.target === 0 ? '' : r.delta > 2 ? 'alloc-delta-pos' : r.delta < -2 ? 'alloc-delta-neg' : '';
      const deltaStr   = r.target === 0 ? '—' : (r.delta > 0 ? '+' : '') + r.delta.toFixed(1) + ' %';
      return `<div class="alloc-row">
        <div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.cat)}</div>
        <div class="alloc-bar-bg">
          <div class="alloc-bar-actual" style="width:${barActual.toFixed(1)}%"></div>
          ${barTarget !== null ? `<div class="alloc-bar-target" style="left:${barTarget.toFixed(1)}%"></div>` : ''}
        </div>
        <div style="text-align:right;font-weight:600">${r.actual.toFixed(1)} %</div>
        <div style="text-align:right;color:var(--text-muted)">${r.target ? r.target + ' %' : '—'}</div>
        <div style="text-align:right" class="${deltaClass}">${deltaStr}</div>
      </div>`;
    }).join('')}`;
}

// ─── Performance ──────────────────────────────────────────────────────────

async function renderPerf() {
  const hist = S.historique;
  const el   = document.getElementById('perf-section');
  if (hist.length < 2) {
    el.innerHTML = '<p class="text-muted" style="font-size:13px">Au moins 2 snapshots nécessaires.</p>';
    return;
  }

  const owner    = S.syntheseOwner;
  const isFamily = owner === 'Famille';

  const netOf = h => isFamily ? h.family_net : (h.by_owner?.[owner] || 0);

  const last  = hist[hist.length - 1];
  const first = hist[0];
  const prev  = hist[hist.length - 2];

  const lastNet  = netOf(last);
  const firstNet = netOf(first);
  const prevNet  = netOf(prev);

  const variation = (curr, ref) => ref !== 0
    ? ((curr - ref) / Math.abs(ref)) * 100
    : null;

  // Flux filtrés sur la plage premier→dernier snapshot
  let fluxTotal = 0;
  try {
    const flux = await api('GET', `/api/flux?date_from=${first.date}&date_to=${last.date}`);
    const filtered = isFamily ? flux : flux.filter(f => f.owner === owner);
    fluxTotal = filtered.reduce((s, f) => s + (f.amount || 0), 0);
  } catch {}

  const totalGain = lastNet - firstNet - fluxTotal;
  const varLast   = variation(lastNet, prevNet);
  const varTotal  = variation(lastNet, firstNet);

  const perfLabel = isFamily ? '' : ` — ${owner}`;

  el.innerHTML = `<div class="perf-grid">
    <div class="perf-row">
      <span class="perf-label">${fmtDate(prev.date)} → ${fmtDate(last.date)}${perfLabel}</span>
      <span class="perf-val ${varLast >= 0 ? 'pos' : 'neg'}">${varLast != null ? (varLast > 0 ? '+' : '') + varLast.toFixed(2) + ' %' : '—'}</span>
    </div>
    <div class="perf-row">
      <span class="perf-label">Depuis le début (${fmtDate(first.date)})${perfLabel}</span>
      <span class="perf-val ${varTotal >= 0 ? 'pos' : 'neg'}">${varTotal != null ? (varTotal > 0 ? '+' : '') + varTotal.toFixed(2) + ' %' : '—'}</span>
    </div>
    <div class="perf-row">
      <span class="perf-label">Gain / perte hors flux${perfLabel}</span>
      <span class="perf-val ${totalGain >= 0 ? 'pos' : 'neg'}">${(totalGain >= 0 ? '+' : '') + fmt(totalGain)}</span>
    </div>
    <div class="perf-row">
      <span class="perf-label">Flux cumulés (${fmtDate(first.date)} → ${fmtDate(last.date)})${perfLabel}</span>
      <span class="perf-val">${fmt(fluxTotal)}</span>
    </div>
  </div>`;
}

// ─── Drill-down ───────────────────────────────────────────────────────────

function openDrilldown({ subtitle, title, amount, sections }) {
  document.getElementById('dd-subtitle').textContent = subtitle || '';
  document.getElementById('dd-title').textContent    = title   || '';
  document.getElementById('dd-amount').textContent   = amount  || '';

  document.getElementById('dd-body').innerHTML = sections.map(sec => `
    <div class="dd-section">
      ${sec.title ? `<div class="dd-section-title">${esc(sec.title)}</div>` : ''}
      ${sec.rows.map(r => {
        const bar = r.pct != null
          ? `<div class="dd-bar-wrap"><div class="dd-bar" style="width:${Math.min(100,r.pct).toFixed(1)}%"></div></div>`
          : '';
        return `<div class="dd-row">
          <div class="dd-row-left">
            <div class="dd-row-name">${esc(r.name)}</div>
            ${r.sub ? `<div class="dd-row-sub">${esc(r.sub)}</div>` : ''}
            ${bar}
          </div>
          <div class="dd-row-right">
            <div class="dd-row-val ${r.neg ? 'neg' : ''}">${r.val}</div>
            ${r.pctLabel ? `<div class="dd-row-pct">${r.pctLabel}</div>` : ''}
          </div>
        </div>`;
      }).join('')}
    </div>`).join('');

  document.getElementById('drilldown-panel').classList.remove('hidden');
}

function closeDrilldown() {
  document.getElementById('drilldown-panel').classList.add('hidden');
}

function drilldownPositions(positions, title, subtitle, { showOwner = false } = {}) {
  const total = positions.reduce((s, p) => s + (p.net_attributed || 0), 0);
  const sorted = [...positions].sort((a, b) => (b.net_attributed || 0) - (a.net_attributed || 0));

  openDrilldown({
    subtitle,
    title,
    amount: fmt(total),
    sections: [{
      title: `${sorted.length} position(s)`,
      rows: sorted.map(p => ({
        name:     p.envelope || p.category,
        sub:      [showOwner ? p.owner : null, p.establishment, p.entity, liqText(p.liquidity)].filter(Boolean).join(' · '),
        val:      fmt(p.net_attributed),
        pct:      total > 0 ? (p.net_attributed / total) * 100 : 0,
        pctLabel: total > 0 ? ((p.net_attributed / total) * 100).toFixed(1) + ' %' : '',
        neg:      p.net_attributed < 0,
      })),
    }],
  });
}

const liqText = l => l ? `Liq. ${l}` : '';

function wireDrilldownEvents() {
  document.getElementById('dd-close').addEventListener('click', closeDrilldown);
  document.getElementById('drilldown-overlay').addEventListener('click', closeDrilldown);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    // Fermer dans l'ordre : modal visible > drilldown
    const modals = ['position-modal', 'flux-modal', 'entity-modal', 'targets-modal'];
    for (const id of modals) {
      const el = document.getElementById(id);
      if (el && !el.classList.contains('hidden')) { closeModal(id); return; }
    }
    closeDrilldown();
  });

  // KPI cards
  ['kpi-net','kpi-gross','kpi-debt','kpi-mobilizable'].forEach(id => {
    document.getElementById(id).closest('.kpi-card').classList.add('clickable');
  });
  document.getElementById('kpi-net').closest('.kpi-card').addEventListener('click', () => {
    if (!S.synthese?.date) return;
    api('GET', `/api/positions?date=${S.syntheseDate}`).then(pos =>
      drilldownPositions(pos, 'Patrimoine net famille', 'Toutes les personnes', { showOwner: true })
    );
  });
  document.getElementById('kpi-gross').closest('.kpi-card').addEventListener('click', () => {
    if (!S.synthese?.date) return;
    api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
      const total = positions.reduce((s, p) => s + (p.gross_attributed || 0), 0);
      const sorted = [...positions].sort((a, b) => (b.gross_attributed||0) - (a.gross_attributed||0));
      openDrilldown({
        subtitle: 'Actifs bruts', title: 'Toutes les personnes', amount: fmt(total),
        sections: [{ title: `${sorted.length} position(s)`, rows: sorted.map(p => ({
          name: p.envelope || p.category,
          sub: [p.owner, p.establishment].filter(Boolean).join(' · '),
          val: fmt(p.gross_attributed),
          pct: total > 0 ? (p.gross_attributed / total) * 100 : 0,
          pctLabel: total > 0 ? ((p.gross_attributed / total) * 100).toFixed(1) + ' %' : '',
        }))}],
      });
    });
  });
  document.getElementById('kpi-debt').closest('.kpi-card').addEventListener('click', () => {
    if (!S.synthese?.date) return;
    api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
      const withDebt = positions.filter(p => p.debt_attributed > 0);
      const total = withDebt.reduce((s, p) => s + (p.debt_attributed || 0), 0);
      openDrilldown({
        subtitle: 'Dettes', title: 'Toutes les personnes', amount: fmt(total),
        sections: [{ title: `${withDebt.length} position(s)`, rows:
          withDebt.sort((a,b) => b.debt_attributed - a.debt_attributed).map(p => ({
            name: p.envelope || p.category,
            sub: [p.owner, p.establishment].filter(Boolean).join(' · '),
            val: fmt(p.debt_attributed), neg: true,
            pct: total > 0 ? (p.debt_attributed / total) * 100 : 0,
            pctLabel: total > 0 ? ((p.debt_attributed / total) * 100).toFixed(1) + ' %' : '',
          }))}],
      });
    });
  });
  document.getElementById('kpi-mobilizable').closest('.kpi-card').addEventListener('click', () => {
    if (!S.synthese?.date) return;
    drilldownMobilizable();
  });
}

function drilldownAllPositions(title, subtitle) {
  // On charge les positions de la date courante
  api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
    drilldownPositions(positions, title, subtitle);
  });
}

function drilldownMobilizable() {
  api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
    const total = positions.reduce((s, p) => s + (p.mobilizable_value || 0), 0);
    const byLiq = {};
    for (const p of positions) {
      const k = p.liquidity || 'Autre';
      if (!byLiq[k]) byLiq[k] = [];
      byLiq[k].push(p);
    }
    const sections = S.config.liquidity_order
      .filter(l => byLiq[l]?.length)
      .map(l => {
        const sub = byLiq[l];
        const liqTotal = sub.reduce((s, p) => s + (p.mobilizable_value || 0), 0);
        return {
          title: `${l} — ${fmt(liqTotal)}`,
          rows: sub.sort((a, b) => (b.mobilizable_value || 0) - (a.mobilizable_value || 0)).map(p => ({
            name:     p.envelope || p.category,
            sub:      [p.owner, p.establishment].filter(Boolean).join(' · '),
            val:      fmt(p.mobilizable_value),
            pct:      total > 0 ? (p.mobilizable_value / total) * 100 : 0,
            pctLabel: total > 0 ? ((p.mobilizable_value / total) * 100).toFixed(1) + ' %' : '',
          })),
        };
      });
    openDrilldown({ subtitle: 'Liquidité', title: 'Mobilisable', amount: fmt(total), sections });
  });
}

// Toggle récursif d'une ligne et tous ses descendants
function treeToggleRow(row, expand) {
  const children = row.nextElementSibling;
  if (!children || !children.classList.contains('tree-children')) return;
  children.style.display = expand ? '' : 'none';
  const tog = row.querySelector(':scope > .tree-toggle');
  if (tog) tog.textContent = expand ? '▾' : '▸';
  // Propager récursivement
  children.querySelectorAll('.tree-children').forEach(el => {
    el.style.display = expand ? '' : 'none';
  });
  children.querySelectorAll('.tree-toggle').forEach(t => {
    t.textContent = expand ? '▾' : '▸';
  });
}

// hierarchy: owner > etabl > env
// expand à un niveau = ouvrir tous les ancêtres d'abord (sans récursion vers le bas)
// collapse à un niveau = fermer ce niveau + tous ses descendants
// Filtre le contenu d'un arbre par texte : affiche les feuilles qui matchent + leurs ancêtres
function treeFilter(containerId, query) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const q = query.trim().toLowerCase();

  if (!q) {
    // Restaurer l'état normal (tout visible, accordéon non forcé)
    container.querySelectorAll('.tree-owner-section, .tree-children, .tree-row').forEach(el => {
      el.style.display = '';
    });
    container.querySelectorAll('.tree-toggle').forEach(t => t.textContent = '▾');
    return;
  }

  // 1. Cacher tout
  container.querySelectorAll('.tree-owner-section').forEach(s => s.style.display = 'none');
  container.querySelectorAll('.tree-children').forEach(c => c.style.display = 'none');
  container.querySelectorAll('.tree-row').forEach(r => r.style.display = 'none');

  // 2. Pour chaque feuille qui matche, révéler elle + tous les ancêtres
  container.querySelectorAll('.tree-pos-leaf, .tree-cat').forEach(leaf => {
    const text = leaf.textContent.toLowerCase();
    if (!text.includes(q)) return;

    leaf.style.display = '';
    // Remonter les nœuds parents
    let el = leaf.parentElement;
    while (el && el !== container) {
      if (el.classList.contains('tree-children') || el.classList.contains('tree-owner-section')) {
        el.style.display = '';
      }
      if (el.classList.contains('tree-children')) {
        const row = el.previousElementSibling;
        if (row && row.classList.contains('tree-row')) {
          row.style.display = '';
          const tog = row.querySelector('.tree-toggle');
          if (tog) tog.textContent = '▾';
        }
      }
      el = el.parentElement;
    }
  });
}

function treeExpandCollapse(containerId, expand, levelClass = null) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!levelClass) {
    // Tout
    container.querySelectorAll('.tree-owner, .tree-etabl, .tree-env')
      .forEach(row => treeToggleRow(row, expand));
    return;
  }

  if (expand) {
    // Ouvrir les ancêtres nécessaires (sans toucher à leurs descendants autres que le chemin)
    const parents = {
      'tree-env':   ['tree-owner', 'tree-etabl'],
      'tree-etabl': ['tree-owner'],
      'tree-owner': [],
    };
    // Ouvrir les niveaux parents : juste l'immédiat (pas récursif vers le bas)
    for (const parentClass of (parents[levelClass] || [])) {
      container.querySelectorAll('.' + parentClass).forEach(row => {
        const children = row.nextElementSibling;
        if (!children || !children.classList.contains('tree-children')) return;
        children.style.display = '';
        const tog = row.querySelector(':scope > .tree-toggle');
        if (tog) tog.textContent = '▾';
      });
    }
    // Ouvrir le niveau cible (juste son immédiat — pas les enfants en dessous)
    container.querySelectorAll('.' + levelClass).forEach(row => {
      const children = row.nextElementSibling;
      if (!children || !children.classList.contains('tree-children')) return;
      children.style.display = '';
      const tog = row.querySelector(':scope > .tree-toggle');
      if (tog) tog.textContent = '▾';
    });
  } else {
    // Replier ce niveau + tous ses descendants récursivement
    container.querySelectorAll('.' + levelClass).forEach(row => treeToggleRow(row, false));
  }
}

// Attache les listeners d'accordéon (récursifs) sur un container
function wireTreeAccordion(container, skipActionsCheck = false) {
  container.querySelectorAll('.tree-owner, .tree-etabl, .tree-env').forEach(row => {
    row.addEventListener('click', ev => {
      if (!skipActionsCheck && ev.target.closest('.tree-actions')) return;
      const children = row.nextElementSibling;
      if (!children || !children.classList.contains('tree-children')) return;
      const expand = children.style.display === 'none';
      treeToggleRow(row, expand);
    });
  });
}

function doughnutConfig(labels, data) {
  return {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: COLORS.slice(0, labels.length),
        borderWidth: 2,
        borderColor: '#fff',
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'right', labels: { font: { size: 11 }, padding: 10, boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: ctx => {
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const pct = ((ctx.parsed / total) * 100).toFixed(1);
              return ` ${new Intl.NumberFormat('fr-FR').format(Math.round(ctx.parsed))}\u202f€  (${pct}%)`;
            },
          },
        },
      },
    },
  };
}

// ─── Entités ──────────────────────────────────────────────────────────────

async function loadEntities() {
  const lastDate = S.dates[0];
  [S.entities, S.entitySnapshots, S.entityPositions] = await Promise.all([
    api('GET', '/api/entities'),
    api('GET', '/api/entity-snapshots'),
    lastDate ? api('GET', `/api/positions?date=${lastDate}`) : Promise.resolve([]),
  ]);
  renderEntities();
  refreshEntitySelect();
}

// Groupe les snapshots par entity_name pour un accès rapide
function snapshotsByEntity() {
  const map = {};
  for (const s of (S.entitySnapshots || [])) {
    if (!map[s.entity_name]) map[s.entity_name] = [];
    map[s.entity_name].push(s);
  }
  return map;
}

function renderEntities() {
  const tbody = document.getElementById('entities-tbody');
  if (!S.entities.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="9">Aucune entité. Ajoutez une SCI ou indivision.</td></tr>';
    return;
  }
  const snapMap = snapshotsByEntity();
  updateSortIndicators('entities-thead', 'entities');
  tbody.innerHTML = sortArr(S.entities, S.sort.entities.key, S.sort.entities.dir).map(e => {
    const linked   = (S.entityPositions || []).filter(p => p.entity === e.name);
    const totalPct = linked.reduce((s, p) => s + (p.ownership_pct || 0), 0);
    const owners   = linked.map(p =>
      `<span class="badge badge-j27" style="margin:1px 2px">${esc(p.owner)} ${Math.round((p.ownership_pct||0)*100)}%</span>`
    ).join('');
    const warn = linked.length > 0 && Math.abs(totalPct - 1) > 0.01
      ? `<div style="color:var(--danger);font-size:11px;margin-top:3px">⚠ Total ${Math.round(totalPct*100)}% — vérifier les %</div>`
      : '';
    const noLink = linked.length === 0
      ? '<span style="color:var(--text-muted);font-size:12px">Aucune position liée</span>'
      : '';
    const snaps = snapMap[e.name] || [];
    const lastSnap = snaps[0]; // déjà trié DESC par date
    const snapCell = snaps.length
      ? `<button class="btn-icon" style="font-size:11px;padding:.15rem .45rem" data-id="${e.id}" data-name="${esc(e.name)}" data-action="snap-hist">${snaps.length} entrée${snaps.length > 1 ? 's' : ''}<br><span style="color:var(--text-muted)">${fmtDate(lastSnap.date)}</span></button>`
      : '<span style="color:var(--text-muted);font-size:12px">—</span>';
    return `<tr>
      <td><strong>${esc(e.name)}</strong></td>
      <td>${esc(e.type || '—')}</td>
      <td>${esc(e.valuation_mode || '—')}</td>
      <td class="num">${fmt(e.gross_assets)}</td>
      <td class="num ${e.debt > 0 ? 'neg' : ''}">${e.debt > 0 ? fmt(e.debt) : '—'}</td>
      <td class="num ${e.net_assets < 0 ? 'neg' : 'pos'}">${fmt(e.net_assets)}</td>
      <td>${owners}${noLink}${warn}</td>
      <td>${esc(e.comment || '—')}</td>
      <td style="text-align:center">${snapCell}</td>
      <td style="white-space:nowrap">
        <button class="btn-icon add" data-action="add-pos-entity" data-name="${esc(e.name)}" title="Ajouter une position liée à cette entité">+ Position</button>
        <button class="btn-icon edit" data-id="${e.id}" data-action="edit-ent">Éditer</button>
        <button class="btn-icon del"  data-id="${e.id}" data-action="del-ent">Suppr.</button>
      </td>
    </tr>`;
  }).join('');

  tbody.addEventListener('click', onEntTableClick, { once: true });
}

function onEntTableClick(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const id = parseInt(btn.dataset.id);
  if (btn.dataset.action === 'edit-ent')  openEntityModal(id);
  if (btn.dataset.action === 'del-ent')   deleteEntity(id);
  if (btn.dataset.action === 'snap-hist') showEntitySnapshots(btn.dataset.name);
  if (btn.dataset.action === 'add-pos-entity') {
    const entityName = btn.dataset.name;
    // Bascule sur l'onglet Positions et ouvre le modal pré-rempli
    switchTab('positions').then(() => openPosModal(null, { entity: entityName }));
  }
  document.getElementById('entities-tbody').addEventListener('click', onEntTableClick, { once: true });
}

function showEntitySnapshots(entityName) {
  const snaps = (S.entitySnapshots || []).filter(s => s.entity_name === entityName);
  const entity = S.entities.find(e => e.name === entityName);

  const rows = snaps.map(s => {
    const net = (s.gross_assets || 0) - (s.debt || 0);
    return `<tr>
      <td>${fmtDate(s.date)}</td>
      <td class="num">${fmt(s.gross_assets)}</td>
      <td class="num ${s.debt > 0 ? 'neg' : ''}">${s.debt > 0 ? fmt(s.debt) : '—'}</td>
      <td class="num ${net < 0 ? 'neg' : 'pos'}">${fmt(net)}</td>
      <td style="text-align:center">
        <button class="btn-icon del" style="font-size:11px" data-sid="${s.id}" data-action="del-snap">Suppr.</button>
      </td>
    </tr>`;
  }).join('') || '<tr><td colspan="5" style="color:var(--text-muted);padding:.75rem">Aucune valorisation enregistrée.</td></tr>';

  document.getElementById('dd-subtitle').textContent = 'Entité';
  document.getElementById('dd-title').textContent = entityName;
  document.getElementById('dd-amount').textContent = entity ? fmt(entity.net_assets) + ' (actuel)' : '';
  document.getElementById('dd-body').innerHTML = `
    <p style="font-size:13px;color:var(--text-muted);margin-bottom:.75rem">
      Chaque modification de valeur crée une entrée datée. L'historique est utilisé pour reconstituer la valorisation aux dates passées.
    </p>
    <div class="table-scroll">
      <table class="data-table" id="snap-hist-table">
        <thead><tr>
          <th>Date</th>
          <th class="num">Actif brut</th>
          <th class="num">Dette</th>
          <th class="num">Actif net</th>
          <th></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;

  document.getElementById('snap-hist-table').addEventListener('click', async ev => {
    const btn = ev.target.closest('[data-action="del-snap"]');
    if (!btn) return;
    if (!await confirmDialog('Supprimer cette valorisation ?', 'Cette entrée historique sera supprimée définitivement.')) return;
    await api('DELETE', `/api/entity-snapshots/${btn.dataset.sid}`);
    S.entitySnapshots = S.entitySnapshots.filter(s => s.id !== parseInt(btn.dataset.sid));
    showEntitySnapshots(entityName); // refresh panel
    renderEntities(); // refresh table count
  });

  document.getElementById('drilldown-panel').classList.remove('hidden');
}

function openEntityModal(id = null) {
  S.editEntityId = id;
  document.getElementById('entity-modal-title').textContent =
    id ? 'Modifier l\'entité' : 'Ajouter une entité';

  if (id) {
    const e = S.entities.find(x => x.id === id);
    if (!e) return;
    document.getElementById('ent-name').value      = e.name;
    document.getElementById('ent-type').value      = e.type || '';
    document.getElementById('ent-valuation').value = e.valuation_mode || '';
    document.getElementById('ent-gross').value     = e.gross_assets || 0;
    document.getElementById('ent-debt').value      = e.debt || 0;
    document.getElementById('ent-comment').value   = e.comment || '';
  } else {
    document.getElementById('ent-name').value      = '';
    document.getElementById('ent-type').value      = '';
    document.getElementById('ent-valuation').value = '';
    document.getElementById('ent-gross').value     = 0;
    document.getElementById('ent-debt').value      = 0;
    document.getElementById('ent-comment').value   = '';
  }
  updateEntInfo();
  // Avertissement rétroactivité en mode édition
  const warn = document.getElementById('ent-retro-warning');
  if (warn) warn.style.display = id ? '' : 'none';
  document.getElementById('entity-modal').classList.remove('hidden');
  document.getElementById('ent-name').focus();
}

function updateEntInfo() {
  const gross = parseFloat(document.getElementById('ent-gross').value) || 0;
  const debt  = parseFloat(document.getElementById('ent-debt').value) || 0;
  document.getElementById('ent-computed-info').textContent =
    `Actif net entité : ${fmt(gross - debt)}`;
}

async function saveEntity(e) {
  e.preventDefault();
  const data = {
    name:           document.getElementById('ent-name').value.trim(),
    type:           document.getElementById('ent-type').value || null,
    valuation_mode: document.getElementById('ent-valuation').value || null,
    gross_assets:   parseFloat(document.getElementById('ent-gross').value) || 0,
    debt:           parseFloat(document.getElementById('ent-debt').value) || 0,
    comment:        document.getElementById('ent-comment').value || null,
  };
  try {
    if (S.editEntityId) {
      await api('PUT', `/api/entities/${S.editEntityId}`, data);
    } else {
      await api('POST', '/api/entities', data);
    }
    closeModal('entity-modal');
    toast(S.editEntityId ? 'Entité mise à jour' : 'Entité ajoutée');
    await loadEntities();
    refreshEntitySelect();
  } catch (err) {
    alert(`Erreur : ${err.message}`);
  }
}

async function deleteEntity(id) {
  const e = S.entities.find(x => x.id === id);
  const name = e?.name || `Entité #${id}`;
  if (!await confirmDialog(
    `Supprimer l'entité ?`,
    `<strong>${esc(name)}</strong><br>Les positions liées ne seront pas supprimées, mais ne pourront plus résoudre la valeur de cette entité.`
  )) return;
  await api('DELETE', `/api/entities/${id}`);
  toast('Entité supprimée');
  await loadEntities();
  refreshEntitySelect();
}

// ─── Helpers ──────────────────────────────────────────────────────────────

const today = () => new Date().toISOString().slice(0, 10);

// ─── Référentiel ──────────────────────────────────────────────────────────

async function loadReferential() {
  S.referential = await api('GET', '/api/referential');
  renderReferential();
}

function renderReferential() {
  if (!S.referential) return;
  renderRefOwners();
  renderRefCategories();
  renderRefEnvelopes();
  renderRefLists();
  renderRefAlerts();
}

// ── Propriétaires ──────────────────────────────────────────────────────────

function renderRefOwners() {
  const el = document.getElementById('ref-owners-chips');
  if (!el) return;
  const owners = S.referential.owners || [];
  el.innerHTML = owners.map((o, i) => `
    <span class="ref-chip">
      ${esc(o)}
      <button class="chip-del" data-section="owners" data-index="${i}" title="Supprimer">×</button>
    </span>`).join('') + `
    <div style="display:flex;gap:.5rem;align-items:center;margin-top:.25rem">
      <input type="text" id="new-owner-input" class="ref-input" placeholder="Prénom / entité">
      <button class="btn btn-secondary btn-sm" id="btn-add-owner">+ Ajouter</button>
    </div>`;

  el.querySelectorAll('.chip-del[data-section="owners"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const owner = S.referential.owners[parseInt(btn.dataset.index)];
      const posCount = S.positions.filter(p => p.owner === owner).length;
      const fluxCount = S.flux.filter(f => f.owner === owner).length;
      if (posCount || fluxCount) {
        const lines = [];
        if (posCount)  lines.push(`${posCount} position(s)`);
        if (fluxCount) lines.push(`${fluxCount} flux`);
        if (!confirm(`"${owner}" est référencé(e) dans ${lines.join(' et ')}.\nCes données ne seront pas supprimées, mais la personne n'apparaîtra plus dans les filtres.\n\nContinuer ?`)) return;
      }
      S.referential.owners.splice(parseInt(btn.dataset.index), 1);
      renderRefOwners();
    });
  });
  document.getElementById('btn-add-owner')?.addEventListener('click', () => {
    const val = document.getElementById('new-owner-input').value.trim();
    if (!val) return;
    if (S.referential.owners.includes(val)) return;
    S.referential.owners.push(val);
    renderRefOwners();
  });
  document.getElementById('new-owner-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); document.getElementById('btn-add-owner').click(); }
  });
}

// ── Catégories ─────────────────────────────────────────────────────────────

function renderRefCategories() {
  const el = document.getElementById('ref-categories-body');
  if (!el) return;
  const cats = S.referential.categories || [];
  const mob  = S.referential.category_mobilizable || {};
  el.innerHTML = cats.map((cat, i) => `
    <tr>
      <td><input class="ref-input ref-cat-name" data-index="${i}" value="${esc(cat)}" style="width:100%"></td>
      <td style="text-align:right">
        <input class="ref-input ref-cat-mob" data-cat="${esc(cat)}" type="number" min="0" max="100" step="5"
               value="${Math.round((mob[cat] ?? 0.8) * 100)}"
               style="width:65px;text-align:right"> %
      </td>
      <td>
        <button class="btn-icon del" data-section="categories" data-index="${i}">Suppr.</button>
      </td>
    </tr>`).join('') + `
    <tr id="ref-cat-add-row">
      <td><input type="text" id="new-cat-name" class="ref-input" placeholder="Nouvelle catégorie" style="width:100%"></td>
      <td style="text-align:right">
        <input type="number" id="new-cat-mob" class="ref-input" min="0" max="100" step="5" value="80"
               style="width:65px;text-align:right"> %
      </td>
      <td><button class="btn btn-secondary btn-sm" id="btn-add-cat">+ Ajouter</button></td>
    </tr>`;

  // Sync edits live
  el.querySelectorAll('.ref-cat-name').forEach(inp => {
    inp.addEventListener('change', () => {
      const i = parseInt(inp.dataset.index);
      const oldCat = cats[i];
      const newCat = inp.value.trim();
      if (!newCat) return;
      S.referential.categories[i] = newCat;
      if (oldCat !== newCat) {
        S.referential.category_mobilizable[newCat] = S.referential.category_mobilizable[oldCat] ?? 0.8;
        delete S.referential.category_mobilizable[oldCat];
      }
    });
  });
  el.querySelectorAll('.ref-cat-mob').forEach(inp => {
    inp.addEventListener('change', () => {
      S.referential.category_mobilizable[inp.dataset.cat] = parseFloat(inp.value) / 100;
    });
  });
  el.querySelectorAll('.btn-icon.del[data-section="categories"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const i = parseInt(btn.dataset.index);
      const cat = S.referential.categories[i];
      S.referential.categories.splice(i, 1);
      delete S.referential.category_mobilizable[cat];
      renderRefCategories();
    });
  });
  document.getElementById('btn-add-cat')?.addEventListener('click', () => {
    const name = document.getElementById('new-cat-name').value.trim();
    const mob  = parseFloat(document.getElementById('new-cat-mob').value) / 100;
    if (!name) return;
    S.referential.categories.push(name);
    S.referential.category_mobilizable[name] = isNaN(mob) ? 0.8 : mob;
    renderRefCategories();
  });
}

// ── Enveloppes ─────────────────────────────────────────────────────────────

function renderRefEnvelopes() {
  const el = document.getElementById('ref-envelopes-body');
  if (!el) return;
  const meta = S.referential.envelope_meta || {};
  const liqOpts = (S.config?.liquidity_order || ['J0–J1','J2–J7','J8–J30','30J+','Bloqué']).map(l =>
    `<option value="${esc(l)}">${esc(l)}</option>`).join('');
  const envNames = Object.keys(meta);

  el.innerHTML = envNames.map((name, i) => {
    const m = meta[name];
    return `<tr>
      <td><input class="ref-input ref-env-name" data-index="${i}" data-orig="${esc(name)}" value="${esc(name)}" style="width:100%"></td>
      <td>
        <select class="ref-input ref-env-liq" data-env="${esc(name)}" style="width:100%">
          ${(S.config?.liquidity_order || ['J0–J1','J2–J7','J8–J30','30J+','Bloqué']).map(l =>
            `<option value="${esc(l)}"${l === m.liquidity ? ' selected' : ''}>${esc(l)}</option>`
          ).join('')}
        </select>
      </td>
      <td><input class="ref-input ref-env-friction" data-env="${esc(name)}" value="${esc(m.friction || '')}" style="width:100%"></td>
      <td><button class="btn-icon del" data-section="envelopes" data-env="${esc(name)}">Suppr.</button></td>
    </tr>`;
  }).join('') + `
    <tr>
      <td><input type="text" id="new-env-name" class="ref-input" placeholder="Nom de l'enveloppe" style="width:100%"></td>
      <td>
        <select id="new-env-liq" class="ref-input" style="width:100%">${liqOpts}</select>
      </td>
      <td><input type="text" id="new-env-friction" class="ref-input" placeholder="ex: Fiscale" style="width:100%"></td>
      <td><button class="btn btn-secondary btn-sm" id="btn-add-env">+ Ajouter</button></td>
    </tr>`;

  el.querySelectorAll('.ref-env-name').forEach(inp => {
    inp.addEventListener('change', () => {
      const orig   = inp.dataset.orig;
      const newName = inp.value.trim();
      if (!newName || newName === orig) return;
      const existing = meta[orig];
      delete S.referential.envelope_meta[orig];
      S.referential.envelope_meta[newName] = existing;
      inp.dataset.orig = newName;
      // update data-env on sibling cells
      inp.closest('tr').querySelectorAll('[data-env]').forEach(el => el.dataset.env = newName);
    });
  });
  el.querySelectorAll('.ref-env-liq').forEach(sel => {
    sel.addEventListener('change', () => {
      if (S.referential.envelope_meta[sel.dataset.env])
        S.referential.envelope_meta[sel.dataset.env].liquidity = sel.value;
    });
  });
  el.querySelectorAll('.ref-env-friction').forEach(inp => {
    inp.addEventListener('change', () => {
      if (S.referential.envelope_meta[inp.dataset.env])
        S.referential.envelope_meta[inp.dataset.env].friction = inp.value;
    });
  });
  el.querySelectorAll('.btn-icon.del[data-section="envelopes"]').forEach(btn => {
    btn.addEventListener('click', () => {
      delete S.referential.envelope_meta[btn.dataset.env];
      renderRefEnvelopes();
    });
  });
  document.getElementById('btn-add-env')?.addEventListener('click', () => {
    const name = document.getElementById('new-env-name').value.trim();
    const liq  = document.getElementById('new-env-liq').value;
    const fric = document.getElementById('new-env-friction').value.trim();
    if (!name) return;
    S.referential.envelope_meta[name] = { liquidity: liq, friction: fric || 'Mixte' };
    renderRefEnvelopes();
  });
}

// ── Listes simples (types entités, modes valo, types flux) ─────────────────

function renderRefLists() {
  renderRefSimpleList('ref-entity-types',    'entity_types',    'Type d\'entité');
  renderRefSimpleList('ref-valuation-modes', 'valuation_modes', 'Mode de valorisation');
  renderRefSimpleList('ref-flux-types',      'flux_types',      'Type de flux');
}

function renderRefSimpleList(containerId, refKey, placeholder) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const items = S.referential[refKey] || [];
  el.innerHTML = items.map((v, i) => `
    <span class="ref-chip">
      ${esc(v)}
      <button class="chip-del" data-ref-key="${refKey}" data-index="${i}">×</button>
    </span>`).join('') + `
    <div style="display:flex;gap:.5rem;align-items:center;margin-top:.25rem">
      <input type="text" id="new-${containerId}" class="ref-input" placeholder="${esc(placeholder)}">
      <button class="btn btn-secondary btn-sm" id="btn-add-${containerId}">+ Ajouter</button>
    </div>`;

  el.querySelectorAll(`.chip-del[data-ref-key="${refKey}"]`).forEach(btn => {
    btn.addEventListener('click', () => {
      S.referential[refKey].splice(parseInt(btn.dataset.index), 1);
      renderRefSimpleList(containerId, refKey, placeholder);
    });
  });
  document.getElementById(`btn-add-${containerId}`)?.addEventListener('click', () => {
    const val = document.getElementById(`new-${containerId}`)?.value.trim();
    if (!val || S.referential[refKey].includes(val)) return;
    S.referential[refKey].push(val);
    renderRefSimpleList(containerId, refKey, placeholder);
  });
}

// ── Alertes ────────────────────────────────────────────────────────────────

function renderRefAlerts() {
  const el = document.getElementById('ref-alerts-list');
  if (!el) return;
  const alerts = loadUserAlerts();
  const cats   = S.config?.categories || [];

  const metricOptions = `
    <option value="cat_pct">Catégorie — % du patrimoine net</option>
    <option value="cat_abs">Catégorie — montant net (€)</option>
    <option value="net">Patrimoine net total (€)</option>
    <option value="gross">Actifs bruts totaux (€)</option>`;

  if (!alerts.length) {
    el.innerHTML = '<p class="text-muted" style="font-size:12.5px">Aucune alerte configurée.</p>';
  } else {
    el.innerHTML = alerts.map((a, i) => {
      const needsCat = a.metric === 'cat_pct' || a.metric === 'cat_abs';
      const catSel = needsCat
        ? `<select class="filter-select alert-cat" data-i="${i}" style="width:auto">
             ${cats.map(c => `<option value="${esc(c)}" ${a.category === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}
           </select>` : '';
      return `<div class="alert-row" data-i="${i}">
        <input class="ref-input alert-label" data-i="${i}" value="${esc(a.label || '')}" placeholder="Label…" style="width:110px">
        <select class="filter-select alert-metric" data-i="${i}" style="width:auto">${metricOptions.replace(`value="${a.metric}"`, `value="${a.metric}" selected`)}</select>
        ${catSel}
        <select class="filter-select alert-op" data-i="${i}" style="width:60px">
          <option value="<" ${a.op === '<' ? 'selected' : ''}>&lt;</option>
          <option value=">" ${a.op === '>' ? 'selected' : ''}>&gt;</option>
        </select>
        <input class="ref-input alert-threshold" data-i="${i}" type="number" value="${a.threshold || 0}" style="width:80px">
        <button class="btn-icon del alert-del" data-i="${i}">Suppr.</button>
      </div>`;
    }).join('');
  }

  // Listeners
  el.querySelectorAll('.alert-label, .alert-metric, .alert-cat, .alert-op, .alert-threshold').forEach(inp => {
    inp.addEventListener('change', () => {
      const i = parseInt(inp.dataset.i);
      if (inp.classList.contains('alert-label'))     alerts[i].label     = inp.value;
      if (inp.classList.contains('alert-metric'))    { alerts[i].metric  = inp.value; renderRefAlerts(); return; }
      if (inp.classList.contains('alert-cat'))       alerts[i].category  = inp.value;
      if (inp.classList.contains('alert-op'))        alerts[i].op        = inp.value;
      if (inp.classList.contains('alert-threshold')) alerts[i].threshold = parseFloat(inp.value) || 0;
      saveUserAlerts(alerts);
    });
  });
  el.querySelectorAll('.alert-del').forEach(btn => {
    btn.addEventListener('click', () => {
      alerts.splice(parseInt(btn.dataset.i), 1);
      saveUserAlerts(alerts);
      renderRefAlerts();
    });
  });

  const addBtn = document.getElementById('btn-add-alert');
  if (addBtn) {
    addBtn.onclick = () => {
      alerts.push({ label: '', metric: 'cat_pct', category: cats[0] || '', op: '<', threshold: 10 });
      saveUserAlerts(alerts);
      renderRefAlerts();
    };
  }
}

// ── Save ───────────────────────────────────────────────────────────────────

async function saveReferential() {
  const btn = document.getElementById('btn-save-referential');
  if (btn) { btn.disabled = true; btn.textContent = 'Enregistrement…'; }
  try {
    await api('PUT', '/api/referential', S.referential);
    // Recharger la config globale pour mettre à jour les selects partout
    S.config = await api('GET', '/api/config');
    buildSelects();
    refreshEntitySelect();
    const status = document.getElementById('ref-save-status');
    if (status) {
      status.textContent = '✓ Référentiel enregistré.';
      status.className = 'alert alert-success';
      setTimeout(() => { status.textContent = ''; status.className = ''; }, 3000);
    }
  } catch (err) {
    const status = document.getElementById('ref-save-status');
    if (status) { status.textContent = `Erreur : ${err.message}`; status.className = 'alert alert-error'; }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Enregistrer le référentiel'; }
  }
}

async function resetReferential() {
  if (!await confirmDialog(
    'Réinitialiser le référentiel ?',
    'Toutes vos personnalisations (propriétaires, catégories, enveloppes) seront remplacées par les valeurs par défaut.',
    { confirmText: 'Réinitialiser', danger: true }
  )) return;
  await api('PUT', '/api/referential', {
    owners: ['Julien', 'Perrine', 'Adriel', 'Aloïs'],
    categories: ['Cash & dépôts','Monétaire','Obligations','Actions','Immobilier','SCPI','Fond Euro','Produits Structurés','Crypto','Objets de valeur','Autre'],
    category_mobilizable: {'Cash & dépôts':1,'Monétaire':.95,'Obligations':.95,'Actions':.9,'Immobilier':0,'SCPI':0,'Fond Euro':.95,'Produits Structurés':0,'Crypto':.9,'Objets de valeur':0,'Autre':.8},
    envelope_meta: {'Compte courant':{liquidity:'J0–J1',friction:'Aucune'},'Livret A':{liquidity:'J2–J7',friction:'Fiscale'},'LDDS':{liquidity:'J0–J1',friction:'Aucune'},'Livret Bourso+':{liquidity:'J0–J1',friction:'Aucune'},'PEL/CEL':{liquidity:'J8–J30',friction:'Frais'},'PEA':{liquidity:'J2–J7',friction:'Fiscale'},'CTO':{liquidity:'J2–J7',friction:'Fiscale'},'Assurance-vie':{liquidity:'J8–J30',friction:'Mixte'},'PER':{liquidity:'Bloqué',friction:'Fiscale'},'Crypto':{liquidity:'J0–J1',friction:'Décote probable'},'Immobilier':{liquidity:'30J+',friction:'Mixte'},'SCI':{liquidity:'30J+',friction:'Mixte'},'Autre':{liquidity:'30J+',friction:'Mixte'}},
    entity_types: ['SCI','Indivision','Holding','Autre'],
    valuation_modes: ['Valeur de marché',"Prix d'acquisition",'Valeur fiscale','Autre'],
    flux_types: ['Versement','Retrait','Dividende/Intérêt','Frais','Autre'],
  });
  S.referential = await api('GET', '/api/referential');
  S.config = await api('GET', '/api/config');
  buildSelects();
  renderReferential();
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
}

// Appliquer immédiatement pour éviter le flash
(function() {
  const saved = localStorage.getItem('financy_theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.dataset.theme = saved || (prefersDark ? 'dark' : 'light');
})();

// ─── Boot ─────────────────────────────────────────────────────────────────

initTheme();
init().catch(err => console.error('Init error:', err));
