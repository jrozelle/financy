import { S } from '../state.js';
import { fmt, fmtDate, esc, liqBadge, sortArr, updateSortIndicators, today, wireTreeAccordion, treeToggleRow } from '../utils.js';
import { api, refreshEntitySelect } from '../api.js';
import { confirmDialog, promptDialog, toast, closeModal } from '../dialogs.js';
import { loadSynthese, loadHistorique } from './synthese.js';
import { openHoldingsModal } from './holdings.js';
import { refreshDates } from '../main.js';
import { saveFilters, loadFilters, clearFilterKey, applyIfValid } from '../filter-persist.js';

// ─── Persistance etat expand/collapse de l'arborescence positions ──────────
// On persiste uniquement les rows COLLAPSED (par defaut tout est deplie) pour
// que de nouveaux noeuds soient visibles par defaut.

const TREE_STATE_KEY = 'financy_positions_tree_collapsed';

function _loadCollapsedKeys() {
  try { return new Set(JSON.parse(localStorage.getItem(TREE_STATE_KEY) || '[]')); }
  catch { return new Set(); }
}

function _saveCollapsedKeys(container) {
  const set = new Set();
  container.querySelectorAll('.tree-row[data-key]').forEach(row => {
    const children = row.nextElementSibling;
    if (children && children.classList.contains('tree-children')
        && children.style.display === 'none') {
      set.add(row.dataset.key);
    }
  });
  try { localStorage.setItem(TREE_STATE_KEY, JSON.stringify([...set])); } catch {}
}

function _restoreTreeState(container) {
  const collapsed = _loadCollapsedKeys();
  if (!collapsed.size) return;
  container.querySelectorAll('.tree-row[data-key]').forEach(row => {
    if (collapsed.has(row.dataset.key)) {
      const children = row.nextElementSibling;
      if (children && children.classList.contains('tree-children')
          && children.style.display !== 'none') {
        treeToggleRow(row, false);
      }
    }
  });
}

function _bindTreePersist(container) {
  if (container.dataset.persistBound) return;
  container.dataset.persistBound = '1';
  // Bubbling : s'execute apres les handlers per-row de wireTreeAccordion.
  container.addEventListener('click', ev => {
    if (ev.target.closest('.tree-actions')) return;
    const row = ev.target.closest('.tree-row[data-key]');
    if (!row) return;
    // Delai 0 pour laisser le toggle se propager
    setTimeout(() => _saveCollapsedKeys(container), 0);
  });
}

export function persistPositionsTreeState() {
  const container = document.getElementById('positions-tree-body');
  if (container) _saveCollapsedKeys(container);
}


let _snapshotEnsured = false;
async function ensureTodaySnapshot() {
  if (_snapshotEnsured) return;
  try {
    await api('POST', '/api/auto-snapshot', {}, { silent: true });
    await refreshDates();
    _snapshotEnsured = true;
  } catch {}
}

export async function loadPositions() {
  if (!S.positionsDate && S.dates.length) S.positionsDate = S.dates[0];
  if (!S.positionsDate) {
    renderPositionsEmpty('Aucune donnée. Importez votre fichier Excel ou ajoutez une position.');
    return;
  }
  S.positions = await api('GET', `/api/positions?date=${S.positionsDate}`);
  populateFilters();
  // Sync filtre local avec le selecteur global
  const globalOwner = S.syntheseOwner;
  if (globalOwner && globalOwner !== 'Famille') {
    document.getElementById('filter-owner').value = globalOwner;
  }
  renderPositions();
}

function populateFilters() {
  const owners    = [...new Set(S.positions.map(p => p.owner))].sort();
  const envelopes = [...new Set(S.positions.map(p => p.envelope).filter(Boolean))].sort();
  const estabs    = [...new Set(S.positions.map(p => p.establishment).filter(Boolean))].sort();

  // Priorite : valeurs courantes DOM > filtres persistes en localStorage
  const saved = loadFilters('positions');
  const cur = {
    owner:         document.getElementById('filter-owner').value         || saved.owner         || '',
    envelope:      document.getElementById('filter-envelope').value      || saved.envelope      || '',
    establishment: document.getElementById('filter-establishment').value || saved.establishment || '',
  };

  fillFilter('filter-owner',         'Toutes les personnes',       owners);
  fillFilter('filter-envelope',      'Toutes les enveloppes',      envelopes);
  fillFilter('filter-establishment', 'Tous les établissements',    estabs);

  applyIfValid('filter-owner',         cur.owner);
  applyIfValid('filter-envelope',      cur.envelope);
  applyIfValid('filter-establishment', cur.establishment);
}

