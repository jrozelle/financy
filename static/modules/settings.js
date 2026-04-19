import { api } from './api.js';
import { closeModal } from './dialogs.js';
import { toast } from './dialogs.js';

let _current = null;

async function _load() {
  try {
    _current = await api('GET', '/api/settings');
  } catch { _current = null; }
}

function _renderStatus() {
  const el = document.getElementById('settings-api-status');
  if (!el || !_current) return;
  if (_current.effective_source === 'db') {
    el.innerHTML = `<span style="color:var(--success)">Active</span> (configuree ici) &mdash; ${_current.anthropic_api_key_masked}`;
  } else if (_current.effective_source === 'env') {
    el.innerHTML = `<span style="color:var(--success)">Active</span> (variable d'environnement)`;
  } else {
    el.innerHTML = `<span style="color:var(--danger)">Non configuree</span> &mdash; l'onglet Conseil fonctionnera en mode mock`;
  }
}

export async function openSettingsModal() {
  await _load();
  const modal = document.getElementById('settings-modal');
  const input = document.getElementById('settings-api-key');
  input.value = '';
  input.type = 'password';
  input.placeholder = _current?.anthropic_api_key_masked || 'sk-ant-api03-...';
  _renderStatus();
  modal.classList.remove('hidden');
  input.focus();
}

export function wireSettingsEvents() {
  document.getElementById('btn-open-settings')?.addEventListener('click', openSettingsModal);
  document.getElementById('settings-modal-overlay')?.addEventListener('click', () => closeModal('settings-modal'));

  document.getElementById('settings-toggle-key-visibility')?.addEventListener('click', () => {
    const input = document.getElementById('settings-api-key');
    input.type = input.type === 'password' ? 'text' : 'password';
  });

  document.getElementById('btn-save-settings')?.addEventListener('click', async () => {
    const input = document.getElementById('settings-api-key');
    const key = input.value.trim();
    try {
      await api('PUT', '/api/settings', { anthropic_api_key: key });
      toast(key ? 'Cle API enregistree' : 'Cle API supprimee');
      closeModal('settings-modal');
    } catch (e) {
      toast(e.message || 'Erreur', 'error');
    }
  });
}
