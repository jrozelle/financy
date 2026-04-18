import { S } from '../state.js';
import { api } from '../api.js';
import { esc, fmt, destroyChart, getColors, chartBorderColor } from '../utils.js';
import { confirmDialog, toast } from '../dialogs.js';

let _allocChart = null;
let _currentOwner = null;

export async function loadAdvisor() {
  // Remplir le selecteur de proprietaire a partir du referentiel
  const owners = (S.config && S.config.owners) || [];
  const sel = document.getElementById('advisor-owner-select');
  if (!sel) return;
  if (sel.options.length !== owners.length) {
    sel.innerHTML = owners.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('');
  }
  if (!_currentOwner || !owners.includes(_currentOwner)) {
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
  await _loadAllocation(profile);
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
        <button type="button" class="btn-icon del" data-action="del-obj">Suppr.</button>
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
    adjEl.innerHTML = '<div class="text-muted" style="font-size:12.5px">Enregistrez un profil pour calculer l\'allocation cible.</div>';
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
}
