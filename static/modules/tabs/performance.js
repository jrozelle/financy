import { api } from '../api.js';
import { S, perfChart, setPerfChart } from '../state.js';
import { fmt, esc, fmtDate, getColors, chartBorderColor, destroyChart } from '../utils.js';

// Etat local : donnees, groupe isole, maille, tri de la liste.
// Le tri par defaut est celui que produit l'API — valeur decroissante — pour
// qu'ouvrir l'onglet et cliquer un en-tete ne donnent pas deux ordres sans
// rapport. Il survit au rechargement des donnees : reordonner puis changer de
// maille ne doit pas ramener a l'ordre initial.
const V = { data: null, focus: null, group: 'account',
            sort: { col: 'value', dir: 'desc' } };

// Cles de tri. Le nom concatene l'enveloppe et le libelle de compte, dans
// l'ordre ou la ligne les affiche.
const SORTS = {
  name: g => `${g.envelope || g.label || ''} ${g.account_label || ''}`.trim(),
  twr: g => g.twr,
  value: g => g.value,
};
// Sens du premier clic : decroissant sur un chiffre — on cherche le plus
// grand —, croissant sur un texte.
const SORT_DIR0 = { name: 'asc', twr: 'desc', value: 'desc' };

function sortRows(rows) {
  const { col, dir } = V.sort;
  const cle = SORTS[col] || SORTS.value;
  const sens = dir === 'asc' ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const x = cle(a), y = cle(b);
    // Une valeur absente reste en bas dans les deux sens : un groupe dont le
    // rendement n'est pas mesurable n'a pas a prendre la tete de la liste.
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return typeof x === 'string' ? sens * x.localeCompare(y, 'fr') : sens * (x - y);
  });
}

function setSort(col) {
  V.sort = V.sort.col === col
    ? { col, dir: V.sort.dir === 'asc' ? 'desc' : 'asc' }
    : { col, dir: SORT_DIR0[col] || 'desc' };
  renderPerformance();
}

/** Nombre brut. `fmt` de utils.js ajoute toujours l'euro : inutilisable pour un %. */
const n = (v, dec = 0) => v == null ? '—'
  : new Intl.NumberFormat('fr-FR', { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(v);

const pct = (v, dec = 2) => v == null ? '—'
  : `${v >= 0 ? '+' : '−'}${n(Math.abs(v) * 100, dec)} %`;

const sign = v => v == null ? '' : (v >= 0 ? 'positive' : 'negative');

function duree(days) {
  if (days == null) return '—';
  if (days < 62) return `${days} j`;
  const m = Math.round(days / 30.44);
  return m < 24 ? `${m} mois` : `${n(days / 365.25, 1)} ans`;
}

export async function loadPerformance() {
  const owner = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : null;
  const qs = new URLSearchParams({ group: V.group });
  if (owner) qs.set('owner', owner);
  V.data = await api('GET', `/api/performance?${qs}`);
  V.focus = null;
  renderPerformance();
}

// Les groupes sans rendement calculable restent affiches : les masquer ferait
// diverger le total de cet onglet de celui de la synthese, sans explication.
// Ne restent affiches que les comptes dont un rendement se mesure. Sont ecartes
// les comptes courants et les objets de valeur (aucun rendement a mesurer), et
// les capitaux propres negatifs (aucun rendement calculable sur une base
// negative, quel que soit l'historique). Le decompte figure dans l'en-tete pour
// que le total reste explicable.
const HIDDEN = new Set(['non_measurable', 'negative', 'closed']);
const visible = () => (V.data?.groups || []).filter(g => !HIDDEN.has(g.status));
const LABELS = { insufficient: 'historique insuffisant', negative: 'capital négatif',
                 non_measurable: 'trésorerie, aucun rendement',
                 closed: 'compte clos' };
const current = () => V.focus
  ? visible().find(g => g.key === V.focus) || V.data.global
  : V.data.global;

export function renderPerformance() {
  const d = V.data;
  const body = document.getElementById('perf-body');
  const empty = document.getElementById('perf-empty');
  if (!d || d.insufficient || !d.groups?.length) {
    body?.classList.add('hidden');
    empty?.classList.remove('hidden');
    return;
  }
  body?.classList.remove('hidden');
  empty?.classList.add('hidden');
  renderHeader(d);
  renderKpi(d);
  renderList(d);
  renderChart(d);
}

function renderHeader(d) {
  const host = document.getElementById('perf-controls');
  if (!host) return;
  const hidden = (d.groups || []).filter(g => HIDDEN.has(g.status)).length;
  host.innerHTML = `
    <div class="seg" role="group" aria-label="Maille d'agrégation">
      <button type="button" class="seg-btn ${V.group === 'account' ? 'is-on' : ''}" data-group="account"
        title="Un compte = une enveloppe chez un établissement, pour une personne. Maille correcte : chaque contrat a son propre rendement.">Par compte</button>
      <button type="button" class="seg-btn ${V.group === 'envelope' ? 'is-on' : ''}" data-group="envelope"
        title="Fusionne tous les contrats d'une même enveloppe, toutes personnes et tous établissements confondus. Un écart avec la vue par compte signale que l'enveloppe agrège des contrats sans rapport.">Par enveloppe</button>
    </div>
    ${V.focus ? `<button type="button" class="btn btn-sm" id="perf-reset">↩ Tout afficher</button>` : ''}
    <span class="perf-meta">${d.dates.length} arrêtés · ${fmtDate(d.first_date)} → ${fmtDate(d.date)}${
      d.excluded?.length ? ` · <span title="${esc(d.excluded.map(e =>
        `${e.label} — ${LABELS[e.status] || e.status}${
          e.status === 'closed' ? ` (dernière valeur le ${fmtDate(e.last_date)})` : ''}`
        ).join(' · '))}">${
        d.excluded.length} compte${d.excluded.length > 1 ? 's' : ''} hors calcul</span>` : ''}</span>`;
  host.querySelectorAll('[data-group]').forEach(b => b.addEventListener('click', () => {
    if (V.group === b.dataset.group) return;
    V.group = b.dataset.group;
    loadPerformance();
  }));
  document.getElementById('perf-reset')?.addEventListener('click', () => {
    V.focus = null; renderPerformance();
  });
}

