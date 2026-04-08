import { S } from './state.js';
import { fmt, fmtDate, esc, liqText, getColors, chartBorderColor, destroyChart } from './utils.js';
import { api } from './api.js';
import { closeModal, confirmDialog } from './dialogs.js';

let _historyChart = null;
const _navStack = [];

// ─── Navigation stack ─────────────────────────────────────────────────────

function _snapshot() {
  return {
    subtitle: document.getElementById('dd-subtitle').textContent,
    title:    document.getElementById('dd-title').textContent,
    amount:   document.getElementById('dd-amount').textContent,
    body:     document.getElementById('dd-body').innerHTML,
  };
}

function _restore(snap) {
  _historyChart = destroyChart(_historyChart);
  document.getElementById('dd-subtitle').textContent = snap.subtitle;
  document.getElementById('dd-title').textContent    = snap.title;
  document.getElementById('dd-amount').textContent   = snap.amount;
  document.getElementById('dd-body').innerHTML        = snap.body;
  _updateBackBtn();
}

function _pushNav() {
  _navStack.push(_snapshot());
  _updateBackBtn();
}

function _updateBackBtn() {
  const btn = document.getElementById('dd-back');
  if (btn) btn.classList.toggle('hidden', _navStack.length === 0);
}

function goBack() {
  if (!_navStack.length) { closeDrilldown(); return; }
  _restore(_navStack.pop());
}

// ─── Core ─────────────────────────────────────────────────────────────────

export function openDrilldown({ subtitle, title, amount, sections }) {
  document.getElementById('dd-subtitle').textContent = subtitle || '';
  document.getElementById('dd-title').textContent    = title   || '';
  document.getElementById('dd-amount').textContent   = amount  || '';

  document.getElementById('dd-body').innerHTML = sections.map(sec => `
    <div class="dd-section">
      ${sec.title ? `<div class="dd-section-title">${esc(sec.title)}</div>` : ''}
      ${sec.rows.map(r => {
        const bar = r.pct != null
          ? `<div class="dd-bar-wrap"><div class="dd-bar" style="width:${Math.min(100,r.pct).toFixed(1)}%"></div></div>`
          : '';
        return `<div class="dd-row">
          <div class="dd-row-left">
            <div class="dd-row-name">${esc(r.name)}</div>
            ${r.sub ? `<div class="dd-row-sub">${esc(r.sub)}</div>` : ''}
            ${bar}
          </div>
          <div class="dd-row-right">
            <div class="dd-row-val ${r.neg ? 'neg' : ''}">${r.val}</div>
            ${r.pctLabel ? `<div class="dd-row-pct">${r.pctLabel}</div>` : ''}
          </div>
        </div>`;
      }).join('')}
    </div>`).join('');

  document.getElementById('drilldown-panel').classList.remove('hidden');
  _updateBackBtn();
}

export function closeDrilldown() {
  _navStack.length = 0;
  _historyChart = destroyChart(_historyChart);
  document.getElementById('drilldown-panel').classList.add('hidden');
  _updateBackBtn();
}

// ─── Drilldown positions (clickable rows) ─────────────────────────────────

export function drilldownPositions(positions, title, subtitle, { showOwner = false, valueField = 'net_attributed', neg = false } = {}) {
  const panel = document.getElementById('drilldown-panel');
  if (panel && !panel.classList.contains('hidden')) _pushNav();

  const valOf = p => p[valueField] || 0;
  const total = positions.reduce((s, p) => s + valOf(p), 0);
  const sorted = [...positions].sort((a, b) => valOf(b) - valOf(a));

  document.getElementById('dd-subtitle').textContent = subtitle || '';
  document.getElementById('dd-title').textContent    = title   || '';
  document.getElementById('dd-amount').textContent   = fmt(total);

  document.getElementById('dd-body').innerHTML = `
    <div class="dd-section">
      <div class="dd-section-title">${sorted.length} position(s)</div>
      ${sorted.map(p => {
        const v = valOf(p);
        const pct = total > 0 ? (v / total) * 100 : 0;
        const bar = total > 0
          ? `<div class="dd-bar-wrap"><div class="dd-bar" style="width:${Math.min(100, pct).toFixed(1)}%"></div></div>`
          : '';
        const pctLabel = total > 0 ? pct.toFixed(1) + ' %' : '';
        return `<div class="dd-row dd-row-clickable" data-pos-id="${p.id}"
                     data-category="${esc(p.category)}">
          <div class="dd-row-left">
            <div class="dd-row-name">${esc(p.envelope || p.category)}</div>
            <div class="dd-row-sub">${esc([showOwner ? p.owner : null, p.establishment, p.entity, liqText(p.liquidity)].filter(Boolean).join(' · '))}</div>
            ${bar}
          </div>
          <div class="dd-row-right">
            <div class="dd-row-val ${neg || v < 0 ? 'neg' : ''}">${fmt(v)}</div>
            ${pctLabel ? `<div class="dd-row-pct">${pctLabel}</div>` : ''}
            <div class="dd-row-action" title="Voir l'évolution">📈</div>
          </div>
        </div>`;
      }).join('')}
    </div>`;

  document.getElementById('drilldown-panel').classList.remove('hidden');
  _updateBackBtn();
}

