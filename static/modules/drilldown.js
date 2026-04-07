import { S } from './state.js';
import { fmt, fmtDate, esc, liqText } from './utils.js';
import { api } from './api.js';
import { closeModal, confirmDialog } from './dialogs.js';

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
}

export function closeDrilldown() {
  document.getElementById('drilldown-panel').classList.add('hidden');
}

export function drilldownPositions(positions, title, subtitle, { showOwner = false } = {}) {
  const total = positions.reduce((s, p) => s + (p.net_attributed || 0), 0);
  const sorted = [...positions].sort((a, b) => (b.net_attributed || 0) - (a.net_attributed || 0));

  openDrilldown({
    subtitle,
    title,
    amount: fmt(total),
    sections: [{
      title: `${sorted.length} position(s)`,
      rows: sorted.map(p => ({
        name:     p.envelope || p.category,
        sub:      [showOwner ? p.owner : null, p.establishment, p.entity, liqText(p.liquidity)].filter(Boolean).join(' · '),
        val:      fmt(p.net_attributed),
        pct:      total > 0 ? (p.net_attributed / total) * 100 : 0,
        pctLabel: total > 0 ? ((p.net_attributed / total) * 100).toFixed(1) + ' %' : '',
        neg:      p.net_attributed < 0,
      })),
    }],
  });
}

export function drilldownMobilizable() {
  api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
    const total = positions.reduce((s, p) => s + (p.mobilizable_value || 0), 0);
    const byLiq = {};
    for (const p of positions) {
      const k = p.liquidity || 'Autre';
      if (!byLiq[k]) byLiq[k] = [];
      byLiq[k].push(p);
    }
    const sections = S.config.liquidity_order
      .filter(l => byLiq[l]?.length)
      .map(l => {
        const sub = byLiq[l];
        const liqTotal = sub.reduce((s, p) => s + (p.mobilizable_value || 0), 0);
        return {
          title: `${l} — ${fmt(liqTotal)}`,
          rows: sub.sort((a, b) => (b.mobilizable_value || 0) - (a.mobilizable_value || 0)).map(p => ({
            name:     p.envelope || p.category,
            sub:      [p.owner, p.establishment].filter(Boolean).join(' · '),
            val:      fmt(p.mobilizable_value),
            pct:      total > 0 ? (p.mobilizable_value / total) * 100 : 0,
            pctLabel: total > 0 ? ((p.mobilizable_value / total) * 100).toFixed(1) + ' %' : '',
          })),
        };
      });
    openDrilldown({ subtitle: 'Liquidité', title: 'Mobilisable', amount: fmt(total), sections });
  });
}

export function wireDrilldownEvents() {
  document.getElementById('dd-close').addEventListener('click', closeDrilldown);
  document.getElementById('drilldown-overlay').addEventListener('click', closeDrilldown);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const modals = ['position-modal', 'flux-modal', 'entity-modal', 'targets-modal'];
    for (const id of modals) {
      const el = document.getElementById(id);
      if (el && !el.classList.contains('hidden')) { closeModal(id); return; }
    }
    closeDrilldown();
  });

  // KPI cards
  ['kpi-net','kpi-gross','kpi-debt','kpi-mobilizable'].forEach(id => {
    document.getElementById(id).closest('.kpi-card').classList.add('clickable');
  });
  document.getElementById('kpi-net').closest('.kpi-card').addEventListener('click', () => {
    if (!S.synthese?.date) return;
    api('GET', `/api/positions?date=${S.syntheseDate}`).then(pos =>
      drilldownPositions(pos, 'Patrimoine net famille', 'Toutes les personnes', { showOwner: true })
    );
  });
  document.getElementById('kpi-gross').closest('.kpi-card').addEventListener('click', () => {
    if (!S.synthese?.date) return;
    api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
      const total = positions.reduce((s, p) => s + (p.gross_attributed || 0), 0);
      const sorted = [...positions].sort((a, b) => (b.gross_attributed||0) - (a.gross_attributed||0));
      openDrilldown({
        subtitle: 'Actifs bruts', title: 'Toutes les personnes', amount: fmt(total),
        sections: [{ title: `${sorted.length} position(s)`, rows: sorted.map(p => ({
          name: p.envelope || p.category,
          sub: [p.owner, p.establishment].filter(Boolean).join(' · '),
          val: fmt(p.gross_attributed),
          pct: total > 0 ? (p.gross_attributed / total) * 100 : 0,
          pctLabel: total > 0 ? ((p.gross_attributed / total) * 100).toFixed(1) + ' %' : '',
        }))}],
      });
    });
  });
  document.getElementById('kpi-debt').closest('.kpi-card').addEventListener('click', () => {
    if (!S.synthese?.date) return;
    api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
      const withDebt = positions.filter(p => p.debt_attributed > 0);
      const total = withDebt.reduce((s, p) => s + (p.debt_attributed || 0), 0);
      openDrilldown({
        subtitle: 'Dettes', title: 'Toutes les personnes', amount: fmt(total),
        sections: [{ title: `${withDebt.length} position(s)`, rows:
          withDebt.sort((a,b) => b.debt_attributed - a.debt_attributed).map(p => ({
            name: p.envelope || p.category,
            sub: [p.owner, p.establishment].filter(Boolean).join(' · '),
            val: fmt(p.debt_attributed), neg: true,
            pct: total > 0 ? (p.debt_attributed / total) * 100 : 0,
            pctLabel: total > 0 ? ((p.debt_attributed / total) * 100).toFixed(1) + ' %' : '',
          }))}],
      });
    });
  });
  document.getElementById('kpi-mobilizable').closest('.kpi-card').addEventListener('click', () => {
    if (!S.synthese?.date) return;
    drilldownMobilizable();
  });
}