function renderKpi(d) {
  const host = document.getElementById('perf-kpi');
  if (!host) return;
  const g = current();
  if (!g) { host.innerHTML = ''; return; }
  // Meme gabarit que la synthese (.kpi-card + lisere colore) : deux onglets qui
  // presentent des indicateurs doivent se ressembler.
  const comptes = g.accounts || (V.data.groups || []).filter(x => x.status === 'ok').length;
  const tiles = [
    ['', `Valeur au ${fmtDate(d.date)}`, fmt(g.value),
      V.focus ? esc(g.label) : `${comptes} compte${comptes > 1 ? 's' : ''} mesuré${comptes > 1 ? 's' : ''}`],
    ['kpi-gross', 'TWR cumulée', pct(g.twr), `sur ${duree(g.days)}`, sign(g.twr)],
    ['kpi-mobilizable', 'TWR annualisée',
      g.annualisable ? pct(g.twr_annualise) : '—',
      g.annualisable ? 'équivalent par an'
        : `moins de ${d.min_days_annualise} j d'historique`,
      g.annualisable ? sign(g.twr_annualise) : ''],
    // La periode est nommee sur la tuile elle-meme : "de la periode" sans dire
    // laquelle obligeait a aller la chercher a l'autre bout de l'ecran.
    ['kpi-debt', 'Apports nets', fmt(g.flux_net),
      `du ${fmtDate(d.first_date)} au ${fmtDate(d.date)} — `
      + `${g.flux_count} mouvement${g.flux_count > 1 ? 's' : ''}, hors dividendes`],
  ];
  host.innerHTML = tiles.map(([variant, k, v, s, cl = '']) => `
    <div class="kpi-card ${variant}">
      <div class="kpi-label">${esc(k)}</div>
      <div class="kpi-value ${cl}">${v}</div>
      <div class="kpi-sub">${s}</div>
    </div>`).join('');
}

/** Liste en grille plutot qu'un tableau : sept colonnes de chiffres se lisent
 *  mal, et la barre donne l'ordre de grandeur avant la lecture du nombre. */
