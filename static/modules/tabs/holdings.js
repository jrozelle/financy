import { api } from '../api.js';
import { esc, fmt } from '../utils.js';
import { closeModal, confirmDialog, toast } from '../dialogs.js';
import { loadPositions } from './positions.js';
import { openIsinPopover } from '../isin-popover.js';

// Etat interne de la modale : position courante + liste de lignes (draft).
// Chaque ligne a un `draftId` local (index) et optionnellement un `id` DB.
let state = {
  positionId: null,
  positionLabel: '',
  rows: [],
  nextDraftId: 0,
};

// Indique que l'utilisateur a modifie le brouillon depuis la derniere ouverture
// ou le dernier save. Utilise par confirmCloseHoldings() pour eviter de perdre
// les edits par erreur (overlay/Escape/X/Annuler).
let _dirty = false;

function _markDirty() { _dirty = true; }
function _markClean() { _dirty = false; }

export function isHoldingsDirty() { return _dirty; }

/**
 * Tente de fermer la modale holdings. Si le brouillon est dirty, demande
 * confirmation. Retourne true si la modale a été fermée, false sinon.
 */
export async function confirmCloseHoldings() {
  const modal = document.getElementById('holdings-modal');
  if (!modal || modal.classList.contains('hidden')) return true;
  if (_dirty) {
    const ok = await confirmDialog(
      'Brouillon non enregistré',
      'Vos modifications n\'ont pas été sauvegardées. <strong>Fermer quand même ?</strong>',
      { confirmText: 'Fermer sans sauvegarder', danger: true }
    );
    if (!ok) return false;
  }
  closeModal('holdings-modal');
  _markClean();
  return true;
}

const PSEUDO_ISIN_PREFIXES = ['FONDS_EUROS_', 'CUSTOM_'];

function isPseudoIsin(isin) {
  if (!isin) return false;
  const u = isin.toUpperCase();
  return PSEUDO_ISIN_PREFIXES.some(p => u.startsWith(p));
}

function makeRow(h = {}) {
  return {
    draftId:         state.nextDraftId++,
    id:              h.id ?? null,
    isin:            h.isin ?? '',
    name:            h.name ?? '',
    ticker:          h.ticker ?? '',
    quantity:        h.quantity ?? '',
    cost_basis:      h.cost_basis ?? '',
    market_value:    h.market_value ?? '',
    is_priceable:    h.is_priceable ?? null,
    last_price:      h.last_price ?? null,
    last_price_date: h.last_price_date ?? null,
    confidence:      h.confidence ?? null,
    asset_class:     h.asset_class ?? null,
  };
}

function _freshnessFromDate(lastPriceDate) {
  if (!lastPriceDate) return 'unknown';
  const last = new Date(lastPriceDate);
  if (isNaN(last)) return 'unknown';
  const ageDays = (Date.now() - last.getTime()) / (1000 * 60 * 60 * 24);
  if (ageDays < 1) return 'fresh';
  if (ageDays < 7) return 'stale';
  return 'expired';
}

export async function openHoldingsModal(positionId, positionLabel = '') {
  state = {
    positionId,
    positionLabel,
    rows: [],
    nextDraftId: 0,
  };

  const modal = document.getElementById('holdings-modal');
  if (!modal) {
    toast('Modale holdings introuvable', 'error');
    return;
  }

  document.getElementById('holdings-modal-title').textContent =
    `Gérer les lignes${positionLabel ? ' — ' + positionLabel : ''}`;

  try {
    const data = await api('GET', `/api/positions/${positionId}/holdings`);
    state.rows = (data.holdings || []).map(makeRow);
  } catch {
    return;
  }

  _markClean();  // fraichement ouverte = propre
  renderHoldingsTable();
  modal.classList.remove('hidden');
  const firstInput = modal.querySelector('input, button');
  firstInput?.focus();
}

