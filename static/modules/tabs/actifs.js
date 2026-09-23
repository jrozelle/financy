import { S } from '../state.js';
import { api } from '../api.js';
import { esc, fmt, fmtDate, destroyChart, getColors, chartBorderColor, sortArr, fmtQty, fmtPct,
         wireSortableTable, updateSortIndicators } from '../utils.js';
import { openIsinPopover } from '../isin-popover.js';
import { triggerPricesRefresh } from './tools.js';
import { saveFilters, loadFilters } from '../filter-persist.js';
import { reapplyColumns } from '../column-picker.js';
import { loadReconcile } from './reconcile.js';

let _classChart = null;
let _envelopeChart = null;
let _data = null;
// Tri du tableau : valeur decroissante par defaut. Cle locale plutot que
// declaree dans state.js.
S.sort.actifs = S.sort.actifs || { key: 'market_value', dir: -1 };
let _filter = { type: null, value: null }; // {type: 'asset_class'|'envelope', value: 'ETF'}
const ACTIFS_COLUMNS_STORAGE_KEY = 'financy_columns_actifs';
const ACTIFS_ESTABLISHMENTS_MIGRATION_KEY = 'financy_columns_actifs_establishments_v1';
// Neuf colonnes plutot que douze : a 1300 px, le tableau debordait de sa carte
// et « Fraîcheur » ne se voyait jamais. L'ISIN passe sous le nom, les
// enveloppes sous l'etablissement, l'age du cours sous le cours lui-meme.
const ACTIFS_TABLE_COLUMNS = [
  { key: 'name', label: 'Nom' },
  { key: 'asset_class', label: 'Classe' },
  { key: 'establishments', label: 'Établissement' },
  { key: 'quantity', label: 'Qté', num: true },
  { key: 'avg_cost', label: 'PRU', num: true },
  { key: 'last_price', label: 'Cours', num: true },
  { key: 'market_value', label: 'Valeur', num: true },
  { key: 'pnl', label: '+/-', num: true },
  { key: 'weight_pct', label: 'Poids', num: true },
];

/** Quantite avec autant de decimales qu'elle en porte (huit au plus) : un
 *  bitcoin detenu a 0,0625 s'affichait « 0 » a cote de 4 215 €, et 570,5 parts
 *  d'ETF « 571 ». Moins de decimales permises a mesure que la quantite grandit :
 *  le bruit d'un calcul flottant ne doit pas s'ecrire. */
function fmtQteAdaptive(q) {
  if (q == null) return '—';
  const a = Math.abs(q);
  const max = a >= 1000 ? 2 : a >= 1 ? 4 : 8;
  let dec = 0;
  while (dec < max && Math.abs(Math.round(q * 10 ** dec) / 10 ** dec - q) > 1e-9 * Math.max(1, a)) dec++;
  return fmtQty(q, dec);
}
/** Plus-value d'une ligne, au format de Positions : montant signe, pourcentage
 *  dessous. Une plus-value nulle au centime pres n'est pas une performance
 *  mesuree : un fonds euros sans cours, ou un releve sans prix de revient dont
 *  la saisie a repris la valeur. On le dit plutot qu'afficher « +0 € ». */
function cellulePnl(l) {
  if (l.pnl == null) return '<span class="pv-na">—</span>';
  if (l.pnl === 0) return '<span class="pv-na">PRU = valeur</span>';
  const v = l.pnl;
  const montant = `<span class="${v >= 0 ? 'pv-hausse' : 'pv-baisse'}">${v >= 0 ? '+' : '−'}${fmt(Math.abs(v))}</span>`;
  return montant + (l.pnl_pct != null ? `<span class="pv-pct">${fmtPct(l.pnl_pct, 1, true)}</span>` : '');
}

/** Dernier cours, dans la devise du titre. Le cours d'un titre du Nasdaq est
 *  en dollars : l'ecrire suivi de « € » le faisait passer pour une valeur en
 *  euros. Hors euro, le code de la devise suit le nombre, masque comme lui. */
function celluleCours(l) {
  if (l.last_price == null) return '—';
  const devise = (l.currency || 'EUR').toUpperCase();
  if (devise === 'EUR') return fmt(l.last_price, 2);
  return `${fmtQty(l.last_price, 2)}\u00a0${esc(devise)}`;
}

/** Un pseudo-ISIN (FONDS_EUROS_FGPER2560DC) est un code interne : il
 *  elargissait la colonne de 100 px sans rien apprendre a personne. Il se lit
 *  « fonds euros » ou « non coté » ; le code reste dans la fenetre du titre,
 *  et dans le nom accessible du bouton. */
function boutonIsin(isin) {
  const u = (isin || '').toUpperCase();
  const pseudo = u.startsWith('FONDS_EUROS_') ? 'fonds euros' : u.startsWith('CUSTOM_') ? 'non coté' : null;
  return `<button type="button" class="h-isin-btn${pseudo ? ' h-isin-pseudo' : ''}" data-action="open-popover"
    data-isin="${esc(isin)}"${pseudo ? ` aria-label="${esc(isin)}"` : ''}>${esc(pseudo || isin)}</button>`;
}

