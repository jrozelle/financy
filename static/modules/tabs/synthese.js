import { S, catChart, histChart, syntheseEnvChart, syntheseHistChart,
         setCatChart, setHistChart, setSyntheseEnvChart, setSyntheseHistChart } from '../state.js';
import { fmt, fmtDate, esc, kpiDelta, liqBadge, getColors, doughnutConfig, chartBorderColor, chartFamilyColors } from '../utils.js';
import { api } from '../api.js';
import { drilldownPositions } from '../drilldown.js';
import { loadUserAlerts } from '../alerts.js';
import { renderAllocationTargets } from '../targets.js';

export async function loadSynthese() {
  if (!S.syntheseDate && S.dates.length) S.syntheseDate = S.dates[0];
  if (!S.syntheseDate) return;
  const [syn, positions] = await Promise.all([
    api('GET', `/api/synthese?date=${S.syntheseDate}`),
    api('GET', `/api/positions?date=${S.syntheseDate}`),
  ]);
  syn._positions_cache = {};
  for (const o of S.config.owners) {
    syn._positions_cache[o] = positions.filter(p => p.owner === o);
  }
  S.synthese = syn;
  renderSynthesePersonTabs();
  renderSynthese();
}

export function renderSynthesePersonTabs() {
  const container = document.getElementById('synthese-person-tabs');
  container.innerHTML = ['Famille', ...S.config.owners].map(o => `
    <button class="person-tab-btn ${S.syntheseOwner === o ? 'active' : ''}"
            data-owner="${esc(o)}">${esc(o)}</button>
  `).join('');
  container.querySelectorAll('.person-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      S.syntheseOwner = btn.dataset.owner;
      renderSynthesePersonTabs();
      renderSynthese();
    });
  });
}

export function renderSynthese() {
  const syn = S.synthese;
  if (!syn?.date) {
    ['kpi-net','kpi-gross','kpi-debt','kpi-mobilizable'].forEach(id => {
      document.getElementById(id).textContent = '—';
    });
    return;
  }

  const { family, totals_by_owner, totals_by_category, mobilizable_by_liquidity } = syn;
  const owner = S.syntheseOwner;
  const isFamily = (owner === 'Famille');

  const kpi = isFamily
    ? { gross: family.gross, debt: family.debt, net: family.net,
        mob: Object.values(totals_by_owner).reduce((s, o) => s + o.mobilizable, 0) }
    : { gross: totals_by_owner[owner]?.gross      || 0,
        debt:  totals_by_owner[owner]?.debt       || 0,
        net:   totals_by_owner[owner]?.net        || 0,
        mob:   totals_by_owner[owner]?.mobilizable|| 0 };

  document.getElementById('kpi-net').innerHTML         = fmt(kpi.net) + kpiDelta(syn.variation, 'net_delta', 'net_pct');
  document.getElementById('kpi-gross').innerHTML       = fmt(kpi.gross) + kpiDelta(syn.variation, 'gross_delta');
  document.getElementById('kpi-debt').innerHTML        = fmt(kpi.debt) + kpiDelta(syn.variation, 'debt_delta', null, { invert: true });
  document.getElementById('kpi-mobilizable').innerHTML = fmt(kpi.mob) + kpiDelta(syn.variation, 'mob_delta');

  document.getElementById('kpi-net-label').textContent   = isFamily ? 'Patrimoine net famille' : `Patrimoine net — ${owner}`;
  document.getElementById('kpi-gross-label').textContent = isFamily ? 'Actifs bruts' : `Actifs bruts — ${owner}`;
  document.getElementById('kpi-debt-label').textContent  = isFamily ? 'Dettes' : `Dettes — ${owner}`;
  document.getElementById('kpi-mob-label').textContent   = isFamily ? 'Mobilisable' : `Mobilisable — ${owner}`;

  const catFiltered = isFamily
    ? totals_by_category
    : Object.fromEntries(
        Object.entries(totals_by_category).map(([cat, v]) => [
          cat, { net: v.by_owner?.[owner] || 0, by_owner: v.by_owner }
        ]).filter(([, v]) => v.net > 0)
      );

  const liqFiltered = isFamily
    ? mobilizable_by_liquidity
    : (() => {
        const pos = S.synthese._positions_cache?.[owner];
        if (!pos) return mobilizable_by_liquidity;
        const byLiq = {};
        for (const p of pos) byLiq[p.liquidity] = (byLiq[p.liquidity] || 0) + (p.mobilizable_value || 0);
        return byLiq;
      })();

  renderEntityWarnings(syn.entity_warnings || []);
  renderOwnersTable(totals_by_owner, family, Object.values(totals_by_owner).reduce((s,o)=>s+o.mobilizable,0));
  renderCatChart(catFiltered);
  renderEnvChart(syn._positions_cache, owner);
  renderHistChart(owner);
  renderSyntheseHistory();
  renderLiqBars(liqFiltered);
  renderEntitiesSynthese();
  renderAllocationTargets();
  renderPerf();
  renderTRI();
}

