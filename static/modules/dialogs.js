import { esc } from './utils.js';

export function confirmDialog(title, message, { confirmText = 'Supprimer', danger = true } = {}) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = `
      <div class="confirm-dialog">
        <div class="confirm-title">${esc(title)}</div>
        <div class="confirm-message">${message}</div>
        <div class="confirm-actions">
          <button class="btn btn-secondary confirm-cancel">Annuler</button>
          <button class="btn ${danger ? 'btn-danger' : 'btn-primary'} confirm-ok">${esc(confirmText)}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const cleanup = (val) => { overlay.remove(); resolve(val); };
    overlay.querySelector('.confirm-cancel').addEventListener('click', () => cleanup(false));
    overlay.querySelector('.confirm-ok').addEventListener('click', () => cleanup(true));
    overlay.addEventListener('click', e => { if (e.target === overlay) cleanup(false); });
    overlay.querySelector('.confirm-ok').focus();
  });
}

export function promptDialog(title, { defaultValue = '', placeholder = '', inputType = 'text', confirmText = 'OK' } = {}) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = `
      <div class="confirm-dialog">
        <div class="confirm-title">${esc(title)}</div>
        <div class="confirm-message">
          <input type="${esc(inputType)}" class="prompt-input" value="${esc(defaultValue)}"
                 placeholder="${esc(placeholder)}" style="width:100%;padding:.5rem .75rem;border:1px solid var(--border);border-radius:6px;font-size:14px;margin-top:.5rem">
        </div>
        <div class="confirm-actions">
          <button class="btn btn-secondary confirm-cancel">Annuler</button>
          <button class="btn btn-primary confirm-ok">${esc(confirmText)}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const input = overlay.querySelector('.prompt-input');
    const cleanup = (val) => { overlay.remove(); resolve(val); };
    overlay.querySelector('.confirm-cancel').addEventListener('click', () => cleanup(null));
    overlay.querySelector('.confirm-ok').addEventListener('click', () => cleanup(input.value));
    overlay.addEventListener('click', e => { if (e.target === overlay) cleanup(null); });
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') cleanup(input.value);
      if (e.key === 'Escape') cleanup(null);
    });
    input.focus();
    input.select();
  });
}

export function toast(msg, type = 'success', duration = 3000) {
  const el = document.createElement('div');
  el.className = `toast-msg toast-${type}`;
  el.textContent = msg;
  const container = document.getElementById('toast') || document.body;
  container.appendChild(el);
  requestAnimationFrame(() => el.classList.add('toast-show'));
  setTimeout(() => {
    el.classList.remove('toast-show');
    el.addEventListener('transitionend', () => el.remove());
  }, duration);
}

export function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}
