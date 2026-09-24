import { S, _targetsCache, setTargetsCache } from './state.js';
import { api } from './api.js';
import { esc, parseLocaleNumber } from './utils.js';
import { closeModal } from './dialogs.js';

/** Ecart en points de pourcentage, a la francaise : « +2,5 pt ». */
const _nfPt = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
function _fmtPoints(v) {
  const s = _nfPt.format(Math.abs(v));
  const signe = s === '0,0' ? '' : v > 0 ? '+' : '−';
  return `${signe}${s}\u202fpt`;
}

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
  document.getElementById('btn-save-targets').addEventListener('click', async () => {
    const targets = {};
    document.querySelectorAll('.target-input').forEach(inp => {
      const val = parseLocaleNumber(inp.value);
      if (!isNaN(val) && val > 0) targets[inp.dataset.cat] = val;
    });
    await saveTargets(targets);
    closeModal('targets-modal');
    // La carte « Ecart a la cible » (Svelte) relit les cibles.
    window.dispatchEvent(new CustomEvent('cibles:modifiees'));
  });
  document.getElementById('targets-modal-overlay').addEventListener('click', () => closeModal('targets-modal'));
}

/** Fenetre de saisie des cibles, ouverte par la carte « Ecart a la cible ». */
export async function openTargetsModal() {
  const targets = await loadTargets();
  document.getElementById('targets-form-grid').innerHTML =
    S.config.categories.map(cat => `
      <div class="target-row">
        <label>${esc(cat)}</label>
        <input class="target-input" type="text" inputmode="decimal" min="0" max="100" step="1"
               data-cat="${esc(cat)}" value="${targets[cat] || ''}">
        <span style="font-size:var(--fs-xs);color:var(--text-muted)">%</span>
      </div>`).join('');
  document.getElementById('targets-modal').classList.remove('hidden');
}
