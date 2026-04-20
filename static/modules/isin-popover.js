import { api } from './api.js';
import { esc, fmt, fmtDate, destroyChart, getColors, chartBorderColor } from './utils.js';
import { toast } from './dialogs.js';

let _chart = null;
let _current = { isin: null, period: '30d' };

const DEFAULT_PERIOD = '30d';

export async function openIsinPopover(isin) {
  if (!isin) return;
  isin = isin.toUpperCase();
  // Detruit tout chart residuel (reouverture rapide sur un autre ISIN)
  _chart = destroyChart(_chart);
  _current = { isin, period: DEFAULT_PERIOD };
  const popover = document.getElementById('isin-popover');
  popover.classList.remove('hidden');

  // Reinit tabs to default period
  document.querySelectorAll('#isin-period-tabs .isin-period-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.period === DEFAULT_PERIOD);
  });

  await _loadAndRender();
}

function closePopover() {
  document.getElementById('isin-popover').classList.add('hidden');
  _chart = destroyChart(_chart);
}

async function _loadAndRender() {
  const { isin, period } = _current;
  document.getElementById('isin-popover-title').textContent = isin;
  document.getElementById('isin-popover-subtitle').textContent = '';
  document.getElementById('isin-popover-summary').innerHTML = '<span class="text-muted">Chargement…</span>';
  document.getElementById('isin-popover-holding').innerHTML = '';

  let data;
  try {
    data = await api('GET', `/api/prices/history/${encodeURIComponent(isin)}?period=${period}`);
  } catch {
    closePopover();
    return;
  }

  const subtitleBits = [data.name, data.ticker ? `(${data.ticker})` : null, data.currency]
    .filter(Boolean).join(' ');
  document.getElementById('isin-popover-subtitle').textContent = subtitleBits || '';

  document.getElementById('isin-popover-summary').innerHTML = _summaryHtml(data);
  document.getElementById('isin-popover-holding').innerHTML = _holdingHtml(data.holding);

  // Ticker + asset class inputs
  document.getElementById('isin-ticker-input').value = data.ticker || '';
  document.getElementById('isin-asset-class').value = data.asset_class || 'autre';

  _renderChart(data);
}

function _summaryHtml(data) {
  if (!data.is_priceable) {
    return `
      <div class="isin-summary-grid">
        <div class="isin-summary-item">
          <div class="isin-summary-label">Type</div>
          <div class="isin-summary-value" style="font-size:13px">Non coté (manuel)</div>
        </div>
      </div>
      <div class="text-muted" style="font-size:12.5px">
        Fonds euros ou actif custom : pas de cours de marché. La valorisation est saisie à la main.
      </div>`;
  }

  const last = data.last_price != null ? fmt(data.last_price) + ` ${data.currency || ''}` : '—';
  const varPct = data.variation_pct;
  const varDisplay = varPct != null
    ? `<span class="${varPct >= 0 ? 'pos' : 'neg'}">${varPct >= 0 ? '+' : ''}${varPct.toFixed(2)}%</span>`
    : '<span class="text-muted">—</span>';
  const freshClass = data.freshness === 'fresh' ? 'h-badge-fresh'
                    : data.freshness === 'stale' ? 'h-badge-stale'
                    : data.freshness === 'expired' ? 'h-badge-expired' : 'h-badge-muted';
  const freshLabel = data.freshness === 'fresh' ? 'À jour'
                   : data.freshness === 'stale' ? 'Vieillissant'
                   : data.freshness === 'expired' ? 'Périmé' : 'Inconnu';

  return `
    <div class="isin-summary-grid">
      <div class="isin-summary-item">
        <div class="isin-summary-label">Dernier cours</div>
        <div class="isin-summary-value">${last}</div>
      </div>
      <div class="isin-summary-item">
        <div class="isin-summary-label">Variation période</div>
        <div class="isin-summary-value">${varDisplay}</div>
      </div>
      <div class="isin-summary-item">
        <div class="isin-summary-label">Fraîcheur</div>
        <div class="isin-summary-value" style="font-size:13px">
          <span class="h-badge ${freshClass}">${freshLabel}</span>
          <span class="text-muted" style="font-size:11px">${data.last_price_date ? ' ' + fmtDate(data.last_price_date) : ''}</span>
        </div>
      </div>
      <div class="isin-summary-item">
        <div class="isin-summary-label">Points</div>
        <div class="isin-summary-value" style="font-size:13px">${data.points.length}</div>
      </div>
    </div>`;
}

