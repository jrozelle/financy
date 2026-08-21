import { S } from '../state.js';
import { fmt, fmtDate, esc, sortArr, updateSortIndicators, today, parseLocaleNumber } from '../utils.js';
import { api } from '../api.js';
import { confirmDialog, toast, closeModal } from '../dialogs.js';
import { saveFilters, loadFilters, clearFilterKey, applyIfValid } from '../filter-persist.js';

export async function loadFlux() {
  S.flux = await api('GET', '/api/flux');
  populateFluxFilters();
  // Sync filtre local avec le selecteur global
  const globalOwner = S.syntheseOwner;
  if (globalOwner && globalOwner !== 'Famille') {
    const sel = document.getElementById('flux-filter-owner');
    if (sel) {
      // Ajouter l'option si elle n'existe pas (personne sans flux)
      if (![...sel.options].some(o => o.value === globalOwner)) {
        sel.add(new Option(globalOwner, globalOwner));
      }
      sel.value = globalOwner;
    }
  }
  renderFlux();
}

function populateFluxFilters() {
  const owners = [...new Set(S.flux.map(f => f.owner))].sort();
  const types  = [...new Set(S.flux.map(f => f.type).filter(Boolean))].sort();
  const cats   = [...new Set(S.flux.map(f => f.category).filter(Boolean))].sort();
  const years  = [...new Set(S.flux.map(f => f.date?.slice(0, 4)).filter(Boolean))].sort().reverse();
  const globalOwner = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : '';

  const saved = loadFilters('flux');
  const sel = (id, placeholder, opts, savedKey) => {
    const cur = id === 'flux-filter-owner'
      ? globalOwner
      : document.getElementById(id)?.value || saved[savedKey] || '';
    document.getElementById(id).innerHTML =
      `<option value="">${placeholder}</option>` +
      opts.map(o => `<option value="${esc(o)}"${o === cur ? ' selected' : ''}>${esc(o)}</option>`).join('');
  };
  sel('flux-filter-owner',    'Toutes les personnes',  owners, 'owner');
  sel('flux-filter-type',     'Tous les types',        types,  'type');
  sel('flux-filter-category', 'Toutes les catégories', cats,   'category');
  sel('flux-filter-year',     'Toutes les années',     years,  'year');

  // Suggestions d'etablissements : ceux deja vus dans les flux et dans les
  // positions, pour eviter les variantes d'orthographe qui creeraient des
  // comptes fantomes ("BoursoBank" vs "Boursorama").
  const dl = document.getElementById('flux-etab-list');
  if (dl) {
    const known = new Set([
      ...S.flux.map(f => f.establishment).filter(Boolean),
      ...(S.positions || []).map(p => p.establishment).filter(Boolean),
    ]);
    dl.innerHTML = [...known].sort().map(e => `<option value="${esc(e)}">`).join('');
  }
}

export function persistFluxFilters() {
  saveFilters('flux', {
    type:     document.getElementById('flux-filter-type')?.value     || '',
    category: document.getElementById('flux-filter-category')?.value || '',
    year:     document.getElementById('flux-filter-year')?.value     || '',
  });
}

export function clearFluxFilters() {
  ['flux-filter-type', 'flux-filter-category', 'flux-filter-year']
    .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  const owner = document.getElementById('flux-filter-owner');
  if (owner) owner.value = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : '';
  clearFilterKey('flux');
}

function filteredFlux() {
  const owner = document.getElementById('flux-filter-owner')?.value;
  const type  = document.getElementById('flux-filter-type')?.value;
  const cat   = document.getElementById('flux-filter-category')?.value;
  const year  = document.getElementById('flux-filter-year')?.value;
  return S.flux.filter(f =>
    (!owner || f.owner    === owner) &&
    (!type  || f.type     === type)  &&
    (!cat   || f.category === cat)   &&
    (!year  || f.date?.startsWith(year))
  );
}