function ensureActifsTableScaffold() {
  const thead = document.getElementById('actifs-thead');
  if (!thead) return;
  const current = [...thead.querySelectorAll('th')].map(th => th.dataset.sort).join('|');
  const expected = ACTIFS_TABLE_COLUMNS.map(c => c.key).join('|');
  if (current === expected) return;
  thead.innerHTML = `<tr>${ACTIFS_TABLE_COLUMNS.map(col => `
    <th data-sort="${col.key}"${col.num ? ' class="num"' : ''}>${esc(col.label)}</th>
  `).join('')}</tr>`;
}

function ensureEstablishmentColumnPreference() {
  try {
    if (localStorage.getItem(ACTIFS_ESTABLISHMENTS_MIGRATION_KEY)) return;
    const saved = JSON.parse(localStorage.getItem(ACTIFS_COLUMNS_STORAGE_KEY) || '{}');
    saved.establishments = true;
    localStorage.setItem(ACTIFS_COLUMNS_STORAGE_KEY, JSON.stringify(saved));
    localStorage.setItem(ACTIFS_ESTABLISHMENTS_MIGRATION_KEY, '1');
  } catch {}
}

// Restore tri et filtre chart depuis localStorage au premier load
(function _restoreActifsState() {
  const saved = loadFilters('actifs');
  if (saved.sortCol) S.sort.actifs.key = saved.sortCol;
  if (typeof saved.sortDesc === 'boolean') S.sort.actifs.dir = saved.sortDesc ? -1 : 1;
  if (saved.filter && saved.filter.type && saved.filter.value) {
    _filter = { type: saved.filter.type, value: saved.filter.value };
  }
})();

function _persist() {
  saveFilters('actifs', { sortCol: S.sort.actifs.key, sortDesc: S.sort.actifs.dir === -1, filter: _filter });
}

export async function loadActifs() {
  ensureEstablishmentColumnPreference();
  ensureActifsTableScaffold();
  // Ne pas reinitialiser _filter : il a ete restaure au boot et maintenu
  // volontairement entre visites. Clic sur camembert toggle ou reset.
  // Utiliser le filtre global owner
  const globalOwner = S.syntheseOwner;
  const owner = (globalOwner && globalOwner !== 'Famille') ? globalOwner : '';
  const params = new URLSearchParams();
  const date = S.syntheseDate || S.positionsDate || S.dates?.[0];
  if (date) params.set('date', date);
  if (owner) params.set('owner', owner);
  const qs = params.toString();
  const url = `/api/holdings/consolidated${qs ? `?${qs}` : ''}`;
  try {
    _data = await api('GET', url, null, { silent: true });
  } catch { return; }
  _render();
  // Le rapprochement avec le journal des operations vit au-dessus du tableau :
  // il repond a « ces quantites sont-elles a jour ? », question que les chiffres
  // affiches ne posent jamais d'eux-memes.
  loadReconcile();
}