function renderHoldingsTable() {
  const tbody = document.getElementById('holdings-tbody');
  if (state.rows.length === 0) {
    tbody.innerHTML = `
      <tr class="empty-row"><td colspan="7">
        Aucune ligne. Cliquez sur « Ajouter une ligne » pour commencer.
      </td></tr>`;
    renderTotals();
    return;
  }
  tbody.innerHTML = state.rows.map(r => rowHtml(r)).join('');
  renderTotals();
}

function rowHtml(r) {
  const pseudo = isPseudoIsin(r.isin);
  const freshness = _freshnessBadge(r);
  const openBtn = (r.id && r.isin)
    ? `<button type="button" class="h-isin-btn" data-action="open-popover" data-isin="${esc(r.isin)}" title="Voir le cours et l'historique">${esc(r.isin)}</button>`
    : '';
  // Lignes issues d'un import PDF/CSV : highlight selon confiance
  let confClass = '';
  let confBadge = '';
  if (r.confidence != null) {
    if (r.confidence < 0.5)      { confClass = 'row-low-conf';  confBadge = `<span class="h-badge h-badge-expired" title="Confiance ${(r.confidence * 100).toFixed(0)} % — verifier les valeurs">à vérifier</span>`; }
    else if (r.confidence < 0.8) { confClass = 'row-mid-conf';  confBadge = `<span class="h-badge h-badge-stale"   title="Confiance ${(r.confidence * 100).toFixed(0)} %">moyen</span>`; }
    else                         { confClass = 'row-high-conf'; }
  }
  return `
    <tr data-draft="${r.draftId}" class="${confClass}">
      <td>
        <input type="text" class="h-input h-isin" value="${esc(r.isin)}"
               list="holdings-isin-list"
               placeholder="FR0000000000 ou FONDS_EUROS_..."
               autocomplete="off" spellcheck="false"
               style="text-transform:uppercase;min-width:140px">
        ${openBtn ? `<div style="margin-top:2px">${openBtn}</div>` : ''}
        ${freshness} ${confBadge}
      </td>
      <td>
        <input type="text" class="h-input h-name" value="${esc(r.name || '')}"
               placeholder="Nom du titre" style="min-width:180px">
      </td>
      <td>
        <input type="number" class="h-input h-qty num" value="${r.quantity}"
               step="any" min="0" placeholder="0">
      </td>
      <td>
        <input type="number" class="h-input h-cost num" value="${r.cost_basis ?? ''}"
               step="0.01" min="0" placeholder="Coût total">
      </td>
      <td>
        <input type="number" class="h-input h-mv num" value="${r.market_value ?? ''}"
               step="0.01" min="0" placeholder="Valo">
      </td>
      <td class="num">${_pnlCell(r)}</td>
      <td>
        <button type="button" class="btn-icon del" data-action="remove-line" data-draft="${r.draftId}">Supprimer</button>
      </td>
    </tr>`;
}

function _freshnessBadge(r) {
  if (r.is_priceable === false) {
    return '<span class="h-badge h-badge-muted" title="Non coté (fonds euros, actif custom)">non coté</span>';
  }
  if (r.last_price == null) return '';
  const f = _freshnessFromDate(r.last_price_date);
  const cls = f === 'fresh' ? 'h-badge-fresh'
            : f === 'stale' ? 'h-badge-stale'
            : f === 'expired' ? 'h-badge-expired' : 'h-badge-muted';
  const label = f === 'fresh' ? 'à jour'
              : f === 'stale' ? 'vieillissant'
              : f === 'expired' ? 'périmé' : 'coté';
  const title = r.last_price_date ? `Dernier cours : ${r.last_price} le ${r.last_price_date}` : 'Cours connu';
  return `<span class="h-badge ${cls}" title="${esc(title)}">${label}</span>`;
}