export function renderFlux() {
  const tbody  = document.getElementById('flux-tbody');
  const tfoot  = document.getElementById('flux-tfoot');
  const flux = sortArr(filteredFlux(), S.sort.flux.key, S.sort.flux.dir);
  updateSortIndicators('flux-thead', 'flux');

  if (!flux.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="9">Aucun flux enregistré.</td></tr>';
    if (tfoot) tfoot.innerHTML = '';
    return;
  }
  tbody.innerHTML = flux.map(f => `
    <tr>
      <td>${fmtDate(f.date)}</td>
      <td>${esc(f.owner)}</td>
      <td>${esc(f.envelope || '—')}</td>
      <td>${f.establishment ? esc(f.establishment) : `<span class="badge badge-blk"
        title="Sans établissement, ce flux est réparti au prorata entre les comptes de l'enveloppe : le rendement de chacun en est faussé">à préciser</span>`}</td>
      <td>${esc(f.category || '—')}</td>
      <td>${esc(f.type || '—')}</td>
      <td class="num ${f.amount >= 0 ? 'pos' : 'neg'}">${f.amount >= 0 ? '+' : ''}${fmt(f.amount)}</td>
      <td>${esc(f.notes || '—')}</td>
      <td style="white-space:nowrap">
        <button class="btn-icon edit" data-id="${f.id}" data-action="edit-flux">Éditer</button>
        <button class="btn-icon del"  data-id="${f.id}" data-action="del-flux">Supprimer</button>
      </td>
    </tr>`).join('');

  const total = flux.reduce((s, f) => s + (f.amount || 0), 0);
  const byType  = {};
  const byOwner = {};
  for (const f of flux) {
    const t = f.type || 'Autre';
    byType[t]   = (byType[t]   || 0) + (f.amount || 0);
    byOwner[f.owner] = (byOwner[f.owner] || 0) + (f.amount || 0);
  }
  const ownersActive = Object.keys(byOwner);
  if (tfoot) {
    tfoot.innerHTML = `
      <tr>
        <td colspan="6" style="font-size:11px;color:var(--text-muted)">
          ${Object.entries(byType).map(([t, v]) =>
            `${esc(t)} : <strong class="${v >= 0 ? 'pos' : 'neg'}">${v >= 0 ? '+' : ''}${fmt(v)}</strong>`
          ).join(' &nbsp;·&nbsp; ')}
        </td>
        <td class="num ${total >= 0 ? 'pos' : 'neg'}" style="font-weight:700">${total >= 0 ? '+' : ''}${fmt(total)}</td>
        <td colspan="2"></td>
      </tr>
      ${ownersActive.length > 1 ? `<tr>
        <td colspan="6" style="font-size:11px;color:var(--text-muted)">
          ${ownersActive.map(o =>
            `${esc(o)} : <strong class="${byOwner[o] >= 0 ? 'pos' : 'neg'}">${byOwner[o] >= 0 ? '+' : ''}${fmt(byOwner[o])}</strong>`
          ).join(' &nbsp;·&nbsp; ')}
        </td>
        <td colspan="3"></td>
      </tr>` : ''}`;
  }

  tbody.addEventListener('click', onFluxTableClick, { once: true });
}

function onFluxTableClick(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const id = parseInt(btn.dataset.id);
  if (btn.dataset.action === 'edit-flux') openFluxModal(id);
  if (btn.dataset.action === 'del-flux')  deleteFlux(id);
  document.getElementById('flux-tbody').addEventListener('click', onFluxTableClick, { once: true });
}