function renderOwnersTable(byOwner, family, totalMob) {
  const activeOwner = S.syntheseOwner;
  const familyNet = family.net || 0;
  const rows = S.config.owners.map(o => {
    const t = byOwner[o] || { gross: 0, debt: 0, net: 0, mobilizable: 0 };
    const pct = familyNet !== 0 ? ((t.net / familyNet) * 100).toFixed(1) : '—';
    const highlight = (activeOwner !== 'Famille' && activeOwner === o)
      ? ' style="background:var(--primary-light);font-weight:700"' : '';
    return `<tr class="clickable" data-dd-owner="${esc(o)}"${highlight}>
      <td>${esc(o)}</td>
      <td>${fmt(t.gross)}</td>
      <td class="${t.debt > 0 ? 'neg' : ''}">${t.debt > 0 ? fmt(t.debt) : '—'}</td>
      <td class="${t.net < 0 ? 'neg' : 'pos'}">${fmt(t.net)}</td>
      <td style="text-align:right;font-size:12px;color:var(--text-muted)">${pct !== '—' ? pct + '\u202f%' : '—'}</td>
      <td>${fmt(t.mobilizable)}</td>
    </tr>`;
  }).join('');

  document.getElementById('owners-table').innerHTML = `
    <table class="owners-table">
      <thead><tr>
        <th>Personne</th><th>Actifs</th><th>Dettes</th><th>Net</th><th>% du total</th><th>Mobilisable</th>
      </tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr class="total-row clickable" data-dd-owner="Famille">
        <td>TOTAL FAMILLE</td>
        <td>${fmt(family.gross)}</td>
        <td class="${family.debt > 0 ? 'neg' : ''}">${family.debt > 0 ? fmt(family.debt) : '—'}</td>
        <td class="${family.net < 0 ? 'neg' : 'pos'}">${fmt(family.net)}</td>
        <td style="text-align:right;font-size:12px;color:var(--text-muted)">100\u202f%</td>
        <td>${fmt(totalMob)}</td>
      </tr></tfoot>
    </table>`;

  document.getElementById('owners-table').querySelectorAll('[data-dd-owner]').forEach(tr => {
    tr.addEventListener('click', () => {
      const owner = tr.dataset.ddOwner;
      api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
        const filtered = owner === 'Famille' ? positions : positions.filter(p => p.owner === owner);
        drilldownPositions(filtered, owner, 'Patrimoine net');
      });
    });
  });
}