function renderList(d) {
  const host = document.getElementById('perf-list');
  if (!host) return;
  const rows = sortRows(visible());
  const span = Math.max(0.02, ...rows.map(g => Math.abs(g.twr || 0)));
  const total = rows.filter(g => g.status === 'ok').length;
  const line = g => {
    const w = g.twr == null ? 0 : Math.abs(g.twr) / span * 50;
    const neg = (g.twr || 0) < 0;
    const sub = [g.establishment, g.owner].filter(Boolean).join(' · ')
      || (g.categories || []).join(', ');
    // Un seul badge de statut par ligne : "valeur negative" et "non mesurable"
    // cote a cote se contredisaient. Et une TWR negative est un resultat normal,
    // pas une anomalie : rien ne la signale.
    const STATUS_BADGE = {
      insufficient: ['historique insuffisant',
        'Il faut deux valorisations successives pour mesurer un rendement.'],
      negative: ['capital négatif',
        "Valeur nulle ou négative sur la période : un rendement n'a pas de sens sur une dette nette ou un apport en compte courant."],
    };
    const st = STATUS_BADGE[g.status];
    const flags = [
      st ? `<span class="badge badge-blk" title="${esc(st[1])} Hors du total.">${st[0]}</span>` : '',
      g.suspect_periods?.length ? `<span class="badge badge-30"
        title="${esc(g.suspect_periods.map(x =>
          `${fmtDate(x.from)} → ${fmtDate(x.to)} : ${pct(x.change)} inexpliqué (${
            x.delta >= 0 ? '+' : '−'}${n(Math.abs(x.delta))} € de variation, ${
            x.flux ? n(x.flux) + ' € de flux déclaré' : 'aucun flux déclaré'})`).join(' · '))}">écart inexpliqué</span>` : '',
    ].join(' ');
    return `
      <div class="perf-item${V.focus === g.key ? ' is-focus' : ''}" data-key="${esc(g.key)}"
           tabindex="0" role="button" aria-pressed="${V.focus === g.key}">
        <div class="perf-name">
          <span class="perf-title">${esc(g.envelope || g.label)}${
            g.account_label ? ` <span class="perf-account">${esc(g.account_label)}</span>` : ''}</span>
          ${sub ? `<span class="perf-sub">${esc(sub)}</span>` : ''}
        </div>
        <div class="perf-bar" aria-hidden="true">
          <span class="perf-bar-fill ${neg ? 'neg' : 'pos'}"
                style="width:${w.toFixed(1)}%;${neg ? 'right' : 'left'}:50%"></span>
        </div>
        <div class="perf-num ${sign(g.twr)}">${pct(g.twr)}
          <span class="perf-num-sub">${
            g.annualisable ? pct(g.twr_annualise) + ' /an'
            : g.days != null ? duree(g.days)
            : `${g.dates_count} arrêté${g.dates_count > 1 ? 's' : ''}`}</span>
        </div>
        <div class="perf-val">${fmt(g.value)}
          <span class="perf-num-sub">${flags || (g.flux_count ? `${g.flux_count} flux` : '')}</span>
        </div>
      </div>`;
  };
  const g = d.global;
  // En-tetes triables. La colonne de barres n'en est pas une : elle donne a
  // voir la TWR, que son propre en-tete trie deja.
  const th = (col, texte, cls = '') => {
    const actif = V.sort.col === col;
    const sens = actif ? V.sort.dir : null;
    return `<span class="perf-th ${cls}${actif ? ' is-sorted' : ''}" data-sort="${col}"
        role="button" tabindex="0" aria-sort="${
          actif ? (sens === 'asc' ? 'ascending' : 'descending') : 'none'}"
        title="Trier par ${esc(texte.toLowerCase())}${
          actif ? (sens === 'asc' ? ', décroissant' : ', croissant') : ''}"
      >${texte}<i class="perf-caret">${actif ? (sens === 'asc' ? '▲' : '▼') : ''}</i></span>`;
  };
  host.innerHTML = `
    <div class="perf-head">
      ${th('name', V.group === 'account' ? 'Compte' : 'Enveloppe')}
      <span class="perf-axis"><i>−</i><i>0</i><i>+</i></span>
      ${th('twr', 'TWR', 'ta-r')}${th('value', 'Valeur', 'ta-r')}
    </div>
    ${rows.map(line).join('')}
    ${g && !V.focus && total > 1 ? `<div class="perf-item is-total">
      <div class="perf-name"><span class="perf-title">Ensemble mesurable</span>
        <span class="perf-sub">${(g.groups || []).length} ${V.group === 'account' ? 'compte' : 'enveloppe'}${(g.groups || []).length > 1 ? 's' : ''}</span></div>
      <div class="perf-bar"></div>
      <div class="perf-num ${sign(g.twr)}">${pct(g.twr)}
        <span class="perf-num-sub">${g.annualisable ? pct(g.twr_annualise) + ' /an' : duree(g.days)}</span></div>
      <div class="perf-val">${fmt(g.value)}</div>
    </div>` : ''}
    <p class="perf-note">TWR annualisée à partir de ${d.min_days_annualise} jours d'historique —
    en dessous, la durée est indiquée à la place. Cliquez une ligne pour l'isoler,
    un en-tête pour trier.</p>`;
  host.querySelectorAll('.perf-th[data-sort]').forEach(el => {
    const trier = () => setSort(el.dataset.sort);
    el.addEventListener('click', trier);
    el.addEventListener('keydown', ev => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); trier(); }
    });
  });
  host.querySelectorAll('.perf-item[data-key]').forEach(el => {
    const pick = () => {
      V.focus = V.focus === el.dataset.key ? null : el.dataset.key;
      renderPerformance();
    };
    el.addEventListener('click', pick);
    el.addEventListener('keydown', ev => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(); }
    });
  });
}