export function persistPositionFilters() {
  saveFilters('positions', {
    owner:         document.getElementById('filter-owner')?.value         || '',
    envelope:      document.getElementById('filter-envelope')?.value      || '',
    establishment: document.getElementById('filter-establishment')?.value || '',
  });
}

function fillFilter(id, placeholder, options) {
  document.getElementById(id).innerHTML =
    `<option value="">${placeholder}</option>` +
    options.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('');
}

export function clearFilters() {
  document.getElementById('filter-owner').value         = '';
  document.getElementById('filter-envelope').value      = '';
  document.getElementById('filter-establishment').value = '';
  clearFilterKey('positions');
  renderPositions();
}

function filteredPositions() {
  const owner  = document.getElementById('filter-owner').value;
  const env    = document.getElementById('filter-envelope').value;
  const estab  = document.getElementById('filter-establishment').value;
  return S.positions.filter(p =>
    (!owner  || p.owner         === owner) &&
    (!env    || p.envelope      === env)   &&
    (!estab  || p.establishment === estab)
  );
}

function renderPositionsEmpty(msg) {
  document.getElementById('positions-tbody').innerHTML =
    `<tr class="empty-row"><td colspan="10">${esc(msg)}</td></tr>`;
  document.getElementById('positions-tfoot').innerHTML = '';
}

export function renderPosViewToggle() {
  const existing = document.getElementById('pos-view-toggle');
  if (existing) {
    existing.querySelectorAll('.view-toggle-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.view === S.positionsView);
    });
    return;
  }
  const toggle = document.createElement('div');
  toggle.id = 'pos-view-toggle';
  toggle.className = 'analyse-view-toggle';
  toggle.style.marginLeft = '.5rem';
  toggle.innerHTML = `
    <button class="view-toggle-btn ${S.positionsView === 'table' ? 'active' : ''}" data-view="table">&#9776; Tableau</button>
    <button class="view-toggle-btn ${S.positionsView === 'tree'  ? 'active' : ''}" data-view="tree">&#9638; Arborescence</button>`;
  toggle.addEventListener('click', e => {
    const btn = e.target.closest('.view-toggle-btn');
    if (!btn) return;
    S.positionsView = btn.dataset.view;
    localStorage.setItem('financy_positionsView', S.positionsView);
    renderPositions();
  });
  const headerActions = document.querySelector('#tab-positions .header-actions');
  if (headerActions) headerActions.insertBefore(toggle, headerActions.firstChild);
}

export function startInlineEdit(span) {
  if (span.querySelector('input')) return;
  const posId  = parseInt(span.dataset.id);
  const curVal = parseFloat(span.dataset.val) || 0;
  const pos    = S.positions.find(p => p.id === posId);
  if (!pos) return;

  const input = document.createElement('input');
  input.type  = 'number';
  input.step  = '0.01';
  input.min   = '0';
  input.value = curVal;
  input.className = 'tree-inline-input';
  span.innerHTML = '';
  span.appendChild(input);
  input.focus();
  input.select();

  const commit = async () => {
    const newVal = parseFloat(input.value);
    if (isNaN(newVal) || newVal === curVal) {
      await loadPositions(); return;
    }
    try {
      await api('PUT', `/api/positions/${posId}`, {
        ...pos,
        value: newVal,
        debt:  pos.debt || 0,
      });
      await loadPositions();
    } catch (err) {
      toast(`Erreur : ${err.message}`, 'error');
      await loadPositions();
    }
  };

  input.addEventListener('blur',  commit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { input.removeEventListener('blur', commit); loadPositions(); }
  });
}