export function openFluxModal(id = null) {
  S.editFluxId = id;
  document.getElementById('flux-modal-title').textContent =
    id ? 'Modifier le flux' : 'Ajouter un flux';

  if (id) {
    const f = S.flux.find(x => x.id === id);
    if (!f) return;
    document.getElementById('flux-date').value     = f.date;
    document.getElementById('flux-owner').value    = f.owner;
    document.getElementById('flux-envelope').value = f.envelope || '';
    document.getElementById('flux-establishment').value = f.establishment || '';
    document.getElementById('flux-category').value = f.category || '';
    document.getElementById('flux-type').value     = f.type || '';
    document.getElementById('flux-amount').value   = f.amount;
    document.getElementById('flux-notes').value    = f.notes || '';
  } else {
    document.getElementById('flux-date').value     = today();
    document.getElementById('flux-owner').value    = S.config.owners[0];
    document.getElementById('flux-envelope').value = '';
    document.getElementById('flux-establishment').value = '';
    document.getElementById('flux-category').value = '';
    document.getElementById('flux-type').value     = S.config.flux_types[0];
    document.getElementById('flux-amount').value   = '';
    document.getElementById('flux-notes').value    = '';
  }
  document.getElementById('flux-modal').classList.remove('hidden');
  document.getElementById('flux-amount').focus();
}

export async function saveFlux(e) {
  e.preventDefault();
  const data = {
    date:     document.getElementById('flux-date').value,
    owner:    document.getElementById('flux-owner').value,
    envelope: document.getElementById('flux-envelope').value || null,
    establishment: document.getElementById('flux-establishment').value.trim() || null,
    category: document.getElementById('flux-category').value || null,
    type:     document.getElementById('flux-type').value || null,
    amount:   parseLocaleNumber(document.getElementById('flux-amount').value),
    notes:    document.getElementById('flux-notes').value || null,
  };
  if (S.editFluxId) {
    await api('PUT', `/api/flux/${S.editFluxId}`, data);
  } else {
    await api('POST', '/api/flux', data);
  }
  closeModal('flux-modal');
  toast(S.editFluxId ? 'Flux mis à jour' : 'Flux ajouté');
  await loadFlux();
}

export async function deleteFlux(id) {
  const f = S.flux.find(x => x.id === id);
  const label = f ? `${f.type || 'Flux'} — ${fmt(f.amount)} (${f.owner})` : `Flux #${id}`;
  if (!await confirmDialog('Supprimer ce flux ?', `<strong>${esc(label)}</strong><br>Cette action est irréversible.`)) return;
  await api('DELETE', `/api/flux/${id}`);
  toast('Flux supprimé');
  await loadFlux();
}

// ─── Import d'avis d'operes et de releves d'especes ────────────────────────
// Deux temps : on lit et on montre, l'utilisateur valide, on ecrit. Rien n'est
// insere sans confirmation, et un document deja importe est ecarte.

let _staged = null;   // resultat du dernier apercu, en attente de validation

const _fmtDate = d => d ? d.split('-').reverse().join('/') : '—';
const _eur = v => v == null ? '—'
  : new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v) + ' €';

export function wireFluxImport() {
  const zone = document.getElementById('flux-drop');
  const input = document.getElementById('flux-drop-input');
  if (!zone || !input) return;
  zone.addEventListener('click', () => input.click());
  zone.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); input.click(); }
  });
  ['dragenter', 'dragover'].forEach(e => zone.addEventListener(e, ev => {
    ev.preventDefault(); zone.classList.add('is-over');
  }));
  ['dragleave', 'drop'].forEach(e => zone.addEventListener(e, ev => {
    ev.preventDefault(); zone.classList.remove('is-over');
  }));
  zone.addEventListener('drop', ev => _preview([...(ev.dataTransfer?.files || [])]));
  input.addEventListener('change', ev => {
    _preview([...ev.target.files]);
    ev.target.value = '';   // permet de redeposer le meme fichier
  });
}

/** Personnes proposees a l'import.
 *
 *  Le referentiel et les donnees peuvent divergier — une base de test annonce
 *  "Personne 1..4" alors que les positions sont au nom de leur vrai proprietaire.
 *  Importer sous un nom absent des positions creerait des flux orphelins,
 *  invisibles dans la performance. On propose donc l'union des deux, et le choix
 *  reste affiche et modifiable avant l'enregistrement.
 */
