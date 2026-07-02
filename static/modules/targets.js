import { S, _targetsCache, setTargetsCache } from './state.js';
import { api } from './api.js';
import { esc, fmt, parseLocaleNumber } from './utils.js';
import { closeModal } from './dialogs.js';

export async function loadTargets() {
  if (_targetsCache !== null) return _targetsCache;
  try {
    setTargetsCache(await api('GET', '/api/targets'));
  } catch (err) {
    console.warn('[targets] API load failed, falling back to localStorage:', err);
    try { setTargetsCache(JSON.parse(localStorage.getItem('patrimoine_targets')) || {}); } catch { setTargetsCache({}); }
  }
  return _targetsCache;
}

export async function saveTargets(targets) {
  setTargetsCache(targets);
  try {
    await api('PUT', '/api/targets', targets);
    localStorage.removeItem('patrimoine_targets');
  } catch (err) {
    console.warn('[targets] API save failed, falling back to localStorage:', err);
    localStorage.setItem('patrimoine_targets', JSON.stringify(targets));
  }
}

export function wireTargetsEvents() {
  document.getElementById('btn-edit-targets').addEventListener('click', openTargetsModal);
  document.getElementById('btn-save-targets').addEventListener('click', async () => {
    const targets = {};
    document.querySelectorAll('.target-input').forEach(inp => {
      const val = parseLocaleNumber(inp.value);
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
        <input class="target-input" type="text" inputmode="decimal" min="0" max="100" step="1"
               data-cat="${esc(cat)}" value="${targets[cat] || ''}">
        <span style="font-size:12px;color:var(--text-muted)">%</span>
      </div>`).join('');
  document.getElementById('targets-modal').classList.remove('hidden');
}

let _allocMode = 'net';  // 'net' | 'brut'

function _wireAllocMode(host) {
  host.querySelectorAll('[data-alloc-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      _allocMode = btn.dataset.allocMode;
      renderAllocationTargets();
    });
  });
}

export async function renderAllocationTargets() {
  const host = document.getElementById('allocation-targets');
  const syn = S.synthese;
  if (!syn?.totals_by_category) {
    host.innerHTML = '<p class="text-muted" style="font-size:13px">Aucune donnée.</p>';
    return;
  }
  const targets  = await loadTargets();
  const owner    = S.syntheseOwner;
  const isFamily = owner === 'Famille';
  const useGross = _allocMode === 'brut';

  const totalBase = useGross
    ? (isFamily ? (syn.family.gross || 0) : (syn.totals_by_owner[owner]?.gross || 0))
    : (isFamily ? (syn.family.net   || 0) : (syn.totals_by_owner[owner]?.net   || 0));

  const valOf = cd => useGross
    ? (isFamily ? (cd.gross || 0) : (cd.by_owner_gross?.[owner] || 0))
    : (isFamily ? (cd.net   || 0) : (cd.by_owner?.[owner]       || 0));

  const rows = S.config.categories
    .map(cat => {
      const val = valOf(syn.totals_by_category[cat] || {});
      const actual = totalBase > 0 ? (val / totalBase) * 100 : 0;
      const target = targets[cat] || 0;
      return { cat, val, actual, target, delta: actual - target };
    })
    .filter(r => r.val > 0 || r.target > 0)
    .sort((a, b) => b.val - a.val);

  // Switch Net/Brut dans l'en-tete de la carte (a cote de "Modifier cibles")
  const switchEl = document.getElementById('alloc-mode-switch');
  if (switchEl) {
    switchEl.innerHTML = `<span style="display:inline-flex;border:1px solid var(--border);border-radius:6px;overflow:hidden;font-size:12px;vertical-align:middle">
      ${['net', 'brut'].map(m => `<button type="button" data-alloc-mode="${m}" style="padding:.2rem .6rem;border:none;cursor:pointer;background:${m === _allocMode ? 'var(--primary)' : 'transparent'};color:${m === _allocMode ? '#fff' : 'var(--text)'}">${m === 'net' ? 'Net' : 'Brut'}</button>`).join('')}
    </span>`;
    _wireAllocMode(switchEl);
  }

  if (!rows.length) {
    host.innerHTML =
      '<p class="text-muted" style="font-size:13px">Cliquez sur "Modifier cibles" pour configurer.</p>';
    return;
  }

  host.innerHTML = `
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