function _posLeafHtml(p, { showHoldings = true, mergedLabel = null } = {}) {
  const pctBadge = (p.ownership_pct ?? 1) < 0.999
    ? `<span class="tree-badge-pct badge badge-j27">${Math.round((p.ownership_pct ?? 1) * 100)}%</span>` : '';
  const mobMark = p.mobilizable_pct_override != null
    ? `<span class="tree-badge-warn" title="Mobilisabilite surchargee : ${Math.round(p.mobilizable_pct_override * 100)} %">&#9888;</span>` : '';
  const notesMark = p.notes
    ? `<span class="tree-badge-notes" title="${esc(p.notes)}">&#128203;</span>` : '';
  const hasEntity = !!p.entity;
  const inlineVal = hasEntity
    ? `<span class="tree-amount ${p.net_attributed < 0 ? 'neg' : ''}">${fmt(p.net_attributed)}</span>`
    : `<span class="tree-inline-amount ${p.net_attributed < 0 ? 'neg' : ''}" title="Cliquer pour editer" data-id="${p.id}" data-field="value" data-val="${p.value || 0}">${fmt(p.net_attributed)}</span>`;
  return `
    <div class="tree-row tree-pos-leaf" data-pos-id="${p.id}">
      <span class="tree-dot"></span>
      <span class="tree-label" title="${esc(mergedLabel || p.label || p.category)}">${esc(mergedLabel || p.label || p.category)}${pctBadge}${notesMark}${mobMark}</span>
      <span class="tree-badges">${liqBadge(p.liquidity)}</span>
      ${inlineVal}
      <span class="tree-actions">
        ${showHoldings ? `<button class="btn-icon" data-action="manage-holdings" data-id="${p.id}" title="Lignes">&#9776;</button>` : ''}
        <button class="btn-icon edit" data-id="${p.id}" data-action="edit-pos" title="Editer">&#9998;</button>
        <button class="btn-icon del" data-id="${p.id}" data-action="del-pos" title="Supprimer">&#10005;</button>
      </span>
    </div>`;
}

function renderPositionsTree(allPositions) {
  const container = document.getElementById('positions-tree-body');
  if (!allPositions.length) {
    container.innerHTML = '<p class="text-muted" style="padding:.75rem">Aucune position pour ce snapshot.</p>';
    return;
  }

  const etablKey = p => p.entity ? `Entité : ${p.entity}` : (p.establishment || 'Biens personnels');

  let html = '';
  for (const owner of S.config.owners) {
    const ops = allPositions.filter(p => p.owner === owner);
    if (!ops.length) continue;
    const ownerNet   = ops.reduce((s, p) => s + (p.net_attributed || 0), 0);

    const byEtabl = {};
    for (const p of ops) {
      const k = etablKey(p);
      if (!byEtabl[k]) byEtabl[k] = [];
      byEtabl[k].push(p);
    }

    const etablHtml = Object.entries(byEtabl)
      .sort((a, b) => b[1].reduce((s, p) => s + (p.net_attributed||0), 0) - a[1].reduce((s, p) => s + (p.net_attributed||0), 0))
      .map(([etabl, ePoses]) => {
        const etablNet   = ePoses.reduce((s, p) => s + (p.net_attributed || 0), 0);
        const isEntity   = etabl.startsWith('Entité : ');
        const isPersonal = etabl === 'Biens personnels';
        const etablIcon  = isEntity ? '🏢' : isPersonal ? '' : '🏦';
        const etablEntityName = isEntity ? etabl.replace(/^Entité : /, '') : '';
        const etablRealName   = isEntity ? '' : etabl;

        const byEnv = {};
        for (const p of ePoses) {
          const k = p.envelope || '(Sans enveloppe)';
          if (!byEnv[k]) byEnv[k] = [];
          byEnv[k].push(p);
        }

        const envHtml = Object.entries(byEnv)
          .sort((a, b) => b[1].reduce((s, p) => s + (p.net_attributed||0), 0) - a[1].reduce((s, p) => s + (p.net_attributed||0), 0))
          .map(([env, envPoses]) => {
            // Pas d'enveloppe (biens personnels) : afficher les positions directement
            if (env === '(Sans enveloppe)') {
              return [...envPoses]
                .sort((a, b) => (b.net_attributed||0) - (a.net_attributed||0))
                .map(p => _posLeafHtml(p, { showHoldings: false }))
                .join('');
            }
            const envNet   = envPoses.reduce((s, p) => s + (p.net_attributed || 0), 0);
            const envDebt  = envPoses.reduce((s, p) => s + (p.debt_attributed || 0), 0);
            const envDebtStr = envDebt > 0 ? `<span class="tree-debt-label">dette ${fmt(envDebt)}</span>` : '';

            // Fusion : si une seule position sous l'enveloppe, merge en une ligne env
            if (envPoses.length === 1) {
              const p = envPoses[0];
              const label = (p.label || p.category) !== env
                ? `${env} — ${p.label || p.category}` : env;
              const hasEntity = !!p.entity;
              const inlineVal = hasEntity
                ? `<span class="tree-amount ${p.net_attributed < 0 ? 'neg' : ''}">${fmt(p.net_attributed)}</span>`
                : `<span class="tree-inline-amount ${p.net_attributed < 0 ? 'neg' : ''}" title="Cliquer pour editer" data-id="${p.id}" data-field="value" data-val="${p.value || 0}">${fmt(p.net_attributed)}</span>`;
              return `
                <div class="tree-row tree-env tree-env-merged" data-pos-id="${p.id}" data-key="penv-${esc(owner)}-${esc(etabl)}-${esc(env)}">
                  <span class="tree-dot"></span>
                  <span class="tree-label" title="${esc(label)}">${esc(label)}${envDebtStr}</span>
                  <span class="tree-badges">${liqBadge(p.liquidity)}</span>
                  ${inlineVal}
                  <span class="tree-actions">
                    <button class="btn-icon" data-action="manage-holdings" data-id="${p.id}" title="Lignes">&#9776;</button>
                    <button class="btn-icon edit" data-id="${p.id}" data-action="edit-pos" title="Editer">&#9998;</button>
                  </span>
                </div>`;
            }

            const catHtml = [...envPoses]
              .sort((a, b) => (b.net_attributed||0) - (a.net_attributed||0))
              .map(p => _posLeafHtml(p))
              .join('');

            const envEntity  = isEntity ? etabl.replace(/^Entité : /, '') : '';
            const envEtabl   = isEntity ? '' : etabl;
            return `
              <div class="tree-row tree-env" data-key="penv-${esc(owner)}-${esc(etabl)}-${esc(env)}">
                <span class="tree-toggle">▾</span>
                <span class="tree-label">${esc(env)}${envDebtStr}</span>
                <span class="tree-amount ${envNet < 0 ? 'neg' : ''}">${fmt(envNet)}</span>
                <span class="tree-actions">
                  <button class="btn-icon" data-action="history-env"
                    data-owner="${esc(owner)}" data-envelope="${esc(env)}"
                    ${isEntity ? `data-entity="${esc(etablEntityName)}"` : `data-establishment="${esc(etablRealName)}"`}
                    title="Évolution dans le temps">&#128200;</button>
                  <button class="btn-icon add" data-action="add-pos-ctx"
                    data-owner="${esc(owner)}"
                    data-establishment="${esc(envEtabl)}"
                    data-envelope="${esc(env)}"
                    data-entity="${esc(envEntity)}"
                    title="Ajouter une position">+</button>
                </span>
              </div>
              <div class="tree-children">${catHtml}</div>`;
          }).join('');

        const etablDebt    = ePoses.reduce((s, p) => s + (p.debt_attributed || 0), 0);
        const etablDebtStr = etablDebt > 0 ? `<span class="tree-debt-label">dette ${fmt(etablDebt)}</span>` : '';
        return `
          <div class="tree-row tree-etabl" data-key="petabl-${esc(owner)}-${esc(etabl)}">
            <span class="tree-toggle">▾</span>
            <span class="tree-icon">${etablIcon}</span>
            <span class="tree-label">${esc(etabl)}${etablDebtStr}</span>
            <span class="tree-amount ${etablNet < 0 ? 'neg' : ''}">${fmt(etablNet)}</span>
            <span class="tree-actions">
              <button class="btn-icon" data-action="history-etabl"
                data-owner="${esc(owner)}"
                ${isEntity ? `data-entity="${esc(etablEntityName)}"` : `data-establishment="${esc(etablRealName)}"`}
                title="Évolution dans le temps">📈</button>
              <button class="btn-icon add" data-action="add-pos-ctx"
                data-owner="${esc(owner)}"
                data-establishment="${esc(etablRealName)}"
                data-envelope=""
                data-entity="${esc(etablEntityName)}"
                title="Ajouter une position dans cet établissement">+</button>
            </span>
          </div>
          <div class="tree-children">${envHtml}</div>`;
      }).join('');

    html += `
      <div class="tree-owner-section">
        <div class="tree-row tree-owner" data-key="powner-${esc(owner)}">
          <span class="tree-toggle">▾</span>
          <span class="tree-label">${esc(owner)}</span>
          <span class="tree-amount">${fmt(ownerNet)}</span>
          <span class="tree-actions">
            <button class="btn-icon add" data-action="add-pos-ctx"
              data-owner="${esc(owner)}"
              data-establishment="" data-envelope="" data-entity=""
              title="Ajouter une position pour ${esc(owner)}">+</button>
          </span>
        </div>
        <div class="tree-children">${etablHtml}</div>
      </div>`;
  }

  container.innerHTML = html;
  wireTreeAccordion(container);
  _restoreTreeState(container);
  _bindTreePersist(container);
}

export function renderPositions() {
  const isTree = S.positionsView === 'tree';
  document.getElementById('positions-table-wrap').style.display = isTree ? 'none' : '';
  document.getElementById('positions-tree-wrap').style.display  = isTree ? '' : 'none';
  document.getElementById('positions-filters').style.display    = isTree ? 'none' : '';
  renderPosViewToggle();

  if (isTree) {
    renderPositionsTree(filteredPositions());
    return;
  }

  const positions = sortArr(filteredPositions(), S.sort.positions.key, S.sort.positions.dir);
  updateSortIndicators('positions-thead', 'positions');
  if (!positions.length) {
    renderPositionsEmpty(S.positions.length ? 'Aucune position pour ce filtre.' : 'Aucune position pour ce snapshot.');
    return;
  }

  document.getElementById('positions-tbody').innerHTML = positions.map(p => {
    const ownPct  = p.ownership_pct ?? 1;
    const debtPct = p.debt_pct ?? 1;
    const pctBadge = ownPct < 0.999
      ? `<span class="badge badge-j27" style="margin-left:4px;font-size:10px;vertical-align:middle">${Math.round(ownPct*100)}%</span>`
      : '';
    const debtBadge = p.debt_attributed > 0 && debtPct < 0.999
      ? `<span class="badge badge-30" style="margin-left:4px;font-size:10px;vertical-align:middle">${Math.round(debtPct*100)}%</span>`
      : '';
    const entitySub = p.entity
      ? `<div style="font-size:11px;color:var(--text-muted);margin-top:1px">↳ ${esc(p.entity)}</div>` : '';
    const notesMark = p.notes
      ? `<span title="${esc(p.notes)}" style="color:var(--text-muted);font-size:11px;margin-left:4px;cursor:default">📋</span>` : '';
    const holdingsBadge = p.holdings_count
      ? `<span class="badge badge-j27" style="margin-left:4px;font-size:10px;vertical-align:middle" title="${p.holdings_count} ligne(s)">${p.holdings_count}L</span>`
      : '';
    return `<tr>
      <td><strong>${esc(p.owner)}</strong></td>
      <td>${esc(p.label || p.category)}${notesMark}${holdingsBadge}</td>
      <td>${esc(p.envelope || '—')}</td>
      <td>${esc(p.establishment || '—')}${entitySub}</td>
      <td class="num">${fmt(p.gross_attributed)}${pctBadge}</td>
      <td class="num ${p.debt_attributed > 0 ? 'neg' : ''}">${p.debt_attributed > 0 ? fmt(p.debt_attributed) : '—'}${debtBadge}</td>
      <td class="num ${p.net_attributed < 0 ? 'neg' : ''}">${fmt(p.net_attributed)}</td>
      <td>${liqBadge(p.liquidity)}</td>
      <td class="num">${fmt(p.mobilizable_value)}${p.mobilizable_pct_override != null ? ` <span title="Mobilisabilité surchargée : ${Math.round(p.mobilizable_pct_override*100)} %" style="color:var(--warning);font-size:11px">⚠</span>` : ''}</td>
      <td style="white-space:nowrap">
        <button class="btn-icon" data-id="${p.id}" data-action="manage-holdings" title="Gérer les lignes">Lignes</button>
        <button class="btn-icon edit" data-id="${p.id}" data-action="edit-pos">Éditer</button>
        <button class="btn-icon del"  data-id="${p.id}" data-action="del-pos">Supprimer</button>
      </td>
    </tr>`;
  }).join('');

  const totGross = positions.reduce((s, p) => s + (p.gross_attributed || 0), 0);
  const totDebt  = positions.reduce((s, p) => s + (p.debt_attributed  || 0), 0);
  const totNet   = positions.reduce((s, p) => s + (p.net_attributed   || 0), 0);
  const totMob   = positions.reduce((s, p) => s + (p.mobilizable_value|| 0), 0);
  document.getElementById('positions-tfoot').innerHTML = `
    <tr>
      <td colspan="4">TOTAL</td>
      <td class="num">${fmt(totGross)}</td>
      <td class="num neg">${totDebt > 0 ? fmt(totDebt) : '—'}</td>
      <td class="num">${fmt(totNet)}</td>
      <td></td>
      <td class="num">${fmt(totMob)}</td>
      <td></td>
    </tr>`;

  document.getElementById('positions-tbody').addEventListener('click', onPosTableClick, { once: true });
}

function onPosTableClick(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const id = parseInt(btn.dataset.id);
  if (btn.dataset.action === 'edit-pos')         openPosModal(id);
  if (btn.dataset.action === 'del-pos')          deletePosition(id);
  if (btn.dataset.action === 'manage-holdings')  _openHoldingsForPosition(id);
  document.getElementById('positions-tbody').addEventListener('click', onPosTableClick, { once: true });
}

function _openHoldingsForPosition(id) {
  const p = S.positions.find(x => x.id === id);
  const label = p ? `${p.envelope || p.category} (${p.owner})` : '';
  openHoldingsModal(id, label);
}

export async function duplicateSnapshot() {
  if (!S.positionsDate) return;
  const newDate = await promptDialog('Nouvelle date pour le snapshot', {
    placeholder: 'AAAA-MM-JJ', defaultValue: today(), confirmText: 'Dupliquer'
  });
  if (!newDate) return;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(newDate)) {
    toast('Format invalide. Utilisez AAAA-MM-JJ (ex: 2026-04-01)', 'error');
    return;
  }
  if (S.dates.includes(newDate) && !await confirmDialog('Snapshot existant',
    `Un snapshot du ${fmtDate(newDate)} existe déjà. L'écraser ?`,
    { confirmText: 'Écraser', danger: true })) return;
  const src = await api('GET', `/api/positions?date=${S.positionsDate}`);
  await Promise.all(src.map(p => {
    const { id, created_at, net_value, gross_attributed, debt_attributed,
            net_attributed, liquidity, friction, mobilizable_pct, mobilizable_value,
            has_holdings, holdings_count, ...rest } = p;
    return api('POST', '/api/positions', { ...rest, date: newDate });
  }));
  // Fige l'etat des holdings a la nouvelle date
  try { await api('POST', '/api/holdings/snapshot', { date: newDate }, { silent: true }); }
  catch {}
  S.positionsDate = newDate;
  await refreshDates();
  await loadPositions();
  await loadHistorique();
}

