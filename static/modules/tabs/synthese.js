import { S, syntheseHistChart, setSyntheseHistChart } from '../state.js';
import { dessinerCourbe } from '../courbe.js';
import { fmt, fmtDate, esc, kpiDelta, getColors, destroyChart, parseLocaleNumber, fmtAxis, sparkline, fmtPct } from '../utils.js';
import { api } from '../api.js';
import { loadTodo } from '../todo.js';
import { loadContribution } from './contribution.js';
import { renderRepartition } from './repartition.js';
import { loadComptes } from './comptes.js';
import { loadFiscalite } from './fiscalite.js';
import { drilldownPositions } from '../drilldown.js';
import { loadUserAlerts } from '../alerts.js';
import { renderAllocationTargets } from '../targets.js';
import { toast, promptDialog } from '../dialogs.js';

function _owners() {
  return S.synthese?._owners || S.config.owners;
}

export async function loadSynthese() {
  if (!S.syntheseDate && S.dates.length) S.syntheseDate = S.dates[0];
  if (!S.syntheseDate) {
    _renderSyntheseEmpty();
    return;
  }
  _clearSyntheseEmpty();
  const [syn, positions] = await Promise.all([
    api('GET', `/api/synthese?date=${S.syntheseDate}`),
    api('GET', `/api/positions?date=${S.syntheseDate}`),
    loadWealthTarget(),
  ]);
  // Build owner list: union of config owners + actual data owners
  const dataOwners = [...new Set(positions.map(p => p.owner))];
  const allOwners = [...S.config.owners];
  for (const o of dataOwners) {
    if (!allOwners.includes(o)) allOwners.push(o);
  }
  syn._owners = allOwners;
  syn._positions_cache = {};
  for (const o of allOwners) {
    syn._positions_cache[o] = positions.filter(p => p.owner === o);
  }
  S.synthese = syn;
  renderSynthese();
}

function _renderSyntheseEmpty() {
  const host = document.getElementById('tab-synthese');
  if (!host || host.querySelector('.empty-state-synthese')) return;
  // Masquer le contenu existant pendant l'etat vide
  host.querySelectorAll('.kpi-grid, .charts-row, .card').forEach(el => el.classList.add('hidden'));
  const card = document.createElement('div');
  card.className = 'card empty-state empty-state-synthese';
  card.innerHTML = `
    <div style="text-align:center;padding:1.5rem .5rem">
      <div style="font-size:32px;margin-bottom:.5rem;opacity:.5">&#128202;</div>
      <h2 style="margin-bottom:.5rem">Aucun snapshot pour le moment</h2>
      <p class="text-muted" style="font-size:13.5px;margin-bottom:1.25rem;line-height:1.6">
        Commence par ajouter une position ou importer un fichier existant
        pour que ton patrimoine s'affiche ici.
      </p>
      <div style="display:flex;gap:.5rem;justify-content:center;flex-wrap:wrap">
        <button class="btn btn-primary" data-tab-switch="positions">+ Ajouter une position</button>
        <button class="btn btn-secondary" data-tab-switch="import">&#8645; Importer des données</button>
      </div>
    </div>`;
  host.querySelector('.page-header')?.after(card);
  // Delegue au listener global (main.js) qui appelle switchTab
}

