import { S } from './state.js';
import { esc } from './utils.js';

export async function api(method, path, body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (method !== 'GET') {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) opts.headers['X-CSRF-Token'] = meta.content;
  }
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
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