// ─── Drilldown mobilizable ────────────────────────────────────────────────

export function drilldownMobilizable() {
  api('GET', `/api/positions?date=${S.syntheseDate}`).then(allPositions => {
    const panel = document.getElementById('drilldown-panel');
    if (panel && !panel.classList.contains('hidden')) _pushNav();

    const owner = S.syntheseOwner;
    const positions = (!owner || owner === 'Famille') ? allPositions : allPositions.filter(p => p.owner === owner);
    const total = positions.reduce((s, p) => s + (p.mobilizable_value || 0), 0);
    const byLiq = {};
    for (const p of positions) {
      const k = p.liquidity || 'Autre';
      if (!byLiq[k]) byLiq[k] = [];
      byLiq[k].push(p);
    }

    document.getElementById('dd-subtitle').textContent = 'Liquidité';
    document.getElementById('dd-title').textContent    = 'Mobilisable';
    document.getElementById('dd-amount').textContent   = fmt(total);

    const sectionsHtml = S.config.liquidity_order
      .filter(l => byLiq[l]?.length)
      .map(l => {
        const sub = byLiq[l].sort((a, b) => (b.mobilizable_value || 0) - (a.mobilizable_value || 0));
        const liqTotal = sub.reduce((s, p) => s + (p.mobilizable_value || 0), 0);
        return `<div class="dd-section">
          <div class="dd-section-title">${esc(l)} — ${fmt(liqTotal)}</div>
          ${sub.map(p => {
            const v = p.mobilizable_value || 0;
            const pct = total > 0 ? (v / total) * 100 : 0;
            return `<div class="dd-row dd-row-clickable" data-pos-id="${p.id}" data-category="${esc(p.category)}">
              <div class="dd-row-left">
                <div class="dd-row-name">${esc(p.envelope || p.category)}</div>
                <div class="dd-row-sub">${esc([p.owner, p.establishment].filter(Boolean).join(' · '))}</div>
                <div class="dd-bar-wrap"><div class="dd-bar" style="width:${Math.min(100, pct).toFixed(1)}%"></div></div>
              </div>
              <div class="dd-row-right">
                <div class="dd-row-val">${fmt(v)}</div>
                ${total > 0 ? `<div class="dd-row-pct">${pct.toFixed(1)} %</div>` : ''}
                <div class="dd-row-action" title="Voir l'évolution">📈</div>
              </div>
            </div>`;
          }).join('')}
        </div>`;
      }).join('');

    document.getElementById('dd-body').innerHTML = sectionsHtml;
    document.getElementById('drilldown-panel').classList.remove('hidden');
    _updateBackBtn();
  });
}

// ─── Drilldown history ────────────────────────────────────────────────────

