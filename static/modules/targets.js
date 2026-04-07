import { S, _targetsCache, setTargetsCache } from './state.js';
import { api } from './api.js';
import { esc, fmt } from './utils.js';
import { closeModal } from './dialogs.js';

export async function loadTargets() {
  if (_targetsCache !== null) return _targetsCache;
  try {
    setTargetsCache(await api('GET', '/api/targets'));
  } catch {
    try { setTargetsCache(JSON.parse(localStorage.getItem('patrimoine_targets')) || {}); } catch { setTargetsCache({}); }
  }
  return _targetsCache;
}

export async function saveTargets(targets) {
  setTargetsCache(targets);
  try {
    await api('PUT', '/api/targets', targets);
    localStorage.removeItem('patrimoine_targets');
  } catch {
    localStorage.setItem('patrimoine_targets', JSON.stringify(targets));
  }
}

export function wireTargetsEvents() {
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

export async function renderAllocationTargets() {
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
