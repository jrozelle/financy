import { esc } from './utils.js';

// ─── Focus trap ────────────────────────────────────────────────────────────
const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

function _trapFocus(container) {
  const handler = (e) => {
    if (e.key !== 'Tab') return;
    const focusable = [...container.querySelectorAll(FOCUSABLE)].filter(el => !el.disabled);
    if (!focusable.length) return;
    const first = focusable[0];
    const last  = focusable[focusable.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first) { e.preventDefault(); last.focus(); }
    } else {
      if (document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  };
  container.addEventListener('keydown', handler);
  return handler;
}

export function confirmDialog(title, message, { confirmText = 'Supprimer', danger = true } = {}) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', title);
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
    _trapFocus(overlay);
    const cleanup = (val) => { overlay.remove(); resolve(val); };
    overlay.querySelector('.confirm-cancel').addEventListener('click', () => cleanup(false));
    overlay.querySelector('.confirm-ok').addEventListener('click', () => cleanup(true));
    overlay.addEventListener('click', e => { if (e.target === overlay) cleanup(false); });
    overlay.addEventListener('keydown', e => { if (e.key === 'Escape') cleanup(false); });
    overlay.querySelector('.confirm-ok').focus();
  });
}

export function promptDialog(title, { defaultValue = '', placeholder = '', inputType = 'text', confirmText = 'OK' } = {}) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', title);
    overlay.innerHTML = `
      <div class="confirm-dialog">
        <div class="confirm-title">${esc(title)}</div>
        <div class="confirm-message">
          <input type="${esc(inputType)}" class="prompt-input" value="${esc(defaultValue)}"
                 placeholder="${esc(placeholder)}" aria-label="${esc(title)}"
                 style="width:100%;padding:.5rem .75rem;border:1px solid var(--border);border-radius:6px;font-size:14px;margin-top:.5rem">
        </div>
        <div class="confirm-actions">
          <button class="btn btn-secondary confirm-cancel">Annuler</button>
          <button class="btn btn-primary confirm-ok">${esc(confirmText)}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    _trapFocus(overlay);
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
  const modal = document.getElementById(id);
  modal.classList.add('hidden');
}

// ─── Focus trap for static HTML modals ─────────────────────────────────────
export function trapModalFocus(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  _trapFocus(modal);
  // Escape key closes the modal
  modal.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeModal(modalId); }
  });
}
