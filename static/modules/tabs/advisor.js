import { S } from '../state.js';
import { api } from '../api.js';
import { esc, fmt, destroyChart, getColors, chartBorderColor } from '../utils.js';
import { confirmDialog, toast } from '../dialogs.js';
import { updateDemoBadge } from './import-export.js';

// ─── Sidebar scroll-spy ─────────────────────────────────────────────────────
let _scrollSpyObserver = null;
function _installSidebarScrollSpy() {
  if (_scrollSpyObserver) return;
  const links = document.querySelectorAll('.advisor-sidebar-link');
  if (!links.length) return;
  const sections = [...links]
    .map(a => document.getElementById(a.dataset.anchor))
    .filter(Boolean);
  if (!sections.length) return;

  _scrollSpyObserver = new IntersectionObserver(entries => {
    // Prend la section dont le rect est la plus haute dans le viewport
    const visible = entries
      .filter(e => e.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
    if (!visible.length) return;
    const activeId = visible[0].target.id;
    links.forEach(a => a.classList.toggle('is-active', a.dataset.anchor === activeId));
  }, { rootMargin: '-40% 0px -55% 0px', threshold: [0, 0.3, 0.6, 1] });

  sections.forEach(s => _scrollSpyObserver.observe(s));

  // Clic : smooth scroll (complement au href="#id" natif)
  links.forEach(a => {
    a.addEventListener('click', e => {
      const id = a.dataset.anchor;
      const target = document.getElementById(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      // Active immediate tant que l'observer n'a pas reagit
      links.forEach(x => x.classList.toggle('is-active', x === a));
    });
  });
}

let _allocChart = null;
let _currentOwner = null;

export async function loadAdvisor() {
  _installSidebarScrollSpy();
  // Remplir le selecteur de proprietaire a partir du referentiel
  const owners = (S.config && S.config.owners) || [];
  const sel = document.getElementById('advisor-owner-select');
  if (!sel) return;
  if (sel.options.length !== owners.length) {
    sel.innerHTML = owners.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('');
  }
  // Sync avec le selecteur global
  const globalOwner = S.syntheseOwner;
  if (globalOwner && globalOwner !== 'Famille' && owners.includes(globalOwner)) {
    _currentOwner = globalOwner;
  } else if (!_currentOwner || !owners.includes(_currentOwner)) {
    _currentOwner = owners[0] || null;
  }
  sel.value = _currentOwner;
  await _loadOwnerData();
}

async function _loadOwnerData() {
  if (!_currentOwner) return;
  const [profile, objectives] = await Promise.all([
    _loadProfile(),
    _loadObjectives(),
  ]);
  _fillProfileForm(profile);
  _renderObjectives(objectives);
  await Promise.all([
    _loadAllocation(profile),
    _loadMacro(),
    _loadProposals(),
    _loadUsage(),
  ]);
}

async function _loadProfile() {
  try {
    return await api('GET', `/api/advisor/profiles/${encodeURIComponent(_currentOwner)}`,
                     null, { silent: true });
  } catch {
    return null;
  }
}

async function _loadObjectives() {
  try {
    return await api('GET', `/api/advisor/profiles/${encodeURIComponent(_currentOwner)}/objectives`,
                     null, { silent: true });
  } catch {
    return [];
  }
}

function _fillProfileForm(p) {
  p = p || {};
  document.getElementById('adv-horizon').value        = p.horizon_years ?? '';
  document.getElementById('adv-risk').value           = p.risk_tolerance ?? 3;
  document.getElementById('adv-employment').value     = p.employment_type ?? '';
  document.getElementById('adv-pension-age').value    = p.pension_age ?? '';
  document.getElementById('adv-children').value       = p.children_count ?? 0;
  document.getElementById('adv-main-residence').checked = !!p.main_residence_owned;
  document.getElementById('adv-lbo').checked          = !!p.has_lbo;
  document.getElementById('adv-notes').value          = p.notes ?? '';
}

async function saveProfile(e) {
  if (e) e.preventDefault();
  if (!_currentOwner) return;
  const payload = {
    horizon_years: _num('adv-horizon'),
    risk_tolerance: _num('adv-risk'),
    employment_type: document.getElementById('adv-employment').value || null,
    pension_age: _num('adv-pension-age'),
    children_count: _num('adv-children'),
    main_residence_owned: document.getElementById('adv-main-residence').checked,
    has_lbo: document.getElementById('adv-lbo').checked,
    notes: document.getElementById('adv-notes').value.trim(),
  };
  try {
    await api('PUT', `/api/advisor/profiles/${encodeURIComponent(_currentOwner)}`, payload);
    toast('Profil enregistré', 'success');
    await _loadOwnerData();  // recharge allocation (derivee du profil)
  } catch {}
}

function _num(id) {
  const v = document.getElementById(id).value;
  if (v === '' || v === null) return null;
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

// ─── Objectifs ──────────────────────────────────────────────────────────────

function _renderObjectives(list) {
  const tbody = document.getElementById('advisor-objectives-tbody');
  if (!tbody) return;
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:1rem;color:var(--text-muted);font-style:italic">Aucun objectif. Ajoutez une ligne pour documenter vos projets patrimoniaux.</td></tr>';
    return;
  }
  tbody.innerHTML = list.map(o => `
    <tr data-oid="${o.id}">
      <td><input type="text" class="obj-label" value="${esc(o.label || '')}" maxlength="200"></td>
      <td class="num"><input type="number" class="obj-amount" value="${o.target_amount ?? ''}" step="100" min="0"></td>
      <td class="num"><input type="number" class="obj-horizon" value="${o.horizon_years ?? ''}" step="1" min="0" max="100"></td>
      <td>
        <select class="obj-priority">
          ${[1,2,3,4,5].map(p => `<option value="${p}" ${o.priority===p?'selected':''}>${p}</option>`).join('')}
        </select>
      </td>
      <td>
        <button type="button" class="btn-icon" data-action="save-obj">Enregistrer</button>
        <button type="button" class="btn-icon del" data-action="del-obj">Supprimer</button>
      </td>
    </tr>
  `).join('');
}

async function addObjective() {
  if (!_currentOwner) return;
  try {
    await api('POST', `/api/advisor/profiles/${encodeURIComponent(_currentOwner)}/objectives`,
              { label: 'Nouvel objectif', horizon_years: 10, priority: 3 });
    _renderObjectives(await _loadObjectives());
  } catch {}
}

async function saveObjectiveRow(tr) {
  const oid = parseInt(tr.dataset.oid);
  const payload = {
    label:         tr.querySelector('.obj-label').value.trim(),
    target_amount: tr.querySelector('.obj-amount').value ? parseFloat(tr.querySelector('.obj-amount').value) : null,
    horizon_years: tr.querySelector('.obj-horizon').value ? parseInt(tr.querySelector('.obj-horizon').value) : null,
    priority:      parseInt(tr.querySelector('.obj-priority').value),
  };
  if (!payload.label) { toast('Libellé requis', 'error'); return; }
  try {
    await api('PATCH', `/api/advisor/objectives/${oid}`, payload);
    toast('Objectif enregistré', 'success');
  } catch {}
}

async function deleteObjective(tr) {
  const oid = parseInt(tr.dataset.oid);
  const label = tr.querySelector('.obj-label').value;
  if (!await confirmDialog('Supprimer l\'objectif ?', `<strong>${esc(label)}</strong>`,
                            { confirmText: 'Supprimer' })) return;
  try {
    await api('DELETE', `/api/advisor/objectives/${oid}`);
    _renderObjectives(await _loadObjectives());
  } catch {}
}

// ─── Allocation cible vs actuelle ───────────────────────────────────────────

async function _loadAllocation(profile) {
  const wrap = document.getElementById('advisor-allocation-wrap');
  const adjEl = document.getElementById('advisor-adjustments');
  if (!profile) {
    adjEl.innerHTML = `
      <div class="empty-state" style="padding:1rem 0">
        <p class="text-muted" style="font-size:12.5px;margin-bottom:.75rem">
          Enregistre un profil (horizon + tolérance au risque) pour calculer
          l'allocation cible et générer des propositions d'arbitrage.
        </p>
        <a href="#adv-profile" class="btn btn-secondary btn-sm advisor-sidebar-link" data-anchor="adv-profile">
          Remplir le profil &uarr;
        </a>
      </div>`;
    document.getElementById('advisor-gap-tbody').innerHTML = '';
    _allocChart = destroyChart(_allocChart);
    return;
  }
  let data;
  try {
    data = await api('GET', `/api/advisor/profiles/${encodeURIComponent(_currentOwner)}/allocation`,
                     null, { silent: true });
  } catch {
    return;
  }

  // Ajustements contextuels
  if (data.adjustments && data.adjustments.length) {
    adjEl.innerHTML = data.adjustments.map(a => `
      <div class="advisor-adjustment-item">${esc(a)}</div>
    `).join('');
  } else {
    adjEl.innerHTML = '<div class="text-muted" style="font-size:12.5px">Profil standard : aucun ajustement contextuel appliqué.</div>';
  }

  // Tableau d'ecarts
  const tbody = document.getElementById('advisor-gap-tbody');
  if (!data.gap.length || !data.total_eur) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:1rem;color:var(--text-muted);font-style:italic">Pas de positions sur ce propriétaire. Saisissez des positions pour comparer.</td></tr>';
    _allocChart = destroyChart(_allocChart);
    return;
  }
  tbody.innerHTML = data.gap.map(g => {
    const cls = g.delta_eur > 0 ? 'pos' : g.delta_eur < 0 ? 'neg' : '';
    return `<tr>
      <td><strong>${esc(g.category)}</strong></td>
      <td class="num">${(g.target_pct * 100).toFixed(1)}%</td>
      <td class="num">${(g.actual_pct * 100).toFixed(1)}%</td>
      <td class="num ${cls}">${g.delta_pct > 0 ? '+' : ''}${(g.delta_pct * 100).toFixed(1)}%</td>
      <td class="num ${cls}">${g.delta_eur > 0 ? '+' : ''}${fmt(g.delta_eur)}</td>
    </tr>`;
  }).join('');

  _renderAllocationChart(data);
}

function _renderAllocationChart(data) {
  const canvas = document.getElementById('advisor-allocation-chart');
  if (!canvas) return;
  _allocChart = destroyChart(_allocChart);
  const colors = getColors();
  const border = chartBorderColor();

  const categories = data.gap.map(g => g.category);
  const target = data.gap.map(g => +(g.target_pct * 100).toFixed(1));
  const actual = data.gap.map(g => +(g.actual_pct * 100).toFixed(1));

  _allocChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: categories,
      datasets: [
        { label: 'Cible',    data: target, backgroundColor: colors[0] + 'cc', borderColor: colors[0], borderWidth: 1 },
        { label: 'Actuelle', data: actual, backgroundColor: colors[2] + 'cc', borderColor: colors[2], borderWidth: 1 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label} : ${ctx.parsed.y.toFixed(1)}%` } },
      },
      scales: {
        y: { ticks: { callback: v => v + '%', font: { size: 11 } }, grid: { color: border }, beginAtZero: true },
        x: { ticks: { font: { size: 11 } }, grid: { display: false } },
      },
    },
  });
}

// ─── Macro snapshot ─────────────────────────────────────────────────────────

let _currentMacroId = null;
let _llmAvailable = false;
let _llmMock = false;

async function _loadMacro() {
  let data;
  try {
    data = await api('GET', '/api/advisor/macro/latest', null, { silent: true });
  } catch { return; }
  _llmAvailable = !!data.llm_available;
  _llmMock = !!data.llm_mock;
  // Sync global demo badge : LLM mock => badge navbar (sauf si deja en mode demo)
  updateDemoBadge({ llmMock: _llmMock });

  const btn = document.getElementById('btn-macro-refresh');
  if (btn) {
    btn.disabled = !_llmAvailable;
    btn.title = _llmAvailable
      ? (_llmMock ? 'Mode mock : reponse fictive' : 'Appel Claude API')
      : 'ANTHROPIC_API_KEY absente';
  }

  const snap = data.snapshot;
  const empty = document.getElementById('macro-empty');
  const content = document.getElementById('macro-content');
  const meta = document.getElementById('macro-meta');
  if (!snap) {
    _currentMacroId = null;
    empty.style.display = '';
    content.style.display = 'none';
    meta.textContent = '';
    return;
  }
  _currentMacroId = snap.id;
  empty.style.display = 'none';
  content.style.display = '';
  document.getElementById('macro-rates').value     = snap.regime_rates || 'neutre';
  document.getElementById('macro-inflation').value = snap.inflation_view || 'maitrisee';
  document.getElementById('macro-bias').value      = snap.equities_bias || 'neutre';
  document.getElementById('macro-summary').value   = snap.raw_summary || '';
  meta.textContent = `Source : ${snap.source === 'manual' ? 'manuelle' : 'LLM'} · ${snap.date || ''}`;
}

async function refreshMacro() {
  const btn = document.getElementById('btn-macro-refresh');
  const originalLabel = btn.textContent;
  btn.disabled = true;
  btn.classList.add('is-loading');
  btn.textContent = 'Appel Claude…';
  try {
    const r = await api('POST', '/api/advisor/macro/refresh');
    const cost = r.meta?.cost_usd;
    const dur = r.meta?.latency_ms;
    const parts = ['Macro actualisée'];
    if (r.meta?.cached) parts.push('(cache)');
    else if (cost || dur) parts.push(`(${cost ? cost.toFixed(4) + ' $' : ''}${cost && dur ? ', ' : ''}${dur ? (dur / 1000).toFixed(1) + ' s' : ''})`);
    toast(parts.join(' '), 'success');
    await _loadMacro();
  } catch {} finally {
    btn.disabled = false;
    btn.classList.remove('is-loading');
    btn.textContent = originalLabel;
  }
}

async function saveMacro() {
  if (!_currentMacroId) return;
  try {
    await api('PATCH', `/api/advisor/macro/${_currentMacroId}`, {
      regime_rates:   document.getElementById('macro-rates').value,
      inflation_view: document.getElementById('macro-inflation').value,
      equities_bias:  document.getElementById('macro-bias').value,
      raw_summary:    document.getElementById('macro-summary').value,
    });
    toast('Snapshot macro enregistré', 'success');
    await _loadMacro();
  } catch {}
}

// ─── Propositions ───────────────────────────────────────────────────────────

async function _loadProposals() {
  if (!_currentOwner) return;
  const status = document.getElementById('proposals-filter').value;
  const url = status
    ? `/api/advisor/profiles/${encodeURIComponent(_currentOwner)}/proposals?status=${status}`
    : `/api/advisor/profiles/${encodeURIComponent(_currentOwner)}/proposals`;
  let list;
  try {
    list = await api('GET', url, null, { silent: true });
  } catch { return; }
  _renderProposals(list);
}

function _renderProposals(list) {
  const wrap = document.getElementById('proposals-list');
  const empty = document.getElementById('proposals-empty');
  if (!list.length) {
    wrap.innerHTML = '';
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';
  wrap.innerHTML = list.map(p => {
    const cls = `proposal-item kind-${p.kind} status-${p.status}`;
    const amount = p.amount != null ? `<strong>${fmt(p.amount)} €</strong>` : '';
    return `
      <div class="${cls}" data-pid="${p.id}">
        <div class="proposal-head">
          <div>
            <span class="proposal-kind">${esc(p.kind)}</span>
            <strong style="margin-left:.4rem">${esc(p.label)}</strong>
            ${amount ? '· ' + amount : ''}
          </div>
          <div class="proposal-actions">
            ${p.status === 'pending' ? `
              <button type="button" class="btn-icon" data-action="apply">Appliquer</button>
              <button type="button" class="btn-icon" data-action="dismiss">Écarter</button>
            ` : `
              <button type="button" class="btn-icon" data-action="reset">Remettre en attente</button>
            `}
          </div>
        </div>
        ${p.rationale ? `<div class="proposal-rationale">${esc(p.rationale)}</div>` : ''}
      </div>`;
  }).join('');
}

async function refreshProposals() {
  if (!_currentOwner) return;
  const btn = document.getElementById('btn-proposals-refresh');
  const originalLabel = btn.textContent;
  btn.disabled = true;
  btn.classList.add('is-loading');
  btn.textContent = 'Calcul…';
  try {
    const r = await api('POST', `/api/advisor/profiles/${encodeURIComponent(_currentOwner)}/proposals/refresh`);
    toast(`${r.count} proposition(s) générée(s)`, 'success');
    document.getElementById('proposals-filter').value = 'pending';
    await _loadProposals();
  } catch {} finally {
    btn.disabled = false;
    btn.classList.remove('is-loading');
    btn.textContent = originalLabel;
  }
}

async function _patchProposal(pid, status) {
  try {
    await api('PATCH', `/api/advisor/proposals/${pid}`, { status });
    await _loadProposals();
  } catch {}
}

// ─── Usage ─────────────────────────────────────────────────────────────────

async function _loadUsage() {
  let data;
  try {
    data = await api('GET', '/api/advisor/usage', null, { silent: true });
  } catch { return; }
  const el = document.getElementById('advisor-usage-summary');
  if (!el) return;
  const callsToday = data.days.length ? data.days[data.days.length - 1].calls : 0;
  const spent  = data.month_total_usd || 0;
  const budget = data.budget_usd;
  const pct    = (budget && budget > 0) ? Math.min(100, spent / budget * 100) : null;

  let bar = '';
  let warning = '';
  if (budget != null && budget > 0) {
    const barColor = pct >= 100 ? 'var(--danger)'
                   : pct >= 80  ? 'var(--warning)'
                   : 'var(--primary)';
    bar = `
      <div style="margin-top:.5rem">
        <div style="height:6px;background:var(--bg);border-radius:3px;overflow:hidden;border:1px solid var(--border)">
          <div style="height:100%;width:${pct}%;background:${barColor};transition:width .25s"></div>
        </div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:.25rem">
          ${spent.toFixed(4)} $ / ${budget.toFixed(2)} $ (${pct.toFixed(0)} %)
        </div>
      </div>`;
    if (pct >= 80 && pct < 100) {
      warning = `<div class="advisor-budget-warning" style="margin-top:.5rem;padding:.4rem .6rem;border-left:3px solid var(--warning);background:rgba(234,179,8,.1);font-size:12px;border-radius:4px">
        Budget mensuel consommé à ${pct.toFixed(0)} %. Les prochains appels Claude
        passeront toujours, mais envisage d'augmenter <code>ADVISOR_BUDGET_USD</code>.
      </div>`;
    } else if (pct >= 100) {
      warning = `<div class="advisor-budget-warning" style="margin-top:.5rem;padding:.4rem .6rem;border-left:3px solid var(--danger);background:rgba(239,68,68,.1);font-size:12px;border-radius:4px">
        <strong>Budget mensuel dépassé.</strong> Les prochains appels Claude seront bloqués
        jusqu'à augmentation de <code>ADVISOR_BUDGET_USD</code> ou mois suivant.
      </div>`;
    }
  }

  const mode = data.mock_mode ? ' <span class="h-badge h-badge-muted">mock</span>' : '';
  el.innerHTML = `
    Ce mois : <strong>${spent.toFixed(4)} $</strong>${mode}
    · Aujourd'hui : ${callsToday} appel(s)
    ${bar}
    ${warning}
  `;
}

// ─── Wiring ─────────────────────────────────────────────────────────────────

export function wireAdvisorEvents() {
  const form = document.getElementById('advisor-profile-form');
  if (!form) return;
  form.addEventListener('submit', saveProfile);

  document.getElementById('advisor-owner-select').addEventListener('change', async e => {
    _currentOwner = e.target.value;
    await _loadOwnerData();
  });

  document.getElementById('btn-add-objective').addEventListener('click', addObjective);

  document.getElementById('advisor-objectives-tbody').addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const tr = btn.closest('tr[data-oid]');
    if (!tr) return;
    if (btn.dataset.action === 'save-obj') saveObjectiveRow(tr);
    if (btn.dataset.action === 'del-obj')  deleteObjective(tr);
  });

  // Macro
  document.getElementById('btn-macro-refresh')?.addEventListener('click', refreshMacro);
  document.getElementById('btn-macro-save')?.addEventListener('click', saveMacro);

  // Propositions
  document.getElementById('btn-proposals-refresh')?.addEventListener('click', refreshProposals);
  document.getElementById('proposals-filter')?.addEventListener('change', _loadProposals);
  document.getElementById('proposals-list')?.addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const item = btn.closest('.proposal-item');
    const pid = parseInt(item.dataset.pid);
    if (btn.dataset.action === 'apply')   _patchProposal(pid, 'applied');
    if (btn.dataset.action === 'dismiss') _patchProposal(pid, 'dismissed');
    if (btn.dataset.action === 'reset')   _patchProposal(pid, 'pending');
  });
}