function renderCatChart(byCat) {
  const cats = Object.keys(byCat).filter(c => byCat[c].net > 0);
  const vals = cats.map(c => byCat[c].net);

  if (catChart) catChart.destroy();
  const ctx = document.getElementById('category-chart').getContext('2d');
  setCatChart(new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: cats,
      datasets: [{
        data: vals,
        backgroundColor: getColors().slice(0, cats.length),
        borderWidth: 2,
        borderColor: chartBorderColor(),
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      onClick: (_, elements) => {
        if (!elements.length) return;
        const cat = cats[elements[0].index];
        api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
          drilldownPositions(positions.filter(p => p.category === cat), cat, 'Catégorie');
        });
      },
      plugins: {
        legend: {
          position: 'right',
          labels: { font: { size: 11 }, padding: 10, boxWidth: 12 },
          onClick: (e, item, legend) => {
            const cat = cats[item.index];
            api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
              drilldownPositions(positions.filter(p => p.category === cat), cat, 'Catégorie');
            });
          },
        },
        tooltip: {
          callbacks: {
            label: ctx => {
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const pct = ((ctx.parsed / total) * 100).toFixed(1);
              return ` ${new Intl.NumberFormat('fr-FR').format(Math.round(ctx.parsed))}\u202f€  (${pct}%)`;
            },
            afterLabel: () => 'Cliquer pour détailler',
          },
        },
      },
    },
  }));
}

function renderEnvChart(posCache, owner) {
  const positions = owner === 'Famille'
    ? Object.values(posCache || {}).flat()
    : (posCache?.[owner] || []);

  const byEnv = {};
  for (const p of positions) {
    const k = p.envelope || 'Autre';
    byEnv[k] = (byEnv[k] || 0) + (p.net_attributed || 0);
  }
  const labels = Object.keys(byEnv).filter(k => byEnv[k] > 0);
  const vals   = labels.map(k => byEnv[k]);

  if (syntheseEnvChart) syntheseEnvChart.destroy();
  const ctx = document.getElementById('synthese-env-chart').getContext('2d');
  setSyntheseEnvChart(new Chart(ctx, doughnutConfig(labels, vals)));
}

export async function renderSyntheseHistory() {
  const card = document.getElementById('synthese-history-detail-card');
  if (!card) return;
  if (S.historique.length < 2) { card.style.display = 'none'; return; }
  card.style.display = '';

  const groupBy = document.getElementById('synthese-history-group').value;
  const owner   = S.syntheseOwner === 'Famille' ? null : S.syntheseOwner;
  const url     = `/api/historique?group_by=${groupBy}${owner ? `&owner=${encodeURIComponent(owner)}` : ''}`;

  const history = await api('GET', url);
  const dates   = history.map(h => fmtDate(h.date));

  const groups = new Set();
  history.forEach(h => Object.keys(h.by_group || {}).forEach(k => groups.add(k)));
  const groupList = [...groups].sort();

  const colors = getColors();
  const datasets = groupList.map((g, i) => ({
    label: g,
    data:  history.map(h => Math.round(h.by_group?.[g] || 0)),
    backgroundColor: colors[i % colors.length] + 'cc',
    borderColor:     colors[i % colors.length],
    borderWidth: 1.5,
    fill: true,
  }));

  if (syntheseHistChart) syntheseHistChart.destroy();
  setSyntheseHistChart(new Chart(
    document.getElementById('synthese-history-detail-chart').getContext('2d'),
    {
      type: 'bar',
      data: { labels: dates, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true, ticks: { font: { size: 11 } } },
          y: { stacked: true, ticks: {
            font: { size: 11 },
            callback: v => new Intl.NumberFormat('fr-FR', { notation: 'compact' }).format(v) + '\u202f€'
          }},
        },
        plugins: {
          legend: { position: 'bottom', labels: { font: { size: 11 }, padding: 8, boxWidth: 12 } },
          tooltip: { callbacks: {
            label: ctx => ` ${ctx.dataset.label} : ${new Intl.NumberFormat('fr-FR').format(ctx.raw)}\u202f€`,
          }},
        },
      },
    }
  ));
}

export async function loadHistorique() {
  S.historique = await api('GET', '/api/historique');
  if (S.currentTab === 'synthese') renderHistChart();
}

