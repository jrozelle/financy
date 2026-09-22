import { S, _targetsCache, setTargetsCache } from './state.js';
import { api } from './api.js';
import { esc, fmt, parseLocaleNumber, fmtPct } from './utils.js';
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
      ${['net', 'brut'].map(m => `<button type="button" data-alloc-mode="${m}" style="padding:.2rem .6rem;border:none;cursor:pointer;background:${m === _allocMode ? 'var(--primary)' : 'transparent'};color:${m === _allocMode ? 'var(--on-accent)' : 'var(--text)'}">${m === 'net' ? 'Net' : 'Brut'}</button>`).join('')}
    </span>`;
    _wireAllocMode(switchEl);
  }

  if (!rows.length) {
    host.innerHTML =
      '<p class="text-muted" style="font-size:13px">Cliquez sur "Modifier cibles" pour configurer.</p>';
    return;
  }

  // Le nom au-dessus, la barre en dessous : la grille a cinq colonnes serrait
  // les libelles sur 130 px et les tronquait. L'ecart en POINTS remplace les
  // trois colonnes reel / cible / ecart — « 31,3 % · −3,7 pt » dit tout, et le
  // trait sur la barre montre la cible sans avoir a la lire.
  host.innerHTML = `
    <div class="cible-liste">
      ${rows.map(r => {
        const reel = Math.min(100, r.actual);
        const cible = r.target ? Math.min(100, r.target) : null;
        const ecart = r.target === 0 ? null : r.delta;
        const classe = ecart === null ? '' : ecart > 2 ? 'trop' : ecart < -2 ? 'pas-assez' : 'ok';
        return `
        <div class="cible-ligne">
          <span class="cible-n">${esc(r.cat)}</span>
          <span class="cible-v">
            <span class="num">${fmtPct(r.actual)}</span>
            ${ecart === null ? '<span class="cible-none">pas de cible</span>'
              : `<span class="cible-ecart cible-ecart--${classe}">${
                  ecart > 0 ? '+' : '−'}${Math.abs(ecart).toFixed(1)}\u202fpt</span>`}
          </span>
          <span class="cible-track">
            <span class="cible-fill" style="width:${reel.toFixed(1)}%"></span>
            ${cible !== null ? `<span class="cible-marque" style="left:${cible.toFixed(1)}%"
                 title=""></span>` : ''}
          </span>
        </div>`;
      }).join('')}
    </div>`;
}