function _ownerChoices() {
  const seen = new Set([
    ...(S.config?.owners || []),
    ...S.flux.map(f => f.owner).filter(Boolean),
    ...(S.positions || []).map(p => p.owner).filter(Boolean),
  ]);
  return [...seen].sort();
}

function _defaultOwner() {
  const global = (S.syntheseOwner && S.syntheseOwner !== 'Famille') ? S.syntheseOwner : null;
  const choices = _ownerChoices();
  // Priorite au filtre global, puis a une personne ayant deja des flux (donc
  // rattachable), en dernier recours au referentiel.
  const withFlux = S.flux.map(f => f.owner).filter(Boolean);
  return global || withFlux[0] || choices[0] || '';
}

function _owner() {
  return document.getElementById('flux-import-owner')?.value || _defaultOwner();
}

/** Etablissement propose : celui que le parseur a devine s'il figure deja dans
 *  les positions, sinon le premier connu. Une variante d'orthographe creerait un
 *  compte distinct de celui des positions, et les flux ne s'y rattacheraient pas. */
function _defaultEtab(summary) {
  const known = summary?.known_establishments || [];
  const devine = _staged?.data?.transactions?.[0]?.establishment
              || _staged?.data?.flux?.[0]?.establishment;
  return known.includes(devine) ? devine : (known[0] || '');
}

function _etab() {
  return document.getElementById('flux-import-etab')?.value || '';
}