export function openPosModal(id = null, prefill = {}) {
  S.editPosId = id;
  document.getElementById('position-modal-title').textContent =
    id ? 'Modifier la position' : 'Ajouter une position';

  if (id) {
    const p = S.positions.find(x => x.id === id);
    if (!p) return;
    document.getElementById('pos-date').value          = p.date;
    document.getElementById('pos-owner').value         = p.owner;
    document.getElementById('pos-category').value      = p.category;
    document.getElementById('pos-envelope').value      = p.envelope || '';
    document.getElementById('pos-establishment').value = p.establishment || '';
    document.getElementById('pos-value').value         = p.value || 0;
    document.getElementById('pos-debt').value          = p.debt || 0;
    document.getElementById('pos-ownership').value     = Math.round((p.ownership_pct ?? 1) * 100);
    document.getElementById('pos-debt-pct').value      = Math.round((p.debt_pct ?? 1) * 100);
    document.getElementById('pos-entity-select').value = p.entity || '';
    document.getElementById('pos-label').value         = p.label || '';
    document.getElementById('pos-notes').value         = p.notes || '';
    const hasOverride = p.mobilizable_pct_override != null || p.liquidity_override;
    document.getElementById('pos-mob-override-check').checked = hasOverride;
    document.getElementById('pos-mob-override-field').style.display = hasOverride ? 'flex' : 'none';
    document.getElementById('pos-mob-override-pct').value = p.mobilizable_pct_override != null ? Math.round(p.mobilizable_pct_override * 100) : 100;
    document.getElementById('pos-liquidity-override').value = p.liquidity_override || '';
    const hasPctFields = document.getElementById('pos-pct-fields');
    if (hasPctFields) hasPctFields.style.display = p.entity ? 'contents' : 'none';
    document.getElementById('pos-value').disabled = !!p.entity;
    document.getElementById('pos-debt').disabled  = !!p.entity;
    document.getElementById('pos-snapshot-option').classList.remove('hidden');
    document.getElementById('pos-snapshot-date').value = today();
    document.getElementById('pos-snapshot-check').checked = false;
    document.getElementById('pos-snapshot-date').style.visibility = 'hidden';
  } else {
    document.getElementById('pos-date').value         = S.positionsDate || today();
    document.getElementById('pos-owner').value        = S.config.owners[0];
    document.getElementById('pos-category').value     = S.config.categories[0];
    document.getElementById('pos-envelope').value     = '';
    document.getElementById('pos-establishment').value= '';
    document.getElementById('pos-value').value        = 0;
    document.getElementById('pos-debt').value         = 0;
    document.getElementById('pos-ownership').value    = 100;
    document.getElementById('pos-debt-pct').value     = 100;
    document.getElementById('pos-label').value          = '';
    document.getElementById('pos-notes').value          = '';
    document.getElementById('pos-mob-override-check').checked = false;
    document.getElementById('pos-mob-override-field').style.display = 'none';
    document.getElementById('pos-mob-override-pct').value = 100;
    document.getElementById('pos-liquidity-override').value = '';
    if (prefill.owner)         document.getElementById('pos-owner').value         = prefill.owner;
    if (prefill.establishment) document.getElementById('pos-establishment').value  = prefill.establishment;
    if (prefill.envelope)      document.getElementById('pos-envelope').value       = prefill.envelope;
    if (prefill.entity) {
      document.getElementById('pos-entity-select').value = prefill.entity;
      onEntitySelectChange();
    } else {
      document.getElementById('pos-entity-select').value = '';
      const hasPctFields = document.getElementById('pos-pct-fields');
      if (hasPctFields) hasPctFields.style.display = 'none';
      document.getElementById('pos-value').disabled = false;
      document.getElementById('pos-debt').disabled  = false;
    }
    document.getElementById('pos-snapshot-option').classList.add('hidden');
  }
  updatePosInfo();
  document.getElementById('position-modal').classList.remove('hidden');
  document.getElementById('pos-date').focus();
}