function _render() {
  if (!_data) return;
  const t = _data.totals;
  const lines = _data.lines || [];

  document.getElementById('actifs-kpi-value').textContent = fmt(t.market_value || 0);
  document.getElementById('actifs-kpi-cost').textContent  = t.cost_basis ? fmt(t.cost_basis) : '—';
  const pnlEl = document.getElementById('actifs-kpi-pnl');
  if (t.pnl != null) {
    pnlEl.textContent = (t.pnl >= 0 ? '+' : '') + fmt(t.pnl) + (t.pnl_pct != null ? ` (${fmtPct(t.pnl_pct, 2)})` : '');
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
  ensureActifsTableScaffold();
  const tbody = document.getElementById('actifs-tbody');
  const cards = document.getElementById('actifs-cards');
  const empty = document.getElementById('actifs-empty');
  if (!lines.length) {
    tbody.innerHTML = '';
    if (cards) cards.innerHTML = '';
    empty.style.display = '';
    updateSortIndicators('actifs-thead', 'actifs');
    return;
  }
  empty.style.display = 'none';
  // Appliquer le filtre graphe si actif
  let filtered = lines;
  if (_filter.type && _filter.value) {
    if (_filter.type === 'asset_class') {
      filtered = lines.filter(l => l.asset_class === _filter.value);
    } else if (_filter.type === 'envelope') {
      filtered = lines.filter(l => (l.envelopes || []).includes(_filter.value));
    }
  }
  const sorted = sortArr([...filtered], S.sort.actifs.key, S.sort.actifs.dir);
  tbody.innerHTML = sorted.map(l => {
    const fresh = _freshnessBadge(l);
    const envs = (l.envelopes || []).join(', ');
    return `<tr>
      <td class="act-nom"><span class="act-nom-lib">${esc(l.name || '—')}</span>
        <span class="act-sous">${boutonIsin(l.isin)}</span></td>
      <td>${esc(l.asset_class || '—')}</td>
      <td class="act-etab">${esc((l.establishments || []).join(', ') || '—')}${
        envs ? `<span class="act-sous">${esc(envs)}</span>` : ''}</td>
      <td class="num">${fmtQteAdaptive(l.quantity)}</td>
      <td class="num">${l.avg_cost != null ? fmt(l.avg_cost, 2) : '—'}</td>
      <td class="num act-cours">${celluleCours(l)}<span class="act-fraicheur">${fresh}</span></td>
      <td class="num">${fmt(l.market_value)}</td>
      <td class="num">${cellulePnl(l)}</td>
      <td class="num">${fmtPct(l.weight_pct)}</td>
    </tr>`;
  }).join('');
  if (cards) {
    cards.innerHTML = sorted.map(l => {
      const fresh = _freshnessBadge(l);
      return `<article class="actif-card">
        <div class="actif-card-main">
          ${boutonIsin(l.isin)}
          <strong>${esc(l.name || '—')}</strong>
          <span>${esc((l.establishments || []).join(', ') || '—')} · ${esc((l.envelopes || []).join(', ') || '—')} · ${esc(l.asset_class || '—')}</span>
        </div>
        <dl class="actif-card-metrics">
          <div><dt>Valeur</dt><dd>${fmt(l.market_value)}</dd></div>
          <div><dt>PRU</dt><dd>${l.avg_cost != null ? fmt(l.avg_cost, 2) : '—'}</dd></div>
          <div><dt>Qté</dt><dd>${fmtQteAdaptive(l.quantity)}</dd></div>
          <div><dt>+/-</dt><dd>${cellulePnl(l)}</dd></div>
          <div><dt>Poids</dt><dd>${fmtPct(l.weight_pct)}</dd></div>
          <div><dt>Cours</dt><dd>${celluleCours(l)}</dd></div>
        </dl>
        <div class="actif-card-freshness">${fresh}</div>
      </article>`;
    }).join('');
  }
  updateSortIndicators('actifs-thead', 'actifs');
  reapplyColumns('actifs', 'actifs-thead');
}

function _freshnessBadge(l) {
  if (!l.is_priceable) {
    return '<span class="h-badge h-badge-muted">non coté</span>';
  }
  if (!l.ticker && !l.last_price_date) {
    return '<span class="h-badge h-badge-expired">sans ticker</span>';
  }
  if (!l.last_price_date) return '<span class="h-badge h-badge-expired">jamais rafraîchi</span>';
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
  // La date du cours s'affiche sous l'age : c'est elle qu'on vient chercher.
  return `<span class="h-badge ${cls}">${lbl}</span><span class="h-badge-date">cours du ${fmtDate(l.last_price_date)}</span>`;
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

function _pieOptions(filterType, labels, breakdown) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    onClick: (_, elements) => {
      if (!elements.length) {
        // Clic hors slice → reset filtre
        _filter = { type: null, value: null };
      } else {
        const label = labels[elements[0].index];
        // Toggle : re-clic sur le meme → reset
        if (_filter.type === filterType && _filter.value === label) {
          _filter = { type: null, value: null };
        } else {
          _filter = { type: filterType, value: label };
        }
      }
      _persist();
      if (_data) _renderTable(_data.lines);
    },
    plugins: {
      legend: {
        position: 'right',
        labels: { boxWidth: 12, font: { size: 11 } },
        onClick: (e, item, legend) => {
          const label = labels[item.index];
          if (_filter.type === filterType && _filter.value === label) {
            _filter = { type: null, value: null };
          } else {
            _filter = { type: filterType, value: label };
          }
          _persist();
          if (_data) _renderTable(_data.lines);
        },
      },
      tooltip: {
        callbacks: {
          // La repartition du graphe survole : l'enveloppe lisait jusqu'ici le
          // poids de la classe d'actifs de meme rang.
          label: ctx => ` ${ctx.label} : ${fmt(ctx.parsed)} (${fmtPct(breakdown[ctx.dataIndex]?.weight_pct)})`,
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
  const labels = breakdown.map(b => b.label);
  _classChart = new Chart(canvas, {
    type: 'doughnut',
    data: _pieDataset(breakdown, getColors()),
    options: _pieOptions('asset_class', labels, breakdown),
  });
}

function _renderEnvelopeChart(breakdown) {
  const canvas = document.getElementById('actifs-chart-envelope');
  if (!canvas) return;
  _envelopeChart = destroyChart(_envelopeChart);
  if (!breakdown.length) return;
  const labels = breakdown.map(b => b.label);
  _envelopeChart = new Chart(canvas, {
    type: 'doughnut',
    data: _pieDataset(breakdown, getColors().slice().reverse()),
    options: _pieOptions('envelope', labels, breakdown),
  });
}

// ─── Wiring ─────────────────────────────────────────────────────────────────

export function wireActifsEvents() {
  ensureEstablishmentColumnPreference();
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
  document.getElementById('actifs-cards')?.addEventListener('click', e => {
    const btn = e.target.closest('[data-action="open-popover"]');
    if (btn) openIsinPopover(btn.dataset.isin);
  });

  // Clic et clavier (Entree, Espace), aria-sort : le helper commun.
  wireSortableTable('actifs-thead', 'actifs', () => {
    _persist();
    if (_data) _renderTable(_data.lines);
  });
}
