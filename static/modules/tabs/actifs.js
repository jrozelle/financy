import { S } from '../state.js';
import { api } from '../api.js';
import { esc, fmt, fmtDate, destroyChart, getColors, chartBorderColor, sortArr } from '../utils.js';
import { openIsinPopover } from '../isin-popover.js';
import { triggerPricesRefresh } from './tools.js';

let _classChart = null;
let _envelopeChart = null;
let _data = null;
let _sortCol = 'market_value';
let _sortDesc = true;

export async function loadActifs() {
  // Remplir le filtre personne
  const owners = (S.config && S.config.owners) || [];
  const sel = document.getElementById('actifs-owner-filter');
  if (sel && sel.options.length <= 1) {
    sel.innerHTML = '<option value="">Toutes</option>' +
      owners.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('');
  }
  const owner = sel ? sel.value : '';
  const url = owner ? `/api/holdings/consolidated?owner=${encodeURIComponent(owner)}` : '/api/holdings/consolidated';
  try {
    _data = await api('GET', url, null, { silent: true });
  } catch { return; }
  _render();
}

function _render() {
  if (!_data) return;
  const t = _data.totals;
  const lines = _data.lines || [];

  document.getElementById('actifs-kpi-value').textContent = fmt(t.market_value || 0);
  document.getElementById('actifs-kpi-cost').textContent  = t.cost_basis ? fmt(t.cost_basis) : '—';
  const pnlEl = document.getElementById('actifs-kpi-pnl');
  if (t.pnl != null) {
    pnlEl.textContent = (t.pnl >= 0 ? '+' : '') + fmt(t.pnl) + (t.pnl_pct != null ? ` (${t.pnl_pct.toFixed(2)}%)` : '');
    pnlEl.style.color = t.pnl >= 0 ? 'var(--success)' : 'var(--danger)';
  } else {
    pnlEl.textContent = '—'; pnlEl.style.color = '';
  }
  document.getElementById('actifs-kpi-count').textContent = t.lines_count || 0;

  _renderTable(lines);
  _renderClassChart(_data.breakdowns.asset_class || []);
  _renderEnvelopeChart(_data.breakdowns.envelope || []);
}