export function onEntitySelectChange() {
  const name = document.getElementById('pos-entity-select').value;
  const pctFields = document.getElementById('pos-pct-fields');

  document.getElementById('pos-value').disabled = !!name;
  document.getElementById('pos-debt').disabled  = !!name;
  if (pctFields) pctFields.style.display = name ? 'contents' : 'none';

  const etablInput = document.getElementById('pos-establishment');
  if (!name) {
    document.getElementById('pos-value').value = 0;
    document.getElementById('pos-debt').value  = 0;
    document.getElementById('pos-ownership').value = 100;
    document.getElementById('pos-debt-pct').value  = 100;
    etablInput.placeholder = 'ex : Boursorama';
    updatePosInfo();
    return;
  }
  if (!etablInput.value) etablInput.value = name;
  etablInput.placeholder = `Établissement gestionnaire de "${name}"`;

  const entity = S.entities.find(e => e.name === name);
  if (!entity) return;

  document.getElementById('pos-value').value = entity.gross_assets || 0;
  document.getElementById('pos-debt').value  = entity.debt || 0;

  const existingPct = S.positions
    .filter(p => p.entity === name && p.id !== S.editPosId)
    .reduce((s, p) => s + (p.ownership_pct || 0), 0);
  const remaining = Math.max(0, 1 - existingPct);

  if (remaining < 1) {
    document.getElementById('pos-ownership').value = Math.round(remaining * 100);
  }

  updatePosInfo();

  const byOwner = S.positions
    .filter(p => p.entity === name && p.id !== S.editPosId)
    .map(p => `${p.owner} ${Math.round((p.ownership_pct || 0) * 100)} %`);
  const hint = byOwner.length
    ? `Entité : ${entity.name} — Actif net ${fmt(entity.net_assets)}\nDétention déjà attribuée : ${byOwner.join(', ')} (total ${Math.round(existingPct * 100)} %)\nSuggestion détention : ${Math.round(remaining * 100)} %\n% dette indépendant — ex: 100% si emprunteur unique, 0% sinon.`
    : `Entité : ${entity.name} — Actif net ${fmt(entity.net_assets)}\nIndiquez votre % de détention et votre % de la dette (peuvent différer).`;
  document.getElementById('pos-computed-info').textContent = hint;
}