function _holdingHtml(h) {
  if (!h || !h.quantity) {
    return '<div class="text-muted" style="font-size:12.5px">Aucune ligne avec cet ISIN.</div>';
  }
  const pru = h.cost_basis && h.quantity ? (h.cost_basis / h.quantity) : null;
  const pnl = h.pnl;
  const pnlPct = h.pnl_pct;
  const pnlCls = pnl == null ? '' : pnl >= 0 ? 'pos' : 'neg';

  let posHtml = '';
  if (h.positions && h.positions.length) {
    const rows = h.positions.map(p => {
      const label = [p.establishment, p.envelope, p.category].filter(Boolean).join(' / ');
      const pct = h.current_value ? ((p.market_value || 0) / h.current_value * 100).toFixed(1) : '—';
      return `<tr>
        <td style="font-size:12px">${esc(label)}</td>
        <td class="num" style="font-size:12px">${new Intl.NumberFormat('fr-FR', {maximumFractionDigits:2}).format(p.quantity || 0)}</td>
        <td class="num" style="font-size:12px">${fmt(p.market_value || 0)}</td>
        <td class="num" style="font-size:12px;color:var(--text-muted)">${pct}%</td>
      </tr>`;
    }).join('');
    posHtml = `
      <div style="margin-top:.75rem">
        <div style="font-size:12px;font-weight:600;margin-bottom:.25rem">Detention par enveloppe</div>
        <table style="width:100%;font-size:12px">
          <thead><tr>
            <th style="text-align:left;font-weight:600">Enveloppe</th>
            <th style="text-align:right;font-weight:600">Qty</th>
            <th style="text-align:right;font-weight:600">Valo</th>
            <th style="text-align:right;font-weight:600">Part</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  return `
    <div class="isin-holding-card">
      <div class="isin-holding-row"><span>Quantite cumulee</span><strong>${new Intl.NumberFormat('fr-FR', {maximumFractionDigits:4}).format(h.quantity)}</strong></div>
      ${h.cost_basis != null && h.cost_basis > 0 ? `<div class="isin-holding-row"><span>Cout total</span><strong>${fmt(h.cost_basis)}</strong></div>` : ''}
      ${pru != null ? `<div class="isin-holding-row"><span>PRU</span><strong>${fmt(pru, 2)}</strong></div>` : ''}
      ${h.current_value != null ? `<div class="isin-holding-row"><span>Valorisation</span><strong>${fmt(h.current_value)}</strong></div>` : ''}
      ${pnl != null ? `<div class="isin-holding-row"><span>P&amp;L latent</span><strong class="${pnlCls}">${fmt(pnl)}${pnlPct != null ? ` (${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%)` : ''}</strong></div>` : ''}
      ${posHtml}
    </div>`;
}

function _renderChart(data) {
  const canvas = document.getElementById('isin-chart');
  const empty = document.getElementById('isin-chart-empty');
  _chart = destroyChart(_chart);

  if (!data.points || data.points.length < 2) {
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  const colors = getColors();
  const border = chartBorderColor();
  const labels = data.points.map(p => fmtDate(p.date));
  const values = data.points.map(p => p.price);

  _chart = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Cours',
        data: values,
        borderColor: colors[0],
        backgroundColor: colors[0] + '18',
        fill: true,
        tension: 0.25,
        pointRadius: 0,
        pointHoverRadius: 4,
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` ${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 4 }).format(ctx.parsed.y)} ${data.currency || ''}`,
          },
        },
      },
      scales: {
        y: {
          ticks: {
            callback: v => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 }).format(v),
            font: { size: 11 },
          },
          grid: { color: border },
        },
        x: {
          ticks: { font: { size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 6 },
          grid: { display: false },
        },
      },
    },
  });
}

export function wireIsinPopoverEvents() {
  const popover = document.getElementById('isin-popover');
  if (!popover) return;

  document.getElementById('isin-popover-overlay').addEventListener('click', closePopover);
  document.getElementById('isin-popover-close').addEventListener('click', closePopover);
  popover.addEventListener('keydown', e => { if (e.key === 'Escape') closePopover(); });

  document.getElementById('isin-period-tabs').addEventListener('click', async e => {
    const btn = e.target.closest('.isin-period-btn');
    if (!btn) return;
    document.querySelectorAll('#isin-period-tabs .isin-period-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    _current.period = btn.dataset.period;
    await _loadAndRender();
  });

  document.getElementById('isin-refresh-btn').addEventListener('click', async () => {
    if (!_current.isin) return;
    const btn = document.getElementById('isin-refresh-btn');
    btn.disabled = true;
    try {
      await api('GET', `/api/prices/history/${encodeURIComponent(_current.isin)}?period=${_current.period}&refresh=1`);
      await _loadAndRender();
      toast('Cours actualisé', 'success');
    } catch {} finally {
      btn.disabled = false;
    }
  });

  document.getElementById('isin-ticker-save').addEventListener('click', async () => {
    if (!_current.isin) return;
    const ticker = document.getElementById('isin-ticker-input').value.trim();
    try {
      await api('PATCH', `/api/securities/${encodeURIComponent(_current.isin)}`, { ticker });
      toast('Ticker enregistre', 'success');
      await _loadAndRender();
    } catch {}
  });

  document.getElementById('isin-reset-btn').addEventListener('click', async () => {
    if (!_current.isin) return;
    try {
      await api('PATCH', `/api/securities/${encodeURIComponent(_current.isin)}`, {
        ticker: null, last_price: null, last_price_date: null,
      });
      toast('Ticker et cours reinitialises', 'success');
      await _loadAndRender();
    } catch {}
  });

  document.getElementById('isin-price-save').addEventListener('click', async () => {
    if (!_current.isin) return;
    const priceStr = document.getElementById('isin-price-input').value.trim();
    if (!priceStr) return;
    const price = parseFloat(priceStr);
    if (isNaN(price) || price <= 0) { toast('Prix invalide', 'error'); return; }
    try {
      await api('PATCH', `/api/securities/${encodeURIComponent(_current.isin)}`, {
        last_price: price,
      });
      toast('Prix mis a jour', 'success');
      await _loadAndRender();
    } catch {}
  });

  document.getElementById('isin-asset-class-save').addEventListener('click', async () => {
    if (!_current.isin) return;
    const ac = document.getElementById('isin-asset-class').value;
    try {
      await api('PATCH', `/api/securities/${encodeURIComponent(_current.isin)}`, { asset_class: ac });
      toast('Classe mise a jour', 'success');
      await _loadAndRender();
    } catch {}
  });
}
