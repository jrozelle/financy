import { api } from '../api.js';
import { esc, fmt } from '../utils.js';
import { closeModal, confirmDialog, toast } from '../dialogs.js';
import { loadPositions } from './positions.js';

// Etat interne de la modale : position courante + liste de lignes (draft).
// Chaque ligne a un `draftId` local (index) et optionnellement un `id` DB.
let state = {
  positionId: null,
  positionLabel: '',
  rows: [],
  nextDraftId: 0,
};

const PSEUDO_ISIN_PREFIXES = ['FONDS_EUROS_', 'CUSTOM_'];

function isPseudoIsin(isin) {
  if (!isin) return false;
  const u = isin.toUpperCase();
  return PSEUDO_ISIN_PREFIXES.some(p => u.startsWith(p));
}

function makeRow(h = {}) {
  return {
    draftId:      state.nextDraftId++,
    id:           h.id ?? null,
    isin:         h.isin ?? '',
    name:         h.name ?? '',
    ticker:       h.ticker ?? '',
    quantity:     h.quantity ?? '',
    cost_basis:   h.cost_basis ?? '',
    market_value: h.market_value ?? '',
    is_priceable: h.is_priceable ?? null,
    last_price:   h.last_price ?? null,
  };
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
  const freshness = _freshnessBadge(r.last_price, r.is_priceable);
  return `
    <tr data-draft="${r.draftId}">
      <td>
        <input type="text" class="h-input h-isin" value="${esc(r.isin)}"
               list="holdings-isin-list"
               placeholder="FR0000000000 ou FONDS_EUROS_..."
               autocomplete="off" spellcheck="false"
               style="text-transform:uppercase;min-width:140px">
        ${freshness}
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
        <button type="button" class="btn-icon del" data-action="remove-line" data-draft="${r.draftId}">Suppr.</button>
      </td>
    </tr>`;
}

function _freshnessBadge(lastPrice, isPriceable) {
  if (isPriceable === false) {
    return '<span class="h-badge h-badge-muted" title="Non coté (fonds euros, actif custom)">non coté</span>';
  }
  if (lastPrice == null) return '';
  return '<span class="h-badge h-badge-ok" title="Cours connu">coté</span>';
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
  renderHoldingsTable();
  const tbody = document.getElementById('holdings-tbody');
  const lastIsin = tbody.querySelector('tr:last-child .h-isin');
  lastIsin?.focus();
}

function removeLine(draftId) {
  collectFromInputs();
  state.rows = state.rows.filter(r => r.draftId !== draftId);
  renderHoldingsTable();
}

async function saveAll() {
  collectFromInputs();

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
      return h;
    }),
  };

  try {
    await api('PUT', `/api/positions/${state.positionId}/holdings`, payload);
    toast('Lignes enregistrées', 'success');
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

export function wireHoldingsEvents() {
  const modal = document.getElementById('holdings-modal');
  if (!modal) return;

  document.getElementById('holdings-add-line')?.addEventListener('click', addLine);
  document.getElementById('holdings-save')?.addEventListener('click', saveAll);

  document.getElementById('holdings-tbody').addEventListener('click', e => {
    const btn = e.target.closest('[data-action="remove-line"]');
    if (btn) {
      removeLine(parseInt(btn.dataset.draft));
    }
  });

  document.getElementById('holdings-tbody').addEventListener('input', e => {
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

  document.getElementById('holdings-modal-overlay')?.addEventListener('click', () => closeModal('holdings-modal'));
}