function renderHistChart(filterOwner = 'Famille') {
  if (!S.historique.length) return;
  const labels = S.historique.map(h => fmtDate(h.date));

  const colors = getColors();
  const fam = chartFamilyColors();
  let datasets;
  if (filterOwner === 'Famille') {
    const famData = S.historique.map(h => h.family_net);
    const ownerSets = S.config.owners.map((o, i) => ({
      label: o,
      data: S.historique.map(h => h.by_owner[o] || 0),
      borderColor: colors[i],
      backgroundColor: colors[i] + '18',
      tension: .35, borderWidth: 2, pointRadius: 4, fill: false,
    }));
    datasets = [
      { label: 'Famille', data: famData, borderColor: fam.line,
        backgroundColor: fam.bg, tension: .35,
        borderWidth: 3, pointRadius: 5, fill: true },
      ...ownerSets,
    ];
  } else {
    const i = S.config.owners.indexOf(filterOwner);
    datasets = [{
      label: filterOwner,
      data: S.historique.map(h => h.by_owner[filterOwner] || 0),
      borderColor: colors[i] || colors[0],
      backgroundColor: (colors[i] || colors[0]) + '18',
      tension: .35, borderWidth: 3, pointRadius: 5, fill: true,
    }];
  }

  if (histChart) histChart.destroy();
  const ctx = document.getElementById('history-chart').getContext('2d');
  setHistChart(new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { font: { size: 11 }, boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: ctx =>
              ` ${ctx.dataset.label} : ${new Intl.NumberFormat('fr-FR').format(Math.round(ctx.parsed.y))}\u202f€`,
          },
        },
      },
      scales: {
        y: {
          ticks: {
            callback: v =>
              new Intl.NumberFormat('fr-FR', { notation: 'compact' }).format(v) + '\u202f€',
          },
        },
      },
    },
  }));
}

function renderEntityWarnings(warnings) {
  const bar = document.getElementById('entity-warnings-bar');
  const entityHtml = warnings.map(w => {
    const msg = w.type === 'debt'
      ? `⚠ <strong>${esc(w.entity)}</strong> : total % dette = ${w.total_pct}% — double-comptage sur la dette`
      : `⚠ <strong>${esc(w.entity)}</strong> : total % détention = ${w.total_pct}% — double-comptage probable`;
    return `<div class="alert alert-error" style="margin-bottom:.5rem">${msg}</div>`;
  }).join('');

  const alertHtml = evalUserAlerts();
  bar.innerHTML = entityHtml + alertHtml;
}

function evalUserAlerts() {
  const alerts = loadUserAlerts();
  if (!alerts.length || !S.synthese) return '';
  const syn   = S.synthese;
  const owner = S.syntheseOwner;
  const isFamily = owner === 'Famille';

  const family = syn.family || {};
  const byOwner = syn.totals_by_owner || {};
  const byCat   = syn.totals_by_category || {};

  const net   = isFamily ? (family.net   || 0) : (byOwner[owner]?.net   || 0);
  const gross = isFamily ? (family.gross || 0) : (byOwner[owner]?.gross || 0);

  return alerts.map(a => {
    let actual = null;
    if (a.metric === 'cat_pct' && a.category) {
      const catNet = byCat[a.category]?.net || 0;
      actual = net > 0 ? (catNet / net) * 100 : 0;
    } else if (a.metric === 'cat_abs' && a.category) {
      actual = byCat[a.category]?.net || 0;
    } else if (a.metric === 'net')   actual = net;
    else if (a.metric === 'gross')   actual = gross;

    if (actual === null) return '';
    const triggered = a.op === '<' ? actual < a.threshold : actual > a.threshold;
    if (!triggered) return '';

    const fmtActual = a.metric.endsWith('pct') ? actual.toFixed(1) + ' %' : fmt(actual);
    const fmtThresh = a.metric.endsWith('pct') ? a.threshold + ' %' : fmt(a.threshold);
    return `<div class="alert alert-warning" style="margin-bottom:.5rem">
      ⚡ <strong>${esc(a.label || a.category || a.metric)}</strong> : ${fmtActual} ${a.op === '<' ? '&lt;' : '&gt;'} seuil ${fmtThresh}
    </div>`;
  }).join('');
}

