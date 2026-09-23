import { fmt, fmtDate, esc, getColors, gridColor, destroyChart, parseLocaleNumber, fmtAxis,
         tsJour, echelleTemps, titreDate } from '../utils.js';
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
  let html = '<div class="timeline-wrapper"><div class="timeline">';
  for (const ev of events) {
    // La nature de l'evenement s'ecrit en toutes lettres : la couleur du
    // point seule ne se lit ni sans couleur ni au lecteur d'ecran.
    const nature = ev.type === 'snapshot' ? 'Arrêté' : ev.type === 'note' ? 'Note' : 'Flux';
    const cls = `timeline-event timeline-${ev.type}`;
    const val = ev.value != null ? ` — ${fmt(ev.value)}` : '';
    html += `<div class="${cls}">
      <div class="timeline-dot" aria-hidden="true"></div>
      <div class="timeline-info">
        <div class="timeline-date">${fmtDate(ev.date)} · ${nature}</div>
        <div class="timeline-label">${esc(ev.label)}${val}</div>
      </div>
    </div>`;
  }
  html += '</div></div>';

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
  const border = gridColor();

  // Echelle de temps : des arretes irreguliers restent a leur vraie date.
  snapshots = [...snapshots].sort((a, b) => a.date.localeCompare(b.date));
  _timelineChart = new Chart(canvas, {
    type: 'line',
    data: {
      datasets: [{
        label: 'Patrimoine net',
        data: snapshots.map(s => ({ x: tsJour(s.date), y: s.value })),
        borderColor: colors[0],
        backgroundColor: colors[0] + '18',
        fill: true,
        cubicInterpolationMode: 'monotone',
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
            title: titreDate,
            label: ctx => ` ${fmt(ctx.parsed.y)}`,
            afterBody: () => 'Cliquer pour voir la composition',
          },
        },
      },
      scales: {
        y: {
          ticks: {
            callback: fmtAxis,
            font: { size: 11 },
          },
          grid: { color: border },
        },
        x: echelleTemps(snapshots.map(s => s.date)),
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
      initial: parseLocaleNumber(document.getElementById('sim-initial').value, 0),
      monthly: parseLocaleNumber(document.getElementById('sim-monthly').value, 0),
      annual_rate: parseLocaleNumber(document.getElementById('sim-rate').value, 5),
      years: parseInt(parseLocaleNumber(document.getElementById('sim-years').value, 10), 10),
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

  // Une quarantaine de points au plus. L'axe x est lineaire sur le numero de
  // mois : le dernier point, garde meme hors du pas, tombe a sa vraie place au
  // lieu d'etre pose a egale distance de son voisin comme sur une echelle
  // `category`.
  const step = Math.max(1, Math.floor(points.length / 40));
  const filtered = points.filter((_, i) => i === 0 || i === points.length - 1 || i % step === 0);

  const colors = getColors();
  const border = gridColor();
  const moisMax = filtered.length ? filtered[filtered.length - 1].month : 0;

  _simulChart = new Chart(canvas, {
    type: 'line',
    data: {
      datasets: [
        {
          label: 'Capital',
          data: filtered.map(p => ({ x: p.month, y: p.balance })),
          borderColor: colors[0],
          backgroundColor: colors[0] + '18',
          fill: true,
          cubicInterpolationMode: 'monotone',
          pointRadius: 2,
          borderWidth: 2,
        },
        {
          label: 'Investi',
          data: filtered.map(p => ({ x: p.month, y: p.invested })),
          borderColor: colors[2],
          borderDash: [5, 3],
          cubicInterpolationMode: 'monotone',
          pointRadius: 0,
          borderWidth: 1.5,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },   // series alignees sur les memes mois
      plugins: {
        legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            title: items => items.length ? _duree(items[0].parsed.x) : '',
            // Montant formate par fmt : masque en mode discretion.
            label: ctx => ` ${ctx.dataset.label} : ${fmt(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        y: {
          ticks: {
            callback: fmtAxis,
            font: { size: 11 },
          },
          grid: { color: border },
        },
        x: {
          type: 'linear', min: 0, max: moisMax,
          ticks: {
            font: { size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 8,
            // Graduation a l'annee quand l'horizon le permet.
            stepSize: moisMax > 24 ? 12 * Math.max(1, Math.round(moisMax / 12 / 8)) : 3,
            callback: v => _duree(v),
          },
          grid: { display: false },
        },
      },
    },
  });
}

/** « 3 ans », « 1 an 6 mois », « 9 mois » : un numero de mois de simulation. */
function _duree(mois) {
  const m = Math.round(mois);
  const a = Math.floor(m / 12), r = m % 12;
  const ans = a ? `${a} an${a > 1 ? 's' : ''}` : '';
  const reste = r ? `${r} mois` : '';
  return [ans, reste].filter(Boolean).join(' ') || '0 mois';
}

// ─── Auto-snapshot ───────────────────────────────────────────────────────────

export async function triggerAutoSnapshot() {
  try {
    const result = await api('POST', '/api/auto-snapshot');
    if (result.skipped) {
      toast('Un arrêté existe déjà à cette date', 'error');
    } else {
      toast(`Arrêté créé : ${result.copied} positions copiées du ${fmtDate(result.from_date)}`);
      await refreshDates();
    }
  } catch (err) { toast('Erreur à la création de l’arrêté : ' + err.message, 'error'); }
}

// ─── Refresh des cours de marche ────────────────────────────────────────────

export async function loadSchedulerStatus() {
  const el = document.getElementById('scheduler-status');
  if (!el) return;
  try {
    const s = await api('GET', '/api/scheduler/status', null, { silent: true });
    if (!s.configured) {
      el.innerHTML = 'Refresh automatique <strong>désactivé</strong> (SCHEDULER_ENABLED=false).';
      return;
    }
    if (!s.running) {
      el.innerHTML = 'Scheduler configuré mais non démarré — vérifier les logs.';
      return;
    }
    const next = s.next_run ? new Date(s.next_run).toLocaleString('fr-FR') : '—';
    el.innerHTML = `Refresh automatique <strong>actif</strong> — prochain passage : ${esc(next)} (${esc(s.timezone || '')})`;
  } catch {
    el.innerHTML = '';
  }
}

export async function triggerPricesRefresh(onlyStale = false) {
  const btnAll   = document.getElementById('btn-refresh-prices');
  const btnStale = document.getElementById('btn-refresh-prices-stale');
  const resultEl = document.getElementById('prices-refresh-result');
  if (btnAll)   btnAll.disabled = true;
  if (btnStale) btnStale.disabled = true;
  if (resultEl) resultEl.innerHTML = '<span class="text-muted">Rafraichissement en cours…</span>';

  try {
    const url = onlyStale ? '/api/prices/refresh?only_stale=1' : '/api/prices/refresh';
    const stats = await api('POST', url);
    const parts = [
      `${stats.refreshed} cours mis a jour`,
      stats.resolved_tickers ? `${stats.resolved_tickers} tickers résolus` : null,
      stats.errors ? `<span style="color:var(--danger)">${stats.errors} erreur(s)</span>` : null,
      stats.skipped ? `${stats.skipped} ignoré(s)` : null,
    ].filter(Boolean);
    let divergentHtml = '';
    if (stats.divergent && stats.divergent.length) {
      const items = stats.divergent.map(d =>
        `<li>${esc(d.isin)} (${esc(d.ticker)}) : ${d.old_price.toFixed(2)} → ${d.new_price.toFixed(2)} — <strong>ignore, verifiez le ticker</strong></li>`
      ).join('');
      divergentHtml = `<div style="color:var(--warning);margin-top:.5rem;font-size:12px">Cours divergents (>50%) ignores :<ul style="margin:.25rem 0">${items}</ul></div>`;
    }
    if (resultEl) {
      resultEl.innerHTML = `Provider <strong>${esc(stats.provider)}</strong> — ${parts.join(' · ')}${divergentHtml}`;
    }
    toast(stats.divergent?.length ? 'Cours rafraichis (divergences detectees)' : 'Cours rafraichis', stats.divergent?.length ? 'warning' : 'success');
  } catch (err) {
    if (resultEl) resultEl.innerHTML = `<span style="color:var(--danger)">Erreur : ${esc(err.message)}</span>`;
  } finally {
    if (btnAll)   btnAll.disabled = false;
    if (btnStale) btnStale.disabled = false;
  }
}