async function _send(files, step, owner = null, etab = null) {
  const fd = new FormData();
  fd.append('owner', owner || _owner());
  const e = etab !== null ? etab : _etab();
  if (e) fd.append('establishment', e);
  files.forEach(f => fd.append('files', f));
  const meta = document.querySelector('meta[name="csrf-token"]');
  const res = await fetch(`/api/import/movements?step=${step}`, {
    method: 'POST', body: fd,
    headers: meta ? { 'X-CSRF-Token': meta.content } : {},
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.error || `Import refusé (${res.status})`);
  return data;
}

async function _preview(files) {
  const pdfs = files.filter(f => f.type === 'application/pdf' || /\.pdf$/i.test(f.name));
  if (!pdfs.length) { toast('Déposez des fichiers PDF', 'error'); return; }
  const zone = document.getElementById('flux-drop');
  zone.classList.add('is-busy');
  try {
    const d = await _send(pdfs, 'preview', _defaultOwner(), '');
    _staged = { files: pdfs, data: d };
    _renderReport(d, pdfs.length);
  } catch (e) {
    toast(e.message, 'error');
  } finally {
    zone.classList.remove('is-busy');
  }
}

function _renderReport(d, nfiles) {
  const host = document.getElementById('flux-import-report');
  if (!host) return;
  const s = d.summary;
  const lines = [
    ...d.transactions.map(t => ({
      dup: t.duplicate, reason: t.duplicate_reason, date: t.date,
      kind: t.side === 'ACHAT' ? 'Achat' : 'Vente',
      label: `${t.name || t.isin || '?'}${t.envelope ? ' · ' + t.envelope : ''}`,
      amount: t.net_eur, warn: t.warnings,
    })),
    ...d.flux.map(f => ({
      dup: f.duplicate, reason: f.duplicate_reason, date: f.date,
      kind: f.flux_type, label: f.label || '', amount: f.net_eur, warn: f.warnings,
    })),
  ].sort((a, b) => (a.date || '').localeCompare(b.date || ''));

  const total = s.transactions + s.flux;
  host.className = 'import-report';
  host.innerHTML = `
    <h3>${nfiles} fichier${nfiles > 1 ? 's' : ''} lu${nfiles > 1 ? 's' : ''}</h3>
    <div class="import-tally">
      <span><b>${s.transactions}</b> opération${s.transactions > 1 ? 's' : ''} de titres</span>
      <span><b>${s.flux}</b> flux de trésorerie</span>
      ${s.duplicates ? `<span class="muted"><b>${s.duplicates}</b> déjà enregistré${s.duplicates > 1 ? 's' : ''}, ignoré${s.duplicates > 1 ? 's' : ''}</span>` : ''}
      ${s.warnings ? `<span class="negative"><b>${s.warnings}</b> à vérifier</span>` : ''}
      ${s.unknown_isins?.length ? `<span><b>${s.unknown_isins.length}</b> valeur${s.unknown_isins.length > 1 ? 's' : ''} à créer</span>` : ''}
      ${s.rejected?.length ? `<span class="negative"><b>${s.rejected.length}</b> non reconnu${s.rejected.length > 1 ? 's' : ''}</span>` : ''}
    </div>
    ${s.rejected?.length ? `<div class="import-lines">${s.rejected.map(r =>
      `<div class="import-line"><span>—</span><span class="negative">rejeté</span>
       <span>${esc(r.file)} — ${esc(r.reason)}</span><span></span></div>`).join('')}</div>` : ''}
    ${lines.length ? `<div class="import-lines">${lines.map(l => `
      <div class="import-line ${l.dup ? 'is-dup' : ''}">
        <span>${_fmtDate(l.date)}</span>
        <span>${esc(l.kind || '')}</span>
        <span>${esc(l.label)}${l.dup ? ` <span class="badge badge-blk">${esc(l.reason || 'doublon')}</span>` : ''}${
          l.warn?.length ? ` <span class="badge badge-30" title="${esc(l.warn.join(' · '))}">à vérifier</span>` : ''}</span>
        <span class="num">${_eur(l.amount)}</span>
      </div>`).join('')}</div>` : ''}
    <div class="import-actions">
      <button class="btn btn-primary" id="flux-import-go" ${total ? '' : 'disabled'}>
        ${total ? `Enregistrer ${total} mouvement${total > 1 ? 's' : ''}` : 'Rien à enregistrer'}</button>
      <button class="btn" id="flux-import-cancel">Annuler</button>
      <label class="import-owner">Au nom de
        <select id="flux-import-owner" class="filter-select">
          ${_ownerChoices().map(o =>
            `<option value="${esc(o)}"${o === _defaultOwner() ? ' selected' : ''}>${esc(o)}</option>`).join('')}
        </select>
      </label>
      <label class="import-owner">Établissement
        <select id="flux-import-etab" class="filter-select"
          title="Doit correspondre à l'orthographe employée dans vos positions : une variante créerait un compte distinct, et les versements ne neutraliseraient plus le rendement.">
          ${(s.known_establishments || []).map(e =>
            `<option value="${esc(e)}"${e === _defaultEtab(s) ? ' selected' : ''}>${esc(e)}</option>`).join('')}
        </select>
      </label>
    </div>`;
  host.classList.remove('hidden');
  document.getElementById('flux-import-cancel').addEventListener('click', _clear);
  document.getElementById('flux-import-go').addEventListener('click', _commit);
}

function _clear() {
  _staged = null;
  const host = document.getElementById('flux-import-report');
  if (host) { host.classList.add('hidden'); host.innerHTML = ''; }
}

async function _commit() {
  if (!_staged) return;
  const btn = document.getElementById('flux-import-go');
  btn.disabled = true;
  btn.textContent = 'Enregistrement…';
  try {
    const d = await _send(_staged.files, 'commit', _owner(), _etab());
    const i = d.inserted;
    toast(`${i.flux} flux et ${i.transactions} opération${i.transactions > 1 ? 's' : ''} enregistré${i.transactions > 1 ? 's' : ''}`, 'success');
    _clear();
    await loadFlux();
  } catch (e) {
    toast(e.message, 'error');
    btn.disabled = false;
    btn.textContent = 'Réessayer';
  }
}
