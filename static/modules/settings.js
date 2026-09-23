import { api } from './api.js';
import { closeModal, toast, confirmDialog } from './dialogs.js';
import { esc } from './utils.js';

let _current = null;

async function _load() {
  try {
    _current = await api('GET', '/api/settings');
  } catch { _current = null; }
}

function _renderStatus() {
  const el = document.getElementById('settings-api-status');
  if (!el || !_current) return;
  if (_current.effective_source === 'fichier') {
    el.innerHTML = `<span style="color:var(--success)">Active</span> (configurée ici, hors de la base et des sauvegardes) &mdash; ${esc(_current.anthropic_api_key_masked)}`;
  } else if (_current.effective_source === 'env') {
    el.innerHTML = `<span style="color:var(--success)">Active</span> (variable d'environnement)`;
  } else {
    el.innerHTML = `<span style="color:var(--danger)">Non configurée</span> &mdash; l'onglet Conseil fonctionnera en mode simulé`;
  }
  // Seule une cle enregistree ici se supprime ici ; celle de l'environnement,
  // non.
  document.getElementById('btn-delete-api-key')?.classList.toggle('hidden', !_current.anthropic_api_key_set);
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

  // Le champ s'ouvre vide (la cle n'est jamais renvoyee au navigateur) :
  // enregistrer sans rien saisir envoyait '', que le serveur lisait comme une
  // suppression. Un champ vide ne change plus rien ; supprimer est un bouton.
  document.getElementById('btn-save-settings')?.addEventListener('click', async () => {
    const input = document.getElementById('settings-api-key');
    const key = input.value.trim();
    if (!key) { closeModal('settings-modal'); return; }
    try {
      await api('PUT', '/api/settings', { anthropic_api_key: key });
      toast('Clé API enregistrée');
      closeModal('settings-modal');
    } catch (e) {
      toast(e.message || 'Erreur', 'error');
    }
  });
  document.getElementById('btn-delete-api-key')?.addEventListener('click', async () => {
    const ok = await confirmDialog('Supprimer la clé API ?',
      'L’analyse de l’onglet Conseil repassera en mode simulé.', { confirmText: 'Supprimer', danger: true });
    if (!ok) return;
    try {
      await api('PUT', '/api/settings', { anthropic_api_key: '' });
      toast('Clé API supprimée');
      closeModal('settings-modal');
    } catch (e) { toast(e.message || 'Erreur', 'error'); }
  });
}
