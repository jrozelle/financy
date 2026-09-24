import { S } from './state.js';
import { fmt, fmtDate, esc, liqText, getColors, destroyChart, fmtAxis, fmtPct,
         tsJour, echelleTemps, titreDate, sortArr, wireSortableTable, updateSortIndicators } from './utils.js';
import { api } from './api.js';
import { closeModal } from './dialogs.js';

// Tri du tableau d'historique. Cle locale plutot que declaree dans state.js.
S.sort.dd_history = S.sort.dd_history || { key: null, dir: 1 };

/** Icone « evolution » des lignes cliquables : une courbe montante, au trait
 *  comme les autres icones de l'application. Le nom accessible est porte par
 *  le texte masque qui l'accompagne. */
const ICONE_EVOLUTION = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
  <path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/></svg><span class="sr-only">Voir l'évolution</span>`;

/** Couleur de grille des graphes, lue sur le theme courant. */
const couleurGrille = () =>
  getComputedStyle(document.documentElement).getPropertyValue('--border').trim() || 'rgba(128,128,128,.2)';

// Element qui avait le focus a l'ouverture du panneau : il le recupere a la
// fermeture, sans quoi le clavier repart du haut de la page.
let _focusAvant = null;

/** Ouvre le panneau (ou le laisse ouvert) et place le focus sur « Fermer ». */
function _ouvrirPanneau() {
  const panel = document.getElementById('drilldown-panel');
  if (!panel) return;
  if (panel.classList.contains('hidden')) {
    _focusAvant = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panel.classList.remove('hidden');
  }
  _updateBackBtn();
  document.getElementById('dd-close')?.focus();
}

/** Montant d'en-tete du panneau. Un net negatif en vert d'accent se lisait
 *  comme un gain : la couleur suit le signe. */
export function montantPanneau(texte, valeur) {
  const el = document.getElementById('dd-amount');
  el.textContent = texte;
  el.classList.toggle('neg', valeur < 0);
}

let _historyChart = null;
const _navStack = [];
// Lignes du tableau d'historique affiche (date, brut, net, variation).
let _hist = null;

// ─── Navigation stack ─────────────────────────────────────────────────────

function _snapshot() {
  return {
    subtitle: document.getElementById('dd-subtitle').textContent,
    title:    document.getElementById('dd-title').textContent,
    amount:   document.getElementById('dd-amount').textContent,
    negatif:  document.getElementById('dd-amount').classList.contains('neg'),
    body:     document.getElementById('dd-body').innerHTML,
    hist:     _hist,
  };
}