function _pnlCell(r) {
  const qty  = parseFloat(r.quantity) || 0;
  const mv   = parseFloat(r.market_value);
  const cost = parseFloat(r.cost_basis);
  if (!qty || isNaN(cost) || cost <= 0) return '—';
  const currentValue = !isNaN(mv) ? mv : (r.last_price != null ? qty * r.last_price : null);
  if (currentValue == null) return '—';
  const pnl = currentValue - cost;
  const pct = (pnl / cost) * 100;
  const cls = pnl >= 0 ? 'pos' : 'neg';
  return `<span class="${cls}">${fmt(pnl)} (${pct.toFixed(1)}%)</span>`;
}

function renderTotals() {
  const totalMv = state.rows.reduce((s, r) => s + (parseFloat(r.market_value) || 0), 0);
  const totalCost = state.rows.reduce((s, r) => s + (parseFloat(r.cost_basis) || 0), 0);
  const pnl = totalMv - totalCost;
  const pct = totalCost > 0 ? (pnl / totalCost * 100) : 0;
  const foot = document.getElementById('holdings-tfoot');
  if (!foot) return;
  foot.innerHTML = `
    <tr>
      <td colspan="3">TOTAL</td>
      <td class="num">${fmt(totalCost)}</td>
      <td class="num">${fmt(totalMv)}</td>
      <td class="num ${pnl >= 0 ? 'pos' : 'neg'}">${fmt(pnl)}${totalCost > 0 ? ` (${pct.toFixed(1)}%)` : ''}</td>
      <td></td>
    </tr>`;
}

// ─── Lecture des inputs dans state ───────────────────────────────────────────

function collectFromInputs() {
  document.querySelectorAll('#holdings-tbody tr[data-draft]').forEach(tr => {
    const draftId = parseInt(tr.dataset.draft);
    const row = state.rows.find(r => r.draftId === draftId);
    if (!row) return;
    row.isin         = tr.querySelector('.h-isin').value.trim().toUpperCase();
    row.name         = tr.querySelector('.h-name').value.trim();
    row.quantity     = tr.querySelector('.h-qty').value;
    row.cost_basis   = tr.querySelector('.h-cost').value;
    row.market_value = tr.querySelector('.h-mv').value;
  });
}

// ─── Actions ─────────────────────────────────────────────────────────────────

function addLine() {
  collectFromInputs();
  state.rows.push(makeRow());
  _markDirty();
  renderHoldingsTable();
  const tbody = document.getElementById('holdings-tbody');
  const lastIsin = tbody.querySelector('tr:last-child .h-isin');
  lastIsin?.focus();
}


function removeLine(draftId) {
  collectFromInputs();
  state.rows = state.rows.filter(r => r.draftId !== draftId);
  _markDirty();
  renderHoldingsTable();
}

async function saveAll() {
  collectFromInputs();
  // Auto-snapshot si besoin
  try { await api('POST', '/api/auto-snapshot', {}, { silent: true }); } catch {}

  // Validation client basique avant envoi
  for (let i = 0; i < state.rows.length; i++) {
    const r = state.rows[i];
    if (!r.isin) {
      toast(`Ligne ${i + 1} : ISIN manquant`, 'error');
      return;
    }
    const qty = parseFloat(r.quantity);
    if (!qty || qty <= 0) {
      toast(`Ligne ${i + 1} : quantité doit être > 0`, 'error');
      return;
    }
  }

  const payload = {
    holdings: state.rows.map(r => {
      const isin = r.isin.trim().toUpperCase();
      const h = {
        isin,
        quantity: parseFloat(r.quantity),
      };
      if (r.name) h.name = r.name;
      if (r.cost_basis !== '' && r.cost_basis != null) h.cost_basis = parseFloat(r.cost_basis);
      if (r.market_value !== '' && r.market_value != null) h.market_value = parseFloat(r.market_value);
      if (isPseudoIsin(isin)) h.is_priceable = false;
      if (r.asset_class) h.asset_class = r.asset_class;
      return h;
    }),
  };

  try {
    await api('PUT', `/api/positions/${state.positionId}/holdings`, payload);
    toast('Lignes enregistrées', 'success');
    _markClean();
    closeModal('holdings-modal');
    await loadPositions();
  } catch {
    // toast deja affiche par api()
  }
}