function _clearSyntheseEmpty() {
  const host = document.getElementById('tab-synthese');
  host?.querySelector('.empty-state-synthese')?.remove();
  host?.querySelectorAll('.kpi-grid, .charts-row, .card').forEach(el => el.classList.remove('hidden'));
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

  // Variation vs precedent + YoY (par owner si pas famille)
  const variation = isFamily ? syn.variation : syn.variation?.by_owner?.[owner];
  const yoyVariation = isFamily ? syn.yoy_variation : syn.yoy_variation?.by_owner?.[owner];
  // Un seul jeu de deltas, celui de la periode choisie dans l'en-tete. Afficher
  // variation ET variation annuelle cote a cote doublait la charge de lecture
  // sur chaque indicateur, pour une comparaison qu'on ne fait pas a chaque fois.
  const varHtml = (field, pctField, opts) => {
    const surAn = S.periodeComparaison === 'an';
    const source = surAn ? yoyVariation : variation;
    if (!source) return '';
    return kpiDelta(source, field, pctField, { ...opts, label: surAn ? 'sur 1 an' : null });
  };
  // Sparklines : la tendance sous le chiffre. Series prises dans l'historique
  // deja charge, filtrees sur le titulaire courant comme le reste de la page.
  const serie = cle => (S.historique || []).map(h =>
    isFamily ? h[`family_${cle}`] : h.by_owner_detail?.[owner]?.[cle]);

  document.getElementById('kpi-net').innerHTML         = fmt(kpi.net) + varHtml('net_delta', 'net_pct')
    + sparkline(serie('net'), { couleur: 'var(--primary)' });
  document.getElementById('kpi-gross').innerHTML       = fmt(kpi.gross) + varHtml('gross_delta')
    + sparkline(serie('gross'), { couleur: 'var(--primary)' });
  // La dette prend une couleur neutre : elle n'est ni bonne ni mauvaise en soi,
  // et la teindre en rouge ferait lire une baisse comme un probleme.
  document.getElementById('kpi-debt').innerHTML        = fmt(kpi.debt) + varHtml('debt_delta', null, { invert: true })
    + sparkline(serie('debt'), { couleur: 'var(--text-muted)' });
  document.getElementById('kpi-mobilizable').innerHTML = fmt(kpi.mob) + varHtml('mob_delta')
    + sparkline(serie('mob'), { couleur: 'var(--primary)' });

  // Sous-titres : un montant seul ne se situe pas. « 530 000 € » ne dit pas
  // ce qu'il contient ; « dont 280 000 € d'immobilier » le qualifie d'un mot.
  // Ces deux valeurs suivent le titulaire choisi, comme le chiffre qu'elles
  // qualifient. Les prendre au niveau famille faisait lire « dont 890 000 EUR
  // d'immobilier » sous des actifs bruts de 950 000 EUR pour une seule
  // personne — soit 94 %, alors que le montant etait celui des quatre.
  const macro = syn.totals_by_macro || {};
  const immoMacro = macro['Patrimoine immobilier'] || {};
  const immo = isFamily ? (immoMacro.gross || 0)
                        : (immoMacro.by_owner?.[owner]?.gross || 0);

  const liqFiltered = isFamily
    ? (mobilizable_by_liquidity || {})
    : (() => {
        const pos = S.synthese._positions_cache?.[owner];
        if (!pos) return mobilizable_by_liquidity || {};
        const byLiq = {};
        for (const p of pos) byLiq[p.liquidity] = (byLiq[p.liquidity] || 0) + (p.mobilizable_value || 0);
        return byLiq;
      })();
  const court = liqFiltered['J0–J1'] || 0;
  const sous = (id, txt) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = txt;
  };
  sous('kpi-gross-sub', immo ? `dont ${fmt(immo)} d'immobilier` : '');
  sous('kpi-debt-sub', kpi.gross
    ? `${fmtPct(kpi.debt / kpi.gross * 100)} du brut`
    : '');
  sous('kpi-mob-sub', kpi.net
    ? `${fmtPct(kpi.mob / kpi.net * 100, 0)} du net`
      + (court ? ` · ${fmt(court)} sous 24\u202fh` : '')
    : '');

  document.getElementById('kpi-net-label').textContent   = isFamily ? 'Patrimoine net famille' : `Patrimoine net — ${owner}`;
  document.getElementById('kpi-gross-label').textContent = isFamily ? 'Actifs bruts' : `Actifs bruts — ${owner}`;
  document.getElementById('kpi-debt-label').textContent  = isFamily ? 'Dettes' : `Dettes — ${owner}`;
  document.getElementById('kpi-mob-label').textContent   = isFamily ? 'Mobilisable' : `Mobilisable — ${owner}`;

  renderRepartition();
  loadContribution();
  loadComptes();
  loadFiscalite();
  renderEntityWarnings(syn.entity_warnings || []);
  renderHistChart();
  renderSyntheseHistory();
  renderLiqBars(liqFiltered);
  renderEntitiesSynthese();
  renderAllocationTargets();
  renderSnapshotDiff(owner, isFamily);
  renderSnapshotNote(syn);
  renderWealthTarget(kpi.net);
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

  // Douze series empilees et une legende de douze entrees : on distingue les
  // trois plus grosses, les autres forment un liseré illisible qui occupe la
  // moitie de la legende. On garde les six premieres par poids et on regroupe
  // le reste, qui reste ainsi compte sans encombrer.
  const MAX_SERIES = 6;
  const poids = {};
  history.forEach(h => Object.entries(h.by_group || {}).forEach(([k, v]) => {
    poids[k] = Math.max(poids[k] || 0, Math.abs(v || 0));
  }));
  const classees = Object.keys(poids).sort((a, b) => poids[b] - poids[a]);
  const gardees = classees.slice(0, MAX_SERIES);
  const fondues = classees.slice(MAX_SERIES);

  const serie = g => history.map(h => ({ x: _ts(h.date), y: Math.round(h.by_group?.[g] || 0) }));
  const colors = getColors();
  const datasets = gardees.map((g, i) => ({
    label: g,
    data:  serie(g),
    backgroundColor: colors[i % colors.length] + 'cc',
    borderColor:     colors[i % colors.length],
    borderWidth: 1.5, tension: .25, pointRadius: 2,
    fill: true,
  }));
  if (fondues.length) {
    datasets.push({
      label: `${fondues.length} autres`,
      data: history.map(h => ({
        x: _ts(h.date),
        y: Math.round(fondues.reduce((t, g) => t + (h.by_group?.[g] || 0), 0)),
      })),
      backgroundColor: getComputedStyle(document.documentElement)
        .getPropertyValue('--text-muted').trim() + '55',
      borderColor: 'var(--text-muted)',
      borderWidth: 1.5, tension: .25, pointRadius: 2, fill: true,
    });
  }

  destroyChart(syntheseHistChart);
  setSyntheseHistChart(new Chart(
    document.getElementById('synthese-history-detail-chart').getContext('2d'),
    {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onClick: (_, elements) => {
          if (!elements.length) return;
          const el = elements[0];
          const dateLabel = history[el.index]?.date;
          const group = groupList[el.datasetIndex];
          if (!dateLabel || !group) return;
          api('GET', `/api/positions?date=${dateLabel}`).then(positions => {
            let filtered = owner ? positions.filter(p => p.owner === owner) : positions;
            if (groupBy === 'category')      filtered = filtered.filter(p => p.category === group);
            else if (groupBy === 'envelope')  filtered = filtered.filter(p => (p.envelope || 'Autre') === group);
            else if (groupBy === 'owner')     filtered = filtered.filter(p => p.owner === group);
            drilldownPositions(filtered, `${group} — ${fmtDate(dateLabel)}`, `Évolution par ${groupBy}`, { showOwner: groupBy !== 'owner' });
          });
        },
        scales: {
          x: { type: 'linear', ticks: { font: { size: 11 }, maxRotation: 0, autoSkip: true, callback: _tsTick } },
          y: { stacked: true, ticks: {
            font: { size: 11 },
            callback: fmtAxis
          }},
        },
        plugins: {
          legend: { position: 'bottom', labels: { font: { size: 11 }, padding: 8, boxWidth: 12 } },
          tooltip: { callbacks: {
            title: _tsTitle,
            label: ctx => ` ${ctx.dataset.label} : ${fmt(ctx.parsed.y)}`,
            afterBody: () => 'Cliquer pour détailler',
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

// ─── Axe temporel (Chart.js sans adaptateur) : axe X 'linear' + timestamps
// -> espacement proportionnel au temps (points a leur vraie date).
const _ts      = d => new Date(d + 'T12:00:00').getTime();
const _tsTick  = v => new Date(v).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' });
const _tsTitle = items => items.length ? new Date(items[0].parsed.x).toLocaleDateString('fr-FR') : '';

/** « Evolution du patrimoine net » : la courbe du titulaire choisi, et sous
 *  elle ce qui explique la variation — l'epargne versee, puis l'effet des
 *  marches. Comparer ce patrimoine a un indice serait trompeur : il grossit
 *  aussi de ce qu'on y verse. La comparaison a un ETF vit dans Performance,
 *  ou le TWR neutralise les versements.
 *
 *  Le titulaire se lit dans S : appelee sans argument apres un rechargement
 *  de l'historique, l'ancienne version revenait a la famille sous un filtre
 *  nominatif. */
function renderHistChart() {
  const hote = document.getElementById('evolution-courbe');
  if (!hote || !S.historique.length) return;
  const owner = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : null;
  const points = S.historique.map(h => ({
    date: h.date, v: owner ? (h.by_owner?.[owner] || 0) : h.family_net,
  }));
  const qui = owner || 'Famille';
  const debut = points[0], fin = points[points.length - 1];
  dessinerCourbe(hote, {
    series: [{ nom: `Patrimoine net — ${qui}`, couleur: 'var(--primary)', points, aire: true }],
    formatV: v => fmt(v),
    aide: `Patrimoine net ${qui} : ${fmt(debut.v)} le ${fmtDate(debut.date)}, ${fmt(fin.v)} le ${fmtDate(fin.date)}.`,
    onPoint: date => api('GET', `/api/positions?date=${date}`).then(positions => {
      const lignes = owner ? positions.filter(p => p.owner === owner) : positions;
      drilldownPositions(lignes, `${qui} — ${fmtDate(date)}`, 'Composition à cette date', { showOwner: !owner });
    }),
  });
  const sous = document.getElementById('evolution-sous');
  if (sous) sous.textContent = `${points.length} arrêtés · du ${fmtDate(debut.date)} au ${fmtDate(fin.date)}`;
  _legendeEvolution(owner, debut, fin);
}

async function _legendeEvolution(owner, debut, fin) {
  const hote = document.getElementById('evolution-legende');
  if (!hote) return;
  const variation = fin.v - debut.v;
  const pct = debut.v ? variation / Math.abs(debut.v) * 100 : null;
  let decompo = '';
  try {
    const q = new URLSearchParams({ limit: '40' });
    if (owner) q.set('owner', owner);
    const d = await api('GET', `/api/contribution?${q}`, null, { silent: true });
    if (d.periodes?.length) {
      decompo = `<span><i style="background:var(--chart-4)"></i>Épargne versée <b>${fmtSigne(d.total_apports)}</b></span>`
              + `<span><i style="background:var(--chart-1)"></i>Marchés <b>${fmtSigne(d.total_performance)}</b></span>`;
    }
  } catch { /* la decomposition est un plus : sans elle, la courbe reste lisible */ }
  hote.innerHTML = `
    <span>Variation <b>${fmtSigne(variation)}</b>${
      pct != null ? ` <b>${fmtPct(pct, 1, true)}</b>` : ''}</span>
    ${decompo}
    <span class="courbe-note">Chaque arrêté ouvre sa composition</span>`;
}

const fmtSigne = v => `${v >= 0 ? '+' : '−'}${fmt(Math.abs(v))}`;

function renderEntityWarnings(warnings) {
  // Ces avertissements ne s'affichent plus dans leur propre bandeau : ils
  // rejoignent la zone « À traiter », avec les signaux calcules en base. Un
  // probleme se lit au meme endroit quelle que soit son origine.
  const signaux = [
    ...warnings.map(w => ({
      cle: `entite-${w.entity}-${w.type}`,
      severite: 'warn',
      titre: w.type === 'debt'
        ? `${w.entity} : total % dette = ${w.total_pct} %`
        : `${w.entity} : total % détention = ${w.total_pct} %`,
      detail: w.type === 'debt'
        ? 'Double-comptage sur la dette'
        : 'Double-comptage probable de la détention',
      action: 'Ouvrir Entités',
      onglet: 'entites',
    })),
    ...evalUserAlerts(),
  ];
  document.getElementById('entity-warnings-bar').innerHTML = '';
  loadTodo(S.syntheseDate, signaux);
}

function evalUserAlerts() {
  const alerts = loadUserAlerts();
  if (!alerts.length || !S.synthese) return [];
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

    if (actual === null) return null;
    const triggered = a.op === '<' ? actual < a.threshold : actual > a.threshold;
    if (!triggered) return null;

    const fmtActual = a.metric.endsWith('pct') ? fmtPct(actual) : fmt(actual);
    const fmtThresh = a.metric.endsWith('pct') ? a.threshold + ' %' : fmt(a.threshold);
    return {
      cle: `seuil-${a.metric}-${a.category || ''}`,
      severite: 'info',
      titre: `${a.label || a.category || a.metric} : ${fmtActual}`,
      detail: `Seuil que vous avez défini : ${a.op === '<' ? 'moins de' : 'plus de'} ${fmtThresh}`,
      action: null, onglet: null,
    };
  }).filter(Boolean);
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
    const familyPct  = e.gross_assets > 0 ? fmtPct(familyGross / e.gross_assets * 100, 0) : '—';

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
            <span style="font-size:11px;color:var(--text-muted);margin-left:4px">${familyPct !== '—' ? familyPct : ''}</span>
          </td>
          ${!isFamily ? `<td style="text-align:right;font-weight:700;color:var(--primary)">
            ${fmt(ownerNet)}
            ${ownerPct !== null ? `<span style="font-size:11px;color:var(--text-muted);margin-left:4px">${fmtPct(ownerPct * 100, 0)}</span>` : ''}
          </td>` : ''}
        </tr>`).join('')}
      </tbody>
    </table>`;
}

/** « Si vous aviez besoin d'argent » : ce qui est disponible, par delai.
 *
 *  Les montants sont CUMULES : sous une semaine, on dispose aussi de ce qui
 *  etait deja mobilisable sous 24 h. Afficher des tranches disjointes obligeait
 *  a les additionner de tete pour repondre a la seule question qui compte —
 *  « de combien je dispose d'ici la ? ».
 */
function renderLiqBars(byLiq) {
  const DELAIS = [
    { cles: ['J0–J1'], libelle: 'Sous 24 heures' },
    { cles: ['J0–J1', 'J2–J7'], libelle: 'Sous une semaine' },
    { cles: ['J0–J1', 'J2–J7', 'J8–J30'], libelle: 'Sous un mois' },
    { cles: ['J0–J1', 'J2–J7', 'J8–J30', '30J+'], libelle: 'Au-delà' },
  ];
  const total = Object.values(byLiq).reduce((s, v) => s + v, 0);
  const bloque = byLiq['Bloqué'] || 0;
  const cumule = d => d.cles.reduce((s, k) => s + (byLiq[k] || 0), 0);
  const max = Math.max(...DELAIS.map(cumule), bloque, 1);

  const ligne = (libelle, valeur, couleur) => `
    <div class="dispo-ligne">
      <span class="dispo-n">${libelle}</span>
      <span class="dispo-v">${fmt(valeur)}</span>
      <span class="dispo-track"><span class="dispo-fill"
            style="width:${((valeur / max) * 100).toFixed(1)}%;background:${couleur}"></span></span>
    </div>`;

  document.getElementById('liquidity-bars').innerHTML = `
    <div class="dispo">
      ${DELAIS.map((d, i) => ligne(d.libelle, cumule(d),
          `var(--chart-${i === 3 ? 2 : 1})`)).join('')}
      ${bloque ? ligne('Bloqué', bloque, 'var(--chart-11)') : ''}
    </div>
    ${total ? `<p class="dispo-note">Les montants sont cumulés : chaque délai
      inclut ce qui était déjà disponible avant.</p>` : ''}`;
}

async function renderSnapshotDiff(owner, isFamily) {
  const el = document.getElementById('snapshot-diff');
  if (!el) return;
  const params = new URLSearchParams({ date: S.syntheseDate || '' });
  if (!isFamily && owner) params.set('owner', owner);
  let data;
  try { data = await api('GET', `/api/snapshot-diff?${params}`, null, { silent: true }); }
  catch { el.innerHTML = ''; return; }
  if (!data || !data.from_date) {
    el.innerHTML = '<p class="text-muted" style="font-size:13px">Aucun snapshot précédent à comparer.</p>';
    return;
  }
  const moves = (data.movements || []).filter(m => Math.abs(m.delta) >= 1 || m.status !== 'changed');
  if (!moves.length) {
    el.innerHTML = `<p class="text-muted" style="font-size:13px">Aucun mouvement depuis le ${fmtDate(data.from_date)}.</p>`;
    return;
  }
  const t = data.totals || {};
  const badge = s => s === 'new' ? ' <span class="h-badge h-badge-fresh">nouveau</span>'
    : s === 'closed' ? ' <span class="h-badge h-badge-expired">clôturé</span>' : '';
  // La VARIATION est l'information ; l'avant et l'apres ne servaient qu'a la
  // calculer de tete. Le montant passe donc a gauche, en gros, et le compte a
  // droite — on lit d'abord ce qui a bouge, ensuite ou.
  el.innerHTML = `
    <p class="mv-total">Variation nette
      <b class="${(t.delta || 0) >= 0 ? 'pos' : 'neg'}">${(t.delta || 0) >= 0 ? '+' : ''}${
        fmt(t.delta || 0)}</b> depuis le ${fmtDate(data.from_date)}</p>
    <div class="mv-liste">
      ${moves.map(m => `
        <div class="mv-ligne">
          <span class="mv-montant ${m.delta >= 0 ? 'pos' : 'neg'}">${
            m.delta >= 0 ? '+' : '−'}${fmt(Math.abs(m.delta))}</span>
          <span class="mv-ou">${esc(m.label || '—')}${badge(m.status)}</span>
          <span class="mv-qui">${esc([m.owner, m.establishment].filter(Boolean).join(' · '))}</span>
        </div>`).join('')}
    </div>`;
}

// ─── Snapshot notes ──────────────────────────────────────────────────────

function renderSnapshotNote(syn) {
  const bar = document.getElementById('snapshot-note-bar');
  if (!bar) return;
  const note = syn.snapshot_note;
  const date = syn.date;

  if (!note) {
    bar.style.display = 'none';
    bar.innerHTML = '';
  } else {
    bar.style.display = '';
    bar.innerHTML = `<div class="snapshot-note">
      <span class="snapshot-note-icon">&#128221;</span>
      <span class="snapshot-note-text">${esc(note)}</span>
      <button class="btn-icon" id="btn-edit-snapshot-note" title="Modifier la note">&#9998;</button>
    </div>`;
    bar.querySelector('#btn-edit-snapshot-note')?.addEventListener('click', () => openSnapshotNoteEditor(date, note));
  }

  let noteBtn = document.getElementById('btn-add-snapshot-note');
  if (noteBtn) {
    noteBtn.innerHTML = note ? '&#128221; Modifier la note' : '&#128221; Note du snapshot';
    noteBtn.onclick = () => openSnapshotNoteEditor(date, note || '');
  }
}

async function openSnapshotNoteEditor(date, currentNote) {
  const note = await promptDialog(`Note pour le snapshot du ${fmtDate(date)}`, {
    defaultValue: currentNote || '', placeholder: 'Ex: achat RP, krach mars 2025…', confirmText: 'Enregistrer'
  });
  if (note === null) return; // cancelled
  await api('PUT', '/api/snapshot-notes', { date, notes: note });
  if (S.synthese) S.synthese.snapshot_note = note || null;
  renderSnapshotNote(S.synthese);
  toast(note ? 'Note enregistrée' : 'Note supprimée');
}

// ─── Wealth target gauge ─────────────────────────────────────────────────

let _wealthTarget = null;

export async function loadWealthTarget() {
  try {
    const data = await api('GET', '/api/wealth-target');
    _wealthTarget = data?.target || null;
  } catch { _wealthTarget = null; }
}

function renderWealthTarget(currentNet) {
  const bar = document.getElementById('wealth-target-bar');
  const menuBtn = document.getElementById('btn-open-wealth-target');
  if (menuBtn) {
    menuBtn.innerHTML = _wealthTarget ? '&#127919; Modifier objectif patrimoine' : '&#127919; Objectif patrimoine';
    menuBtn.onclick = openWealthTargetEditor;
  }
  if (!bar) return;

  if (!_wealthTarget) {
    bar.style.display = 'none';
    bar.innerHTML = '';
    return;
  }

  const target = _wealthTarget;
  const pct = target > 0 ? Math.min((currentNet / target) * 100, 100) : 0;
  const cls = pct >= 100 ? 'pos' : '';

  bar.style.display = '';
  // L'objectif rejoint le chiffre qu'il vise : une trajectoire n'a de sens
  // qu'accolee au montant qu'elle projette, pas dans un bandeau separe en haut
  // de page. Le bandeau disparait donc, la jauge vit dans le heros.
  bar.style.display = 'none';
  bar.innerHTML = '';

  const hote = document.getElementById('kpi-hero-goal');
  if (!hote) return;

  // Rythme observe sur l'historique : de quoi dire QUAND l'objectif tombe, et
  // pas seulement ou l'on en est.
  const h = S.historique || [];
  let projection = '';
  if (h.length >= 2 && currentNet < target) {
    const debut = h[0], fin = h[h.length - 1];
    const jours = (new Date(fin.date) - new Date(debut.date)) / 86400000;
    const progression = (fin.family_net || 0) - (debut.family_net || 0);
    if (jours > 30 && progression > 0) {
      const parMois = progression / (jours / 30.44);
      const mois = (target - currentNet) / parMois;
      const quand = new Date();
      quand.setMonth(quand.getMonth() + Math.ceil(mois));
      projection = mois < 120
        ? `Atteint en <b>${quand.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' })}</b> au rythme actuel`
        : '';
    }
  }

  hote.className = 'hero-goal';
  hote.innerHTML = `
    <div class="g-track"><span class="g-fill" style="width:${pct.toFixed(1)}%"></span></div>
    <div class="g-foot">
      <span>Objectif <b>${fmt(target)}</b> · ${fmtPct(pct)} atteint</span>
      <span>${projection || `Reste <b>${fmt(Math.max(target - currentNet, 0))}</b>`}</span>
    </div>`;
}

async function openWealthTargetEditor() {
  const current = _wealthTarget ? String(_wealthTarget) : '';
  const val = await promptDialog('Objectif patrimoine net (€)', {
    defaultValue: current, placeholder: 'Laisser vide pour supprimer', confirmText: 'Enregistrer'
  });
  if (val === null) return;
  const target = val.trim() ? parseLocaleNumber(val) : null;
  if (val.trim() && (isNaN(target) || target <= 0)) { toast('Montant invalide', 'error'); return; }
  await api('PUT', '/api/wealth-target', { target });
  _wealthTarget = target;
  const kpiNet = S.synthese?.family?.net || 0;
  renderWealthTarget(kpiNet);
  toast(target ? 'Objectif enregistré' : 'Objectif supprimé');
}