function _restore(snap) {
  _historyChart = destroyChart(_historyChart);
  document.getElementById('dd-subtitle').textContent = snap.subtitle;
  document.getElementById('dd-title').textContent    = snap.title;
  montantPanneau(snap.amount, snap.negatif ? -1 : 1);
  document.getElementById('dd-body').innerHTML        = snap.body;
  _hist = snap.hist;
  // Le thead restaure a perdu ses ecouteurs : on le recable.
  if (_hist && document.getElementById('dd-history-thead')) {
    wireSortableTable('dd-history-thead', 'dd_history', _renderHistoryRows);
  }
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


export function closeDrilldown() {
  _navStack.length = 0;
  _historyChart = destroyChart(_historyChart);
  const panel = document.getElementById('drilldown-panel');
  const etaitOuvert = panel && !panel.classList.contains('hidden');
  panel?.classList.add('hidden');
  _updateBackBtn();
  if (etaitOuvert && _focusAvant?.isConnected) _focusAvant.focus();
  _focusAvant = null;
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
  montantPanneau(fmt(total), total);

  document.getElementById('dd-body').innerHTML = `
    <div class="dd-section">
      <div class="dd-section-title">${sorted.length} position(s)</div>
      ${sorted.map(p => {
        const v = valOf(p);
        const pct = total > 0 ? (v / total) * 100 : 0;
        const bar = total > 0
          ? `<div class="dd-bar-wrap"><div class="dd-bar" style="width:${Math.min(100, pct).toFixed(1)}%"></div></div>`
          : '';
        const pctLabel = total > 0 ? fmtPct(pct) : '';
        return `<div class="dd-row dd-row-clickable" data-pos-id="${p.id}"
                     data-category="${esc(p.category)}" role="button" tabindex="0">
          <div class="dd-row-left">
            <div class="dd-row-name">${esc(p.label || p.envelope || p.category)}</div>
            <div class="dd-row-sub">${esc([showOwner ? p.owner : null, p.category, p.establishment, p.entity, liqText(p.liquidity)].filter(Boolean).join(' · '))}</div>
            ${bar}
          </div>
          <div class="dd-row-right">
            <div class="dd-row-val ${neg || v < 0 ? 'neg' : ''}">${fmt(v)}</div>
            ${pctLabel ? `<div class="dd-row-pct">${pctLabel}</div>` : ''}
            <div class="dd-row-action">${ICONE_EVOLUTION}</div>
          </div>
        </div>`;
      }).join('')}
    </div>`;

  _ouvrirPanneau();
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
    montantPanneau(fmt(total), total);

    // Une position sans liquidite, ou d'une liquidite absente du referentiel,
    // compte dans le total : elle figure donc dans une derniere section plutot
    // que de disparaitre de la liste.
    const ordre = S.config.liquidity_order || [];
    const autres = Object.keys(byLiq).filter(k => !ordre.includes(k)).flatMap(k => byLiq[k]);
    const groupes = ordre.filter(l => byLiq[l]?.length).map(l => [l, byLiq[l]]);
    if (autres.length) groupes.push(['Autre / non classé', autres]);
    const sectionsHtml = groupes
      .map(([l, liste]) => {
        const sub = liste.sort((a, b) => (b.mobilizable_value || 0) - (a.mobilizable_value || 0));
        const liqTotal = sub.reduce((s, p) => s + (p.mobilizable_value || 0), 0);
        return `<div class="dd-section">
          <div class="dd-section-title">${esc(l)} — ${fmt(liqTotal)}</div>
          ${sub.map(p => {
            const v = p.mobilizable_value || 0;
            const pct = total > 0 ? (v / total) * 100 : 0;
            return `<div class="dd-row dd-row-clickable" data-pos-id="${p.id}" data-category="${esc(p.category)}"
                         role="button" tabindex="0">
              <div class="dd-row-left">
                <div class="dd-row-name">${esc(p.label || p.envelope || p.category)}</div>
                <div class="dd-row-sub">${esc([p.owner, p.category, p.establishment,
                  l === 'Autre / non classé' ? (p.liquidity ? liqText(p.liquidity) : 'liquidité non renseignée') : null,
                ].filter(Boolean).join(' · '))}</div>
                <div class="dd-bar-wrap"><div class="dd-bar" style="width:${Math.min(100, pct).toFixed(1)}%"></div></div>
              </div>
              <div class="dd-row-right">
                <div class="dd-row-val">${fmt(v)}</div>
                ${total > 0 ? `<div class="dd-row-pct">${fmtPct(pct)}</div>` : ''}
                <div class="dd-row-action">${ICONE_EVOLUTION}</div>
              </div>
            </div>`;
          }).join('')}
        </div>`;
      }).join('');

    document.getElementById('dd-body').innerHTML = sectionsHtml;
    _ouvrirPanneau();
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
    montantPanneau('', 0);
    _hist = null;
    document.getElementById('dd-body').innerHTML =
      '<p style="color:var(--text-muted);padding:.75rem">Aucune donnée historique.</p>';
    _ouvrirPanneau();
    return;
  }

  const last = history[history.length - 1];
  montantPanneau(fmt(last.net), last.net);

  // Variation calculee dans l'ordre chronologique, avant tout tri d'affichage.
  _hist = history.map((h, i) => ({
    date: h.date, gross: h.gross, net: h.net,
    delta: i > 0 ? h.net - history[i - 1].net : null,
  }));

  document.getElementById('dd-body').innerHTML = `
    ${history.length >= 2 ? '<div style="position:relative;height:200px;margin-bottom:1rem"><canvas id="dd-history-chart"></canvas></div>' : ''}
    <div class="table-scroll" tabindex="0" role="region" aria-label="Historique">
      <table class="data-table">
        <thead id="dd-history-thead"><tr><th data-sort="date">Date</th><th class="num" data-sort="gross">Brut</th>
          <th class="num" data-sort="net">Net</th><th class="num" data-sort="delta">Variation</th></tr></thead>
        <tbody id="dd-history-tbody"></tbody>
      </table>
    </div>`;
  wireSortableTable('dd-history-thead', 'dd_history', _renderHistoryRows);
  _renderHistoryRows();

  if (history.length >= 2) {
    _historyChart = destroyChart(_historyChart);
    const canvas = document.getElementById('dd-history-chart');
    const colors = getColors();
    const border = couleurGrille();
    _historyChart = new Chart(canvas, {
      type: 'line',
      data: {
        datasets: [{
          label: 'Net',
          data: history.map(h => ({ x: tsJour(h.date), y: h.net })),
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
        plugins: { legend: { display: false },
                   tooltip: { callbacks: { title: titreDate, label: ctx => ` ${fmt(ctx.parsed.y)}` } } },
        scales: {
          y: { ticks: { callback: fmtAxis, font: { size: 11 } }, grid: { color: border } },
          x: echelleTemps(history.map(h => h.date)),
        },
      },
    });
  }

  _ouvrirPanneau();
}

/** Corps du tableau d'historique, selon le tri choisi. Sans tri, le plus
 *  recent en tete. */
function _renderHistoryRows() {
  const tbody = document.getElementById('dd-history-tbody');
  if (!tbody || !_hist) return;
  const { key, dir } = S.sort.dd_history;
  const lignes = key ? sortArr(_hist, key, dir) : [..._hist].reverse();
  tbody.innerHTML = lignes.map(h => {
    const deltaStr = h.delta != null
      ? `<span style="color:${h.delta >= 0 ? 'var(--success)' : 'var(--danger)'};font-size:11px">${h.delta >= 0 ? '+' : ''}${fmt(h.delta)}</span>`
      : '';
    return `<tr>
      <td>${fmtDate(h.date)}</td>
      <td class="num">${fmt(h.gross)}</td>
      <td class="num">${fmt(h.net)}</td>
      <td class="num">${deltaStr}</td>
    </tr>`;
  }).join('');
  updateSortIndicators('dd-history-thead', 'dd_history');
}

// ─── Events ───────────────────────────────────────────────────────────────

export function wireDrilldownEvents() {
  document.getElementById('dd-close').addEventListener('click', closeDrilldown);
  document.getElementById('dd-back').addEventListener('click', goBack);
  document.getElementById('drilldown-overlay').addEventListener('click', closeDrilldown);

  // Delegated click on dd-body — survives innerHTML restores from nav stack
  const ouvrirLigne = row => {
    const posId = row.dataset.posId;
    const category = row.dataset.category;
    if (posId) {
      drilldownHistory({
        subtitle: 'Évolution position',
        title: category || '',
        filters: { position_id: posId },
      });
    }
  };
  document.getElementById('dd-body').addEventListener('click', e => {
    const row = e.target.closest('.dd-row-clickable');
    if (row) ouvrirLigne(row);
  });
  // Les lignes sont des boutons (role="button") : Entree et Espace les ouvrent.
  document.getElementById('dd-body').addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const row = e.target.closest('.dd-row-clickable');
    if (!row) return;
    e.preventDefault();
    ouvrirLigne(row);
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

  // Cartes des chiffres de tete : delegation sur la grille, qui reste en
  // place quand l'ecran (Svelte) redessine ses cartes.

  const _filterByOwner = positions => {
    const owner = S.syntheseOwner;
    if (!owner || owner === 'Famille') return positions;
    return positions.filter(p => p.owner === owner);
  };
  const _ownerLabel = () => {
    const owner = S.syntheseOwner;
    return (!owner || owner === 'Famille') ? 'Tous les titulaires' : owner;
  };
  const _showOwner = () => !S.syntheseOwner || S.syntheseOwner === 'Famille';

  const ouvrir = {
    'kpi-hero': () => api('GET', `/api/positions?date=${S.syntheseDate}`).then(pos =>
      drilldownPositions(_filterByOwner(pos), 'Patrimoine net', _ownerLabel(), { showOwner: _showOwner() })),
    'kpi-gross': () => api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions =>
      drilldownPositions(_filterByOwner(positions), 'Actifs bruts', _ownerLabel(), { showOwner: _showOwner(), valueField: 'gross_attributed' })),
    'kpi-debt': () => api('GET', `/api/positions?date=${S.syntheseDate}`).then(positions => {
      const withDebt = _filterByOwner(positions).filter(p => p.debt_attributed > 0);
      drilldownPositions(withDebt, 'Dettes', _ownerLabel(), { showOwner: _showOwner(), valueField: 'debt_attributed', neg: true });
    }),
    'kpi-mobilizable': () => drilldownMobilizable(),
  };
  document.querySelector('.kpi-grid[data-carte="chiffres"]')?.addEventListener('click', e => {
    const carte = e.target.closest('.kpi-card');
    if (!carte || !S.synthese?.date) return;
    // Les commandes de la grille de widgets (poignee, largeur) ne sont pas un clic sur le chiffre.
    if (e.target.closest('.w-commandes, .w-bord')) return;
    const cle = Object.keys(ouvrir).find(c => carte.classList.contains(c));
    if (cle) ouvrir[cle]();
  });
}