function renderEntitiesSynthese() {
  const card = document.getElementById('entities-synthese-card');
  if (!S.entities.length) { card.style.display = 'none'; return; }
  card.style.display = '';

  const owner    = S.syntheseOwner;
  const isFamily = owner === 'Famille';
  const cache    = S.synthese?._positions_cache || {};

  const allPositions = Object.values(cache).flat();

  const rows = S.entities.map(e => {
    const linked = allPositions.filter(p => p.entity === e.name);
    const familyNet  = linked.reduce((s, p) => s + (p.net_attributed || 0), 0);
    const familyGross= linked.reduce((s, p) => s + (p.gross_attributed || 0), 0);
    const familyDebt = linked.reduce((s, p) => s + (p.debt_attributed || 0), 0);
    const familyPct  = e.gross_assets > 0 ? (familyGross / e.gross_assets * 100).toFixed(0) : '—';

    const ownerNet   = !isFamily
      ? linked.filter(p => p.owner === owner).reduce((s, p) => s + (p.net_attributed || 0), 0)
      : null;
    const ownerPct   = !isFamily && e.gross_assets > 0
      ? linked.filter(p => p.owner === owner).reduce((s, p) => s + (p.ownership_pct || 0), 0)
      : null;

    return { e, familyGross, familyDebt, familyNet, familyPct, ownerNet, ownerPct };
  });

  const personCol = !isFamily
    ? `<th style="text-align:right">${esc(owner)}</th>` : '';

  document.getElementById('entities-synthese').innerHTML = `
    <table class="owners-table">
      <thead><tr>
        <th>Entité</th>
        <th>Type</th>
        <th style="text-align:right">Actif brut total</th>
        <th style="text-align:right">Dette totale</th>
        <th style="text-align:right">Net total</th>
        <th style="text-align:right">Quote-part famille</th>
        ${personCol}
      </tr></thead>
      <tbody>${rows.map(({ e, familyGross, familyDebt, familyNet, familyPct, ownerNet, ownerPct }) => `
        <tr>
          <td><strong>${esc(e.name)}</strong></td>
          <td>${esc(e.type || '—')}</td>
          <td style="text-align:right">${fmt(e.gross_assets)}</td>
          <td style="text-align:right">${e.debt > 0 ? fmt(e.debt) : '—'}</td>
          <td style="text-align:right;font-weight:600" class="${e.net_assets >= 0 ? 'pos' : 'neg'}">${fmt(e.net_assets)}</td>
          <td style="text-align:right">
            ${fmt(familyNet)}
            <span style="font-size:11px;color:var(--text-muted);margin-left:4px">${familyPct !== '—' ? familyPct + '%' : ''}</span>
          </td>
          ${!isFamily ? `<td style="text-align:right;font-weight:700;color:var(--primary)">
            ${fmt(ownerNet)}
            ${ownerPct !== null ? `<span style="font-size:11px;color:var(--text-muted);margin-left:4px">${(ownerPct*100).toFixed(0)}%</span>` : ''}
          </td>` : ''}
        </tr>`).join('')}
      </tbody>
    </table>`;
}

function renderLiqBars(byLiq) {
  const total = Object.values(byLiq).reduce((s, v) => s + v, 0);
  const rows = S.config.liquidity_order.map(liq => {
    const val = byLiq[liq] || 0;
    const pct = total > 0 ? (val / total) * 100 : 0;
    return `<div class="liq-row">
      <div>${liqBadge(liq)}</div>
      <div class="liq-bar-bg"><div class="liq-bar" style="width:${pct.toFixed(1)}%"></div></div>
      <div class="liq-value">${fmt(val)}</div>
    </div>`;
  }).join('');
  document.getElementById('liquidity-bars').innerHTML = `<div class="liq-grid">${rows}</div>`;
}