export async function drilldownHistory({ subtitle, title, filters }) {
  const panel = document.getElementById('drilldown-panel');
  if (panel && !panel.classList.contains('hidden')) _pushNav();

  const params = new URLSearchParams(filters).toString();
  const history = await api('GET', `/api/position-history?${params}`);

  document.getElementById('dd-subtitle').textContent = subtitle || 'Évolution';
  document.getElementById('dd-title').textContent = title || '';

  if (!history.length) {
    document.getElementById('dd-amount').textContent = '';
    document.getElementById('dd-body').innerHTML =
      '<p style="color:var(--text-muted);padding:.75rem">Aucune donnée historique.</p>';
    document.getElementById('drilldown-panel').classList.remove('hidden');
    _updateBackBtn();
    return;
  }

  const last = history[history.length - 1];
  document.getElementById('dd-amount').textContent = fmt(last.net);

  const rows = history.map(h => {
    const prev = history[history.indexOf(h) - 1];
    const delta = prev ? h.net - prev.net : null;
    const deltaStr = delta != null
      ? `<span style="color:${delta >= 0 ? 'var(--success)' : 'var(--danger)'};font-size:11px">${delta >= 0 ? '+' : ''}${fmt(delta)}</span>`
      : '';
    return `<tr>
      <td>${fmtDate(h.date)}</td>
      <td class="num">${fmt(h.gross)}</td>
      <td class="num">${fmt(h.net)}</td>
      <td class="num">${deltaStr}</td>
    </tr>`;
  }).reverse().join('');

  document.getElementById('dd-body').innerHTML = `
    ${history.length >= 2 ? '<div style="position:relative;height:200px;margin-bottom:1rem"><canvas id="dd-history-chart"></canvas></div>' : ''}
    <div class="table-scroll">
      <table class="data-table">
        <thead><tr><th>Date</th><th class="num">Brut</th><th class="num">Net</th><th class="num">Δ</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;

  if (history.length >= 2) {
    _historyChart = destroyChart(_historyChart);
    const canvas = document.getElementById('dd-history-chart');
    const colors = getColors();
    const border = chartBorderColor();
    _historyChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: history.map(h => fmtDate(h.date)),
        datasets: [{
          label: 'Net',
          data: history.map(h => h.net),
          borderColor: colors[0],
          backgroundColor: colors[0] + '18',
          fill: true,
          tension: 0.3,
          pointRadius: 4,
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { ticks: { callback: v => new Intl.NumberFormat('fr-FR', { notation: 'compact' }).format(v) + ' €', font: { size: 11 } }, grid: { color: border } },
          x: { ticks: { font: { size: 10 } }, grid: { display: false } },
        },
      },
    });
  }

  document.getElementById('drilldown-panel').classList.remove('hidden');
  _updateBackBtn();
}

// ─── Events ───────────────────────────────────────────────────────────────

export function wireDrilldownEvents() {
  document.getElementById('dd-close').addEventListener('click', closeDrilldown);
  document.getElementById('dd-back').addEventListener('click', goBack);
  document.getElementById('drilldown-overlay').addEventListener('click', closeDrilldown);

  // Delegated click on dd-body — survives innerHTML restores from nav stack
  document.getElementById('dd-body').addEventListener('click', e => {
    const row = e.target.closest('.dd-row-clickable');
    if (!row) return;
    const posId = row.dataset.posId;
    const category = row.dataset.category;
    if (posId) {
      drilldownHistory({
        subtitle: 'Évolution position',
        title: category || '',
        filters: { position_id: posId },
      });
    }
  });

  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    // Modals have priority
    const modals = ['position-modal', 'flux-modal', 'entity-modal', 'targets-modal'];
    for (const id of modals) {
      const el = document.getElementById(id);
      if (el && !el.classList.contains('hidden')) { closeModal(id); return; }
    }
    // Drilldown: back if stack, close if at root
    const panel = document.getElementById('drilldown-panel');
    if (panel && !panel.classList.contains('hidden')) {
      if (_navStack.length > 0) goBack();
      else closeDrilldown();
    }
  });

  // KPI cards
  ['kpi-net','kpi-gross','kpi-debt','kpi-mobilizable'].forEach(id => {
    document.getElementById(id).closest('.kpi-card').classList.add('clickable');
  });

  const _filterByOwner = positions => {
    const owner = S.syntheseOwner;
    if (!owner || owner === 'Famille') return positions;
    return positions.filter(p => p.owner === owner);
  };
  const _ownerLabel = () => {
    const owner = S.syntheseOwner;
    return (!owner || owner === 'Famille') ? 'Toutes les personnes' : owner;
  };
  const _showOwner = () => !S.syntheseOwner || S.syntheseOwner === 'Famille';

  document.getElementById('kpi-net').closest('.kpi-card').addEventListener('click', () => {
    if (!S.synthese?.date) return;
    api('GET', `/api/positions?date=${S.syntheseDate}`).then(pos =>
      drilldownPositions(_filterByOwner(pos), 'Patrimoine net', _ownerLabel(), { showOwner: _showOwner() })
    );
  });
  document.getElementById('kpi-gross').closest('.kpi-card').addEventListener('click', () => {
    if (!S.synthese?.date) return;
    api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
      drilldownPositions(_filterByOwner(positions), 'Actifs bruts', _ownerLabel(), { showOwner: _showOwner(), valueField: 'gross_attributed' });
    });
  });
  document.getElementById('kpi-debt').closest('.kpi-card').addEventListener('click', () => {
    if (!S.synthese?.date) return;
    api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
      const withDebt = _filterByOwner(positions).filter(p => p.debt_attributed > 0);
      drilldownPositions(withDebt, 'Dettes', _ownerLabel(), { showOwner: _showOwner(), valueField: 'debt_attributed', neg: true });
    });
  });
  document.getElementById('kpi-mobilizable').closest('.kpi-card').addEventListener('click', () => {
    if (!S.synthese?.date) return;
    drilldownMobilizable();
  });
}
