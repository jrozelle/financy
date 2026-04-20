/**
 * Selecteur de colonnes reutilisable pour les tableaux.
 *
 * Usage :
 *   initColumnPicker('positions', 'positions-col-picker', 'positions-thead', {
 *     owner: 'Proprietaire', category: 'Categorie', ...
 *   });
 */

const STORAGE_PREFIX = 'financy_columns_';

export function initColumnPicker(key, buttonId, theadId, columns) {
  const btn = document.getElementById(buttonId);
  if (!btn) return;

  const saved = _load(key);
  // Par defaut toutes visibles
  const state = {};
  for (const col of Object.keys(columns)) {
    state[col] = saved[col] !== undefined ? saved[col] : true;
  }

  // Appliquer l'etat initial
  _apply(theadId, state);

  // Dropdown
  let dropdown = null;

  btn.addEventListener('click', e => {
    e.stopPropagation();
    if (dropdown) { dropdown.remove(); dropdown = null; return; }

    dropdown = document.createElement('div');
    dropdown.className = 'col-picker-dropdown';
    dropdown.innerHTML = Object.entries(columns).map(([col, label]) => `
      <label class="col-picker-item">
        <input type="checkbox" data-col="${col}" ${state[col] ? 'checked' : ''}>
        ${label}
      </label>
    `).join('');

    dropdown.addEventListener('change', ev => {
      const cb = ev.target;
      const col = cb.dataset.col;
      state[col] = cb.checked;
      _apply(theadId, state);
      _save(key, state);
    });

    btn.parentElement.style.position = 'relative';
    btn.parentElement.appendChild(dropdown);

    const close = ev => {
      if (dropdown && !dropdown.contains(ev.target) && ev.target !== btn) {
        dropdown.remove();
        dropdown = null;
        document.removeEventListener('click', close);
      }
    };
    setTimeout(() => document.addEventListener('click', close), 0);
  });
}

function _apply(theadId, state) {
  const thead = document.getElementById(theadId);
  if (!thead) return;
  const ths = thead.querySelectorAll('th[data-sort]');
  ths.forEach(th => {
    const col = th.dataset.sort;
    if (col in state) {
      const idx = [...th.parentElement.children].indexOf(th);
      const hidden = !state[col];
      th.style.display = hidden ? 'none' : '';
      // Masquer aussi les td correspondantes
      const table = thead.closest('table');
      if (table) {
        table.querySelectorAll(`tbody tr`).forEach(tr => {
          const td = tr.children[idx];
          if (td) td.style.display = hidden ? 'none' : '';
        });
      }
    }
  });
}

// Re-appliquer apres un re-render du tbody
export function reapplyColumns(key, theadId) {
  const saved = _load(key);
  if (Object.keys(saved).length) _apply(theadId, saved);
}

function _save(key, state) {
  try { localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(state)); } catch {}
}

function _load(key) {
  try { return JSON.parse(localStorage.getItem(STORAGE_PREFIX + key) || '{}'); } catch { return {}; }
}
