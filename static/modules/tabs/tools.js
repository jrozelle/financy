import { S } from '../state.js';
import { fmt, fmtDate, esc, getColors, chartBorderColor, destroyChart } from '../utils.js';
import { api } from '../api.js';
import { toast } from '../dialogs.js';
import { refreshDates } from '../main.js';
import { drilldownPositions } from '../drilldown.js';

let _timelineChart = null;
let _simulChart = null;

// ─── Timeline ────────────────────────────────────────────────────────────────

export async function loadTimeline() {
  const events = await api('GET', '/api/timeline');
  renderTimeline(events);
}

function renderTimeline(events) {
  const container = document.getElementById('timeline-body');
  if (!events.length) {
    container.innerHTML = '<p class="text-muted" style="padding:1rem">Aucun événement.</p>';
    return;
  }

  // Frise visuelle
  let html = '<div class="timeline">';
  for (const ev of events) {
    const icon = ev.type === 'snapshot' ? '&#128200;' : ev.type === 'note' ? '&#128221;' : '&#128176;';
    const cls = `timeline-event timeline-${ev.type}`;
    const val = ev.value != null ? ` — ${fmt(ev.value)}` : '';
    html += `<div class="${cls}">
      <div class="timeline-dot">${icon}</div>
      <div class="timeline-info">
        <div class="timeline-date">${fmtDate(ev.date)}</div>
        <div class="timeline-label">${esc(ev.label)}${val}</div>
      </div>
    </div>`;
  }
  html += '</div>';

  // Graphe net patrimoine (snapshots uniquement)
  const snapshots = events.filter(e => e.type === 'snapshot' && e.value != null);
  if (snapshots.length >= 2) {
    html = `<div style="position:relative;height:220px;margin-bottom:1.25rem"><canvas id="timeline-chart"></canvas></div>` + html;
  }

  container.innerHTML = html;

  if (snapshots.length >= 2) {
    renderTimelineChart(snapshots);
  }
}

function renderTimelineChart(snapshots) {
  const canvas = document.getElementById('timeline-chart');
  if (!canvas) return;
  _timelineChart = destroyChart(_timelineChart);

  const colors = getColors();
  const border = chartBorderColor();

  _timelineChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: snapshots.map(s => fmtDate(s.date)),
      datasets: [{
        label: 'Patrimoine net',
        data: snapshots.map(s => s.value),
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
      onClick: (_, elements) => {
        if (!elements.length) return;
        const snap = snapshots[elements[0].index];
        if (!snap) return;
        api('GET', `/api/positions?date=${snap.date}`).then(positions => {
          drilldownPositions(positions, `Famille — ${fmtDate(snap.date)}`, 'Composition du patrimoine', { showOwner: true });
        });
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` ${new Intl.NumberFormat('fr-FR').format(Math.round(ctx.parsed.y))}\u202f€`,
            afterBody: () => 'Cliquer pour voir la composition',
          },
        },
      },
      scales: {
        y: {
          ticks: {
            callback: v => new Intl.NumberFormat('fr-FR', { notation: 'compact' }).format(v) + ' €',
            font: { size: 11 },
          },
          grid: { color: border },
        },
        x: { ticks: { font: { size: 10 } }, grid: { display: false } },
      },
    },
  });
}

// ─── Simulation ──────────────────────────────────────────────────────────────

export function wireSimulation() {
  const form = document.getElementById('simulation-form');
  if (!form) return;
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const data = {
      initial: parseFloat(document.getElementById('sim-initial').value) || 0,
      monthly: parseFloat(document.getElementById('sim-monthly').value) || 0,
      annual_rate: parseFloat(document.getElementById('sim-rate').value) || 5,
      years: parseInt(document.getElementById('sim-years').value) || 10,
    };
    try {
      const result = await api('POST', '/api/simulate', data);
      renderSimulation(result, data);
    } catch (err) { toast('Erreur simulation : ' + err.message, 'error'); }
  });
}

function renderSimulation(result, params) {
  const container = document.getElementById('simulation-result');
  const gains = result.gains;
  container.innerHTML = `
    <div class="kpi-grid" style="grid-template-columns:repeat(3,1fr);margin-bottom:1rem">
      <div class="kpi-card"><div class="kpi-label">Capital final</div><div class="kpi-value">${fmt(result.final_balance)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Total investi</div><div class="kpi-value">${fmt(result.total_invested)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Plus-values</div><div class="kpi-value" style="color:${gains >= 0 ? 'var(--success)' : 'var(--danger)'}">${fmt(gains)}</div></div>
    </div>
    <div style="position:relative;height:250px"><canvas id="simulation-chart"></canvas></div>
  `;
  renderSimulChart(result.points);
}

function renderSimulChart(points) {
  const canvas = document.getElementById('simulation-chart');
  if (!canvas) return;
  _simulChart = destroyChart(_simulChart);

  // Afficher un point tous les 6 mois max pour lisibilité
  const step = Math.max(1, Math.floor(points.length / 40));
  const filtered = points.filter((_, i) => i === 0 || i === points.length - 1 || i % step === 0);

  const colors = getColors();
  const border = chartBorderColor();

  const labels = filtered.map(p => {
    const y = Math.floor(p.month / 12);
    const m = p.month % 12;
    return m === 0 ? `${y} an${y > 1 ? 's' : ''}` : `${y}a${m}m`;
  });

  _simulChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Capital',
          data: filtered.map(p => p.balance),
          borderColor: colors[0],
          backgroundColor: colors[0] + '18',
          fill: true,
          tension: 0.3,
          pointRadius: 2,
          borderWidth: 2,
        },
        {
          label: 'Investi',
          data: filtered.map(p => p.invested),
          borderColor: colors[2],
          borderDash: [5, 3],
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 1.5,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
      },
      scales: {
        y: {
          ticks: {
            callback: v => new Intl.NumberFormat('fr-FR', { notation: 'compact' }).format(v) + ' €',
            font: { size: 11 },
          },
          grid: { color: border },
        },
        x: { ticks: { font: { size: 10 }, maxRotation: 0 }, grid: { display: false } },
      },
    },
  });
}

// ─── Auto-snapshot ───────────────────────────────────────────────────────────

export async function triggerAutoSnapshot() {
  try {
    const result = await api('POST', '/api/auto-snapshot');
    if (result.skipped) {
      toast('Snapshot déjà existant à cette date', 'error');
    } else {
      toast(`Snapshot créé : ${result.copied} positions copiées du ${fmtDate(result.from_date)}`);
      await refreshDates();
    }
  } catch (err) { toast('Erreur snapshot : ' + err.message, 'error'); }
}