function renderChart(d) {
  const el = document.getElementById('perf-chart');
  if (!el || typeof Chart === 'undefined') return;
  destroyChart(perfChart);
  const colors = getColors();
  const border = chartBorderColor();
  const shown = visible();
  // La couleur suit le groupe, jamais son rang : isoler une ligne ne doit pas
  // repeindre les autres.
  const hue = g => colors[Math.max(0, d.groups.findIndex(x => x.key === g.key)) % colors.length];
  const series = (V.focus ? shown.filter(g => g.key === V.focus) : shown)
    .filter(g => g.serie?.length > 1);
  const datasets = series.map(g => ({
    label: g.label, borderColor: hue(g), backgroundColor: hue(g),
    data: g.serie.map(p => ({ x: p.date, y: p.index })),
    borderWidth: 2, pointRadius: 2.5, pointHoverRadius: 6, tension: 0,
  }));
  if (!V.focus && d.global && series.length > 1) {
    datasets.push({
      label: 'Ensemble', data: d.global.serie.map(p => ({ x: p.date, y: p.index })),
      borderColor: border, backgroundColor: border,
      borderWidth: 2, borderDash: [5, 3], pointRadius: 0, tension: 0,
    });
  }
  const labels = [...new Set(series.flatMap(g => g.serie.map(p => p.date)))].sort();
  const toggle = lbl => {
    const hit = d.groups.find(g => g.label === lbl);
    if (!hit) return;
    V.focus = V.focus === hit.key ? null : hit.key;
    renderPerformance();
  };
  setPerfChart(new Chart(el.getContext('2d'), {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true, maintainAspectRatio: false, parsing: false,
      interaction: { mode: 'index', intersect: false },
      onClick(ev, els) {
        if (els.length) toggle(this.data.datasets[els[0].datasetIndex].label);
      },
      scales: {
        x: { type: 'category', labels, grid: { display: false },
             ticks: { autoSkip: true, maxRotation: 0,
                      callback(v) { return fmtDate(this.getLabelForValue(v)); } } },
        y: { title: { display: true, text: 'base 100 au premier arrêté' },
             grid: { color: border } },
      },
      plugins: {
        legend: { position: 'bottom',
                  labels: { usePointStyle: true, pointStyle: 'line', boxWidth: 24, padding: 12 },
                  onClick: (ev, item) => toggle(item.text) },
        tooltip: {
          callbacks: {
            title: items => fmtDate(items[0].label),
            label: it => `${it.dataset.label} : ${pct(it.parsed.y / 100 - 1)}`,
          },
        },
      },
    },
  }));
}