export function updatePosInfo() {
  const value       = parseFloat(document.getElementById('pos-value').value) || 0;
  const debt        = parseFloat(document.getElementById('pos-debt').value) || 0;
  const ownerPct    = (parseFloat(document.getElementById('pos-ownership').value) || 100) / 100;
  const debtPct     = (parseFloat(document.getElementById('pos-debt-pct').value) || 100) / 100;
  const envelope    = document.getElementById('pos-envelope').value;
  const category    = document.getElementById('pos-category').value;

  const gross    = value * ownerPct;
  const debtAttr = debt * debtPct;
  const net      = gross - debtAttr;

  const envMeta    = S.config.envelope_meta[envelope] || { liquidity: '30J+', friction: 'Mixte' };
  const useOverride = document.getElementById('pos-mob-override-check').checked;
  const mobPct     = useOverride
    ? (parseFloat(document.getElementById('pos-mob-override-pct').value) || 0) / 100
    : (S.config.category_mobilizable[category] ?? 0.8);
  const mob      = net > 0 ? net * mobPct : 0;
  const overrideLabel = useOverride ? ' ⚠ surchargé' : '';

  document.getElementById('pos-computed-info').textContent =
    `Net attribué : ${fmt(net)}  ·  Liquidité : ${envMeta.liquidity}  ·  Mobilisable : ${fmt(mob)} (${(mobPct * 100).toFixed(0)} %${overrideLabel})`;
}

