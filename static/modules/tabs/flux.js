import { S } from '../state.js';
import { fmt, fmtDate, esc, sortArr, updateSortIndicators, today } from '../utils.js';
import { api } from '../api.js';
import { confirmDialog, toast, closeModal } from '../dialogs.js';

export async function loadFlux() {
  S.flux = await api('GET', '/api/flux');
  populateFluxFilters();
  renderFlux();
}

function populateFluxFilters() {
  const owners = [...new Set(S.flux.map(f => f.owner))].sort();
  const types  = [...new Set(S.flux.map(f => f.type).filter(Boolean))].sort();
  const cats   = [...new Set(S.flux.map(f => f.category).filter(Boolean))].sort();
  const years  = [...new Set(S.flux.map(f => f.date?.slice(0, 4)).filter(Boolean))].sort().reverse();

  const sel = (id, placeholder, opts) => {
    const cur = document.getElementById(id)?.value;
    document.getElementById(id).innerHTML =
      `<option value="">${placeholder}</option>` +
      opts.map(o => `<option value="${esc(o)}"${o === cur ? ' selected' : ''}>${esc(o)}</option>`).join('');
  };
  sel('flux-filter-owner',    'Toutes les personnes',  owners);
  sel('flux-filter-type',     'Tous les types',        types);
  sel('flux-filter-category', 'Toutes les catégories', cats);
  sel('flux-filter-year',     'Toutes les années',     years);
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
    tbody.innerHTML = '<tr class="empty-row"><td colspan="8">Aucun flux enregistré.</td></tr>';
    if (tfoot) tfoot.innerHTML = '';
    return;
  }
  tbody.innerHTML = flux.map(f => `
    <tr>
      <td>${fmtDate(f.date)}</td>
      <td>${esc(f.owner)}</td>
      <td>${esc(f.envelope || '—')}</td>
      <td>${esc(f.category || '—')}</td>
      <td>${esc(f.type || '—')}</td>
      <td class="num ${f.amount >= 0 ? 'pos' : 'neg'}">${f.amount >= 0 ? '+' : ''}${fmt(f.amount)}</td>
      <td>${esc(f.notes || '—')}</td>
      <td style="white-space:nowrap">
        <button class="btn-icon edit" data-id="${f.id}" data-action="edit-flux">Éditer</button>
        <button class="btn-icon del"  data-id="${f.id}" data-action="del-flux">Suppr.</button>
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
        <td colspan="5" style="font-size:11px;color:var(--text-muted)">
          ${Object.entries(byType).map(([t, v]) =>
            `${esc(t)} : <strong class="${v >= 0 ? 'pos' : 'neg'}">${v >= 0 ? '+' : ''}${fmt(v)}</strong>`
          ).join(' &nbsp;·&nbsp; ')}
        </td>
        <td class="num ${total >= 0 ? 'pos' : 'neg'}" style="font-weight:700">${total >= 0 ? '+' : ''}${fmt(total)}</td>
        <td colspan="2"></td>
      </tr>
      ${ownersActive.length > 1 ? `<tr>
        <td colspan="5" style="font-size:11px;color:var(--text-muted)">
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
    document.getElementById('flux-category').value = f.category || '';
    document.getElementById('flux-type').value     = f.type || '';
    document.getElementById('flux-amount').value   = f.amount;
    document.getElementById('flux-notes').value    = f.notes || '';
  } else {
    document.getElementById('flux-date').value     = today();
    document.getElementById('flux-owner').value    = S.config.owners[0];
    document.getElementById('flux-envelope').value = '';
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
    category: document.getElementById('flux-category').value || null,
    type:     document.getElementById('flux-type').value || null,
    amount:   parseFloat(document.getElementById('flux-amount').value),
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