// ─── ISIN autocomplete via datalist ──────────────────────────────────────────

let _searchTimer = null;
async function onIsinInput(e) {
  const input = e.target.closest('.h-isin');
  if (!input) return;
  const q = input.value.trim();
  if (q.length < 2) return;
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(async () => {
    try {
      const results = await api('GET', `/api/securities?q=${encodeURIComponent(q)}&limit=20`,
                                null, { silent: true });
      const list = document.getElementById('holdings-isin-list');
      if (list && Array.isArray(results)) {
        list.innerHTML = results
          .map(s => `<option value="${esc(s.isin)}">${esc(s.name || '')}</option>`)
          .join('');
      }
      // Si l'ISIN saisi est connu, pre-remplir nom/ticker de la ligne
      const match = results.find(s => s.isin.toUpperCase() === q.toUpperCase());
      if (match) {
        const tr = input.closest('tr[data-draft]');
        const nameInput = tr?.querySelector('.h-name');
        if (nameInput && !nameInput.value) nameInput.value = match.name || '';
      }
    } catch {}
  }, 250);
}

// ─── Event wiring ────────────────────────────────────────────────────────────

// ─── Import par copier-coller ────────────────────────────────────────────────

async function openPasteDialog() {
  if (!state.positionId) {
    toast('Ouvrez d\'abord la modale d\'une position', 'error');
    return;
  }
  const { promptDialog } = await import('../dialogs.js');
  const text = await promptDialog('Coller le texte depuis le navigateur', {
    placeholder: 'Selectionnez les lignes sur le site de votre courtier, copiez (Ctrl+C) et collez ici (Ctrl+V)',
    inputType: 'textarea',
    confirmText: 'Analyser',
  });
  if (!text) return;

  const status = document.getElementById('holdings-import-status');
  if (status) status.innerHTML = '<span class="text-muted">Analyse du texte…</span>';

  try {
    const data = await api('POST',
      `/api/envelope/${state.positionId}/import-paste`,
      { text });
    if (!data.lines || !data.lines.length) {
      toast('Aucune ligne detectee dans le texte', 'error');
      if (status) status.innerHTML = '';
      return;
    }
    state.rows = (data.lines || []).map(l => makeRow({
      isin: l.isin, name: l.name, quantity: l.quantity,
      cost_basis: l.cost_basis, market_value: l.market_value,
      asset_class: l.asset_class,
    }));
    renderHoldingsTable();
    if (status) {
      status.innerHTML = `<strong>${data.source_label}</strong> · ${data.lines.length} ligne(s) — verifiez puis Enregistrer.`;
    }
    toast(`${data.lines.length} ligne(s) detectee(s)`, 'success');
  } catch (err) {
    toast(err.message || 'Erreur', 'error');
    if (status) status.innerHTML = '';
  }
}

// ─── Import PDF / CSV ───────────────────────────────────────────────────────

async function openPdfPicker() {
  const input = document.getElementById('holdings-pdf-input');
  if (!input) return;
  input.value = '';
  input.click();
}