export async function savePosition(e) {
  e.preventDefault();
  await ensureTodaySnapshot();
  const data = {
    date:          document.getElementById('pos-date').value,
    owner:         document.getElementById('pos-owner').value,
    category:      document.getElementById('pos-category').value,
    envelope:      document.getElementById('pos-envelope').value || null,
    establishment: document.getElementById('pos-establishment').value || null,
    value:         parseFloat(document.getElementById('pos-value').value) || 0,
    debt:          parseFloat(document.getElementById('pos-debt').value) || 0,
    ownership_pct: (parseFloat(document.getElementById('pos-ownership').value) || 100) / 100,
    debt_pct:      (parseFloat(document.getElementById('pos-debt-pct').value) || 100) / 100,
    entity:        document.getElementById('pos-entity-select').value || null,
    label:         document.getElementById('pos-label').value || null,
    notes:         document.getElementById('pos-notes').value || null,
    mobilizable_pct_override: document.getElementById('pos-mob-override-check').checked
      ? (parseFloat(document.getElementById('pos-mob-override-pct').value) || 0) / 100
      : null,
    liquidity_override: document.getElementById('pos-mob-override-check').checked
      ? (document.getElementById('pos-liquidity-override').value || null)
      : null,
  };

  if (S.editPosId) {
    const useSnapshot = document.getElementById('pos-snapshot-check').checked;
    const targetDate  = document.getElementById('pos-snapshot-date').value;

    if (useSnapshot && targetDate) {
      const sourceDate = S.positions.find(p => p.id === S.editPosId)?.date;
      if (targetDate !== sourceDate && S.dates.includes(targetDate) &&
          !await confirmDialog('Snapshot existant',
            `Le snapshot du ${fmtDate(targetDate)} sera remplacé par une copie du ${fmtDate(sourceDate)} avec cette modification.`,
            { confirmText: 'Remplacer', danger: true })) {
        return;
      }
      await api('POST', `/api/positions/${S.editPosId}/snapshot-update`, {
        source_date: sourceDate,
        target_date: targetDate,
        position:    data,
      });
      S.positionsDate = targetDate;
      S.syntheseDate  = targetDate;
    } else {
      await api('PUT', `/api/positions/${S.editPosId}`, data);
    }
  } else {
    await api('POST', '/api/positions', data);
  }

  closeModal('position-modal');
  toast(S.editPosId ? 'Position mise à jour' : 'Position ajoutée');
  await refreshDates();
  await loadPositions();
  await loadSynthese();
  await loadHistorique();
}

export async function deletePosition(id) {
  const pos = S.positions.find(p => p.id === id);
  const label = pos ? `${pos.category} — ${pos.owner}` : `Position #${id}`;
  if (!await confirmDialog('Supprimer la position ?', `<strong>${esc(label)}</strong><br>Cette action est irréversible.`)) return;
  await api('DELETE', `/api/positions/${id}`);
  toast('Position supprimée');
  await loadPositions();
  await loadSynthese();
  await loadHistorique();
}