export async function renderPerf() {
  const hist = S.historique;
  const el   = document.getElementById('perf-section');
  if (hist.length < 2) {
    el.innerHTML = '<p class="text-muted" style="font-size:13px">Au moins 2 snapshots nécessaires.</p>';
    return;
  }

  const owner    = S.syntheseOwner;
  const isFamily = owner === 'Famille';

  const netOf = h => isFamily ? h.family_net : (h.by_owner?.[owner] || 0);

  const last  = hist[hist.length - 1];
  const first = hist[0];
  const prev  = hist[hist.length - 2];

  const lastNet  = netOf(last);
  const firstNet = netOf(first);
  const prevNet  = netOf(prev);

  const variation = (curr, ref) => ref !== 0
    ? ((curr - ref) / Math.abs(ref)) * 100
    : null;

  let fluxTotal = 0;
  try {
    const flux = await api('GET', `/api/flux?date_from=${first.date}&date_to=${last.date}`);
    const filtered = isFamily ? flux : flux.filter(f => f.owner === owner);
    fluxTotal = filtered.reduce((s, f) => s + (f.amount || 0), 0);
  } catch {}

  const totalGain = lastNet - firstNet - fluxTotal;
  const varLast   = variation(lastNet, prevNet);
  const varTotal  = variation(lastNet, firstNet);

  const perfLabel = isFamily ? '' : ` — ${owner}`;

  el.innerHTML = `<div class="perf-grid">
    <div class="perf-row">
      <span class="perf-label">${fmtDate(prev.date)} → ${fmtDate(last.date)}${perfLabel}</span>
      <span class="perf-val ${varLast >= 0 ? 'pos' : 'neg'}">${varLast != null ? (varLast > 0 ? '+' : '') + varLast.toFixed(2) + ' %' : '—'}</span>
    </div>
    <div class="perf-row">
      <span class="perf-label">Depuis le début (${fmtDate(first.date)})${perfLabel}</span>
      <span class="perf-val ${varTotal >= 0 ? 'pos' : 'neg'}">${varTotal != null ? (varTotal > 0 ? '+' : '') + varTotal.toFixed(2) + ' %' : '—'}</span>
    </div>
    <div class="perf-row">
      <span class="perf-label">Gain / perte hors flux${perfLabel}</span>
      <span class="perf-val ${totalGain >= 0 ? 'pos' : 'neg'}">${(totalGain >= 0 ? '+' : '') + fmt(totalGain)}</span>
    </div>
    <div class="perf-row">
      <span class="perf-label">Flux cumulés (${fmtDate(first.date)} → ${fmtDate(last.date)})${perfLabel}</span>
      <span class="perf-val">${fmt(fluxTotal)}</span>
    </div>
  </div>`;
}

async function renderTRI() {
  const el = document.getElementById('tri-section');
  if (!el) return;
  const owner = S.syntheseOwner;
  const isFamily = owner === 'Famille';
  const url = isFamily ? '/api/tri' : `/api/tri?owner=${encodeURIComponent(owner)}`;

  try {
    const data = await api('GET', url);
    if (!data.tri || Object.keys(data.tri).length === 0) {
      el.innerHTML = '<p class="text-muted" style="font-size:13px">Pas assez de données (min. 2 snapshots + flux).</p>';
      return;
    }
    const globalTri = data.tri._global;
    const envs = Object.entries(data.tri)
      .filter(([k]) => k !== '_global')
      .sort((a, b) => b[1] - a[1]);

    let html = '<div class="tri-grid">';
    if (globalTri != null) {
      const cls = globalTri >= 0 ? 'pos' : 'neg';
      const label = isFamily ? 'TRI global' : `TRI global — ${esc(owner)}`;
      html += `<div class="tri-row tri-global">
        <span class="tri-label">${label}</span>
        <span class="tri-val ${cls}">${globalTri > 0 ? '+' : ''}${globalTri.toFixed(2)}\u202f%</span>
      </div>`;
    }
    html += `<div class="tri-period text-muted" style="font-size:12px;margin-bottom:.5rem">${fmtDate(data.first_date)} → ${fmtDate(data.date)}</div>`;
    for (const [env, tri] of envs) {
      const cls = tri >= 0 ? 'pos' : 'neg';
      html += `<div class="tri-row">
        <span class="tri-label">${esc(env)}</span>
        <span class="tri-val ${cls}">${tri > 0 ? '+' : ''}${tri.toFixed(2)}\u202f%</span>
      </div>`;
    }
    html += '</div>';
    el.innerHTML = html;
  } catch {
    el.innerHTML = '<p class="text-muted" style="font-size:13px">Erreur lors du calcul du TRI.</p>';
  }
}