async function onPdfSelected(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  if (!state.positionId) {
    toast('Ouvrez d\'abord la modale d\'une position', 'error');
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    toast('Fichier trop volumineux (>5 Mo)', 'error');
    return;
  }
  const status = document.getElementById('holdings-import-status');
  const isCsv = file.name.toLowerCase().endsWith('.csv');
  if (status) status.innerHTML = `<span class="text-muted">Analyse du ${isCsv ? 'CSV' : 'PDF'}…</span>`;

  const fd = new FormData();
  fd.append('file', file);
  const meta = document.querySelector('meta[name="csrf-token"]');

  let data;
  try {
    const res = await fetch(
      `/api/envelope/${state.positionId}/import-pdf?step=preview`,
      {
        method: 'POST',
        headers: { 'X-CSRF-Token': meta ? meta.content : '' },
        body: fd,
      }
    );
    data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Echec du parsing');
  } catch (err) {
    toast(err.message || 'Erreur lors de l\'analyse du fichier', 'error');
    if (status) status.innerHTML = '';
    return;
  }

  // Remplit le draft avec les lignes detectees
  state.rows = (data.lines || []).map(l => makeRow({
    isin:         l.isin,
    name:         l.name,
    quantity:     l.quantity,
    cost_basis:   l.cost_basis,
    market_value: l.market_value,
    confidence:   l.confidence,
    asset_class:  l.asset_class,
  }));
  _markDirty();
  renderHoldingsTable();

  // Statut : format detecte + warnings + action a faire
  const lines = data.lines || [];
  const lowConf = lines.filter(l => (l.confidence || 0) < 0.5).length;
  const parts = [
    `<strong>${esc(data.source_label || 'Format inconnu')}</strong>`,
    `${lines.length} ligne(s) détectée(s)`,
  ];
  if (lowConf) parts.push(`<span style="color:var(--warning)">${lowConf} à faible confiance</span>`);
  if (data.warnings && data.warnings.length) {
    parts.push(`<span style="color:var(--warning)">${esc(data.warnings[0])}</span>`);
  }
  if (status) {
    status.innerHTML = parts.join(' · ') +
      ' — vérifiez le tableau puis cliquez Enregistrer pour <strong>remplacer</strong> les lignes existantes.';
  }
  toast(`${lines.length} ligne(s) detectee(s)`, 'success');
}

export function wireHoldingsEvents() {
  const modal = document.getElementById('holdings-modal');
  if (!modal) return;

  document.getElementById('holdings-add-line')?.addEventListener('click', addLine);
document.getElementById('holdings-save')?.addEventListener('click', saveAll);
  document.getElementById('holdings-import-pdf')?.addEventListener('click', openPdfPicker);
  document.getElementById('holdings-pdf-input')?.addEventListener('change', onPdfSelected);
  document.getElementById('holdings-paste-btn')?.addEventListener('click', openPasteDialog);

  document.getElementById('holdings-tbody').addEventListener('click', e => {
    const remove = e.target.closest('[data-action="remove-line"]');
    if (remove) {
      removeLine(parseInt(remove.dataset.draft));
      return;
    }
    const popover = e.target.closest('[data-action="open-popover"]');
    if (popover) {
      openIsinPopover(popover.dataset.isin);
    }
  });

  document.getElementById('holdings-tbody').addEventListener('input', e => {
    // Toute saisie dans une ligne => brouillon dirty
    if (e.target.matches('.h-isin, .h-name, .h-qty, .h-cost, .h-mv')) {
      _markDirty();
    }
    if (e.target.matches('.h-isin')) onIsinInput(e);
    if (e.target.matches('.h-qty, .h-cost, .h-mv')) {
      // Recalcul P&L ligne et totaux en live — on collecte puis re-render la ligne courante
      const tr = e.target.closest('tr[data-draft]');
      if (!tr) return;
      const draftId = parseInt(tr.dataset.draft);
      const row = state.rows.find(r => r.draftId === draftId);
      if (!row) return;
      row.quantity     = tr.querySelector('.h-qty').value;
      row.cost_basis   = tr.querySelector('.h-cost').value;
      row.market_value = tr.querySelector('.h-mv').value;
      // Remplace juste la cellule P&L sans tout re-rendre (pour ne pas perdre le focus input)
      const pnlCell = tr.querySelector('td.num:nth-last-child(2)');
      if (pnlCell) pnlCell.innerHTML = _pnlCell(row);
      renderTotals();
    }
  });

  // Intercepte les 3 points de fermeture pour proposer sauvegarde si dirty
  document.getElementById('holdings-modal-overlay')?.addEventListener('click', confirmCloseHoldings);
  modal.querySelectorAll('[data-close="holdings-modal"]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      confirmCloseHoldings();
    }, { capture: true });
  });
}
