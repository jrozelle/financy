import { S } from './state.js';
import { esc } from './utils.js';
import { toast } from './dialogs.js';

const MAX_RETRIES = 2;
const RETRY_DELAY = 800;

export async function api(method, path, body = null, { silent = false, retries = null } = {}) {
  const maxRetries = retries ?? (method === 'GET' ? MAX_RETRIES : 0);
  let lastError;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (method !== 'GET') {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) opts.headers['X-CSRF-Token'] = meta.content;
      }
      if (body) opts.body = JSON.stringify(body);

      const res = await fetch(path, opts);
      if (res.status === 204) return null;

      let data;
      try {
        data = await res.json();
      } catch {
        throw new Error(`Réponse invalide du serveur (${res.status})`);
      }

      if (!res.ok) throw new Error(data.error || res.statusText);
      return data;

    } catch (err) {
      lastError = err;
      const isNetwork = err instanceof TypeError;
      const canRetry = attempt < maxRetries && (isNetwork || err.message.includes('500'));
      if (canRetry) {
        await new Promise(r => setTimeout(r, RETRY_DELAY * (attempt + 1)));
        continue;
      }
      break;
    }
  }

  if (!silent) {
    const msg = lastError instanceof TypeError
      ? 'Erreur réseau — vérifiez votre connexion'
      : lastError.message || 'Erreur inconnue';
    toast(msg, 'error', 5000);
  }
  throw lastError;
}

export function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : '';
}

export function buildSelects() {
  const { owners, categories, envelopes, flux_types, entity_types, valuation_modes } = S.config;
  fill('pos-owner',    owners);
  fill('pos-category', categories);
  fill('pos-envelope', ['', ...envelopes]);
  fill('flux-owner',   owners);
  fill('flux-envelope',['', ...envelopes]);
  fill('flux-type',    flux_types);
  fill('flux-category',['', ...categories]);
  fill('ent-type',      ['', ...entity_types]);
  fill('ent-valuation', ['', ...valuation_modes]);
}

export function refreshEntitySelect() {
  const names = S.entities.map(e => e.name);
  fill('pos-entity-select', ['', ...names]);
}

export function fill(id, opts) {
  document.getElementById(id).innerHTML =
    opts.map(o => `<option value="${esc(o)}">${esc(o) || '—'}</option>`).join('');
}