function _renderTable(lines) {
  const tbody = document.getElementById('actifs-tbody');
  const empty = document.getElementById('actifs-empty');
  if (!lines.length) {
    tbody.innerHTML = '';
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';
  const sorted = sortArr([...lines], _sortCol, _sortDesc ? -1 : 1);
  tbody.innerHTML = sorted.map(l => {
    const pnl = l.pnl;
    const pnlCls = pnl == null ? '' : pnl >= 0 ? 'pos' : 'neg';
    const pnlStr = pnl == null ? '—'
      : `${pnl >= 0 ? '+' : ''}${fmt(pnl)}${l.pnl_pct != null ? ` (${l.pnl_pct.toFixed(1)}%)` : ''}`;
    const fresh = _freshnessBadge(l);
    return `<tr>
      <td><button type="button" class="h-isin-btn" data-action="open-popover" data-isin="${esc(l.isin)}">${esc(l.isin)}</button></td>
      <td>${esc(l.name || '—')}</td>
      <td>${esc(l.asset_class || '—')}</td>
      <td class="num">${new Intl.NumberFormat('fr-FR').format(l.quantity)}</td>
      <td class="num">${l.avg_cost != null ? fmt(l.avg_cost) : '—'}</td>
      <td class="num">${l.last_price != null ? fmt(l.last_price) : '—'}</td>
      <td class="num">${fmt(l.market_value)}</td>
      <td class="num ${pnlCls}">${pnlStr}</td>
      <td class="num">${l.weight_pct.toFixed(1)}%</td>
      <td>${esc((l.envelopes || []).join(', ') || '—')}</td>
      <td>${fresh}</td>
    </tr>`;
  }).join('');
  const thead = document.getElementById('actifs-thead');
  if (thead) {
    thead.querySelectorAll('th[data-sort]').forEach(th => {
      th.classList.remove('sort-asc', 'sort-desc');
      if (th.dataset.sort === _sortCol) th.classList.add(_sortDesc ? 'sort-desc' : 'sort-asc');
    });
  }
}

function _freshnessBadge(l) {
  if (!l.is_priceable) {
    return '<span class="h-badge h-badge-muted" title="Non coté">non coté</span>';
  }
  if (!l.last_price_date) return '<span class="h-badge h-badge-expired" title="Jamais rafraichi">inconnu</span>';
  const ageMs = Date.now() - new Date(l.last_price_date + 'T23:59:59').getTime();
  if (isNaN(ageMs)) return '<span class="h-badge h-badge-expired">inconnu</span>';
  const ageHours = ageMs / (1000 * 3600);
  let cls, lbl;
  if (ageHours < 1)       { cls = 'h-badge-fresh'; lbl = '<1h'; }
  else if (ageHours < 12) { cls = 'h-badge-fresh'; lbl = `${Math.floor(ageHours)}h`; }
  else if (ageHours < 24) { cls = 'h-badge-fresh'; lbl = '<1j'; }
  else if (ageHours < 48) { cls = 'h-badge-stale'; lbl = '1j'; }
  else if (ageHours < 168){ cls = 'h-badge-stale'; lbl = `${Math.floor(ageHours / 24)}j`; }
  else                    { cls = 'h-badge-expired'; lbl = `${Math.floor(ageHours / 24)}j`; }
  return `<span class="h-badge ${cls}" title="${esc(l.last_price_date)}">${lbl}</span>`;
}

// ─── Charts ─────────────────────────────────────────────────────────────────

function _pieDataset(breakdown, colors) {
  return {
    labels: breakdown.map(b => b.label),
    datasets: [{
      data: breakdown.map(b => b.market_value),
      backgroundColor: breakdown.map((_, i) => colors[i % colors.length] + 'cc'),
      borderColor: chartBorderColor(),
      borderWidth: 1.5,
    }],
  };
}

function _pieOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } },
      tooltip: {
        callbacks: {
          label: ctx => {
            const b = _data?.breakdowns?.asset_class?.[ctx.dataIndex]
                   || _data?.breakdowns?.envelope?.[ctx.dataIndex]
                   || {};
            return ` ${ctx.label} : ${fmt(ctx.parsed)} (${b.weight_pct ?? '—'}%)`;
          },
        },
      },
    },
  };
}

function _renderClassChart(breakdown) {
  const canvas = document.getElementById('actifs-chart-class');
  if (!canvas) return;
  _classChart = destroyChart(_classChart);
  if (!breakdown.length) return;
  _classChart = new Chart(canvas, {
    type: 'doughnut',
    data: _pieDataset(breakdown, getColors()),
    options: _pieOptions(),
  });
}

function _renderEnvelopeChart(breakdown) {
  const canvas = document.getElementById('actifs-chart-envelope');
  if (!canvas) return;
  _envelopeChart = destroyChart(_envelopeChart);
  if (!breakdown.length) return;
  _envelopeChart = new Chart(canvas, {
    type: 'doughnut',
    data: _pieDataset(breakdown, getColors().slice().reverse()),
    options: _pieOptions(),
  });
}

// ─── Wiring ─────────────────────────────────────────────────────────────────

export function wireActifsEvents() {
  const sel = document.getElementById('actifs-owner-filter');
  sel?.addEventListener('change', loadActifs);

  document.getElementById('actifs-refresh-prices')?.addEventListener('click', async () => {
    await triggerPricesRefresh(false);
    loadActifs();
  });

  document.getElementById('actifs-tbody')?.addEventListener('click', e => {
    const btn = e.target.closest('[data-action="open-popover"]');
    if (btn) openIsinPopover(btn.dataset.isin);
  });

  const thead = document.getElementById('actifs-thead');
  thead?.addEventListener('click', e => {
    const th = e.target.closest('[data-sort]');
    if (!th) return;
    const col = th.dataset.sort;
    if (col === _sortCol) _sortDesc = !_sortDesc;
    else { _sortCol = col; _sortDesc = true; }
    if (_data) _renderTable(_data.lines);
  });
}
