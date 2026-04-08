import { S } from '../state.js';
import { fmt, fmtDate, esc, sortArr, updateSortIndicators, today, getColors, chartBorderColor, destroyChart } from '../utils.js';
import { api, refreshEntitySelect } from '../api.js';
import { confirmDialog, toast, closeModal } from '../dialogs.js';
import { switchTab } from '../main.js';
import { openPosModal } from './positions.js';

let _entityTimelineChart = null;

export async function loadEntities() {
  const lastDate = S.dates[0];
  [S.entities, S.entitySnapshots, S.entityPositions] = await Promise.all([
    api('GET', '/api/entities'),
    api('GET', '/api/entity-snapshots'),
    lastDate ? api('GET', `/api/positions?date=${lastDate}`) : Promise.resolve([]),
  ]);
  renderEntities();
  refreshEntitySelect();
}

function snapshotsByEntity() {
  const map = {};
  for (const s of (S.entitySnapshots || [])) {
    if (!map[s.entity_name]) map[s.entity_name] = [];
    map[s.entity_name].push(s);
  }
  return map;
}

export function renderEntities() {
  const tbody = document.getElementById('entities-tbody');
  if (!S.entities.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="9">Aucune entité. Ajoutez une SCI ou indivision.</td></tr>';
    return;
  }
  const snapMap = snapshotsByEntity();
  updateSortIndicators('entities-thead', 'entities');
  tbody.innerHTML = sortArr(S.entities, S.sort.entities.key, S.sort.entities.dir).map(e => {
    const linked   = (S.entityPositions || []).filter(p => p.entity === e.name);
    const totalPct = linked.reduce((s, p) => s + (p.ownership_pct || 0), 0);
    const owners   = linked.map(p =>
      `<span class="badge badge-j27" style="margin:1px 2px">${esc(p.owner)} ${Math.round((p.ownership_pct||0)*100)}%</span>`
    ).join('');
    const warn = linked.length > 0 && Math.abs(totalPct - 1) > 0.01
      ? `<div style="color:var(--danger);font-size:11px;margin-top:3px">⚠ Total ${Math.round(totalPct*100)}% — vérifier les %</div>`
      : '';
    const noLink = linked.length === 0
      ? '<span style="color:var(--text-muted);font-size:12px">Aucune position liée</span>'
      : '';
    const snaps = snapMap[e.name] || [];
    const lastSnap = snaps[0];
    const snapCell = snaps.length
      ? `<button class="btn-icon" style="font-size:11px;padding:.15rem .45rem" data-id="${e.id}" data-name="${esc(e.name)}" data-action="snap-hist">${snaps.length} entrée${snaps.length > 1 ? 's' : ''}<br><span style="color:var(--text-muted)">${fmtDate(lastSnap.date)}</span></button>`
      : '<span style="color:var(--text-muted);font-size:12px">—</span>';
    return `<tr>
      <td><strong>${esc(e.name)}</strong></td>
      <td>${esc(e.type || '—')}</td>
      <td>${esc(e.valuation_mode || '—')}</td>
      <td class="num">${fmt(e.gross_assets)}</td>
      <td class="num ${e.debt > 0 ? 'neg' : ''}">${e.debt > 0 ? fmt(e.debt) : '—'}</td>
      <td class="num ${e.net_assets < 0 ? 'neg' : 'pos'}">${fmt(e.net_assets)}</td>
      <td>${owners}${noLink}${warn}</td>
      <td>${esc(e.comment || '—')}</td>
      <td style="text-align:center">${snapCell}</td>
      <td style="white-space:nowrap">
        <button class="btn-icon add" data-action="add-pos-entity" data-name="${esc(e.name)}" title="Ajouter une position liée à cette entité">+ Position</button>
        <button class="btn-icon edit" data-id="${e.id}" data-action="edit-ent">Éditer</button>
        <button class="btn-icon del"  data-id="${e.id}" data-action="del-ent">Suppr.</button>
      </td>
    </tr>`;
  }).join('');

  tbody.addEventListener('click', onEntTableClick, { once: true });
}

function onEntTableClick(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const id = parseInt(btn.dataset.id);
  if (btn.dataset.action === 'edit-ent')  openEntityModal(id);
  if (btn.dataset.action === 'del-ent')   deleteEntity(id);
  if (btn.dataset.action === 'snap-hist') showEntitySnapshots(btn.dataset.name);
  if (btn.dataset.action === 'add-pos-entity') {
    const entityName = btn.dataset.name;
    switchTab('positions').then(() => openPosModal(null, { entity: entityName }));
  }
  document.getElementById('entities-tbody').addEventListener('click', onEntTableClick, { once: true });
}

function showEntitySnapshots(entityName) {
  const snaps = (S.entitySnapshots || []).filter(s => s.entity_name === entityName);
  const entity = S.entities.find(e => e.name === entityName);

  const rows = snaps.map(s => {
    const net = (s.gross_assets || 0) - (s.debt || 0);
    return `<tr>
      <td>${fmtDate(s.date)}</td>
      <td class="num">${fmt(s.gross_assets)}</td>
      <td class="num ${s.debt > 0 ? 'neg' : ''}">${s.debt > 0 ? fmt(s.debt) : '—'}</td>
      <td class="num ${net < 0 ? 'neg' : 'pos'}">${fmt(net)}</td>
      <td style="text-align:center">
        <button class="btn-icon del" style="font-size:11px" data-sid="${s.id}" data-action="del-snap">Suppr.</button>
      </td>
    </tr>`;
  }).join('') || '<tr><td colspan="5" style="color:var(--text-muted);padding:.75rem">Aucune valorisation enregistrée.</td></tr>';

  document.getElementById('dd-subtitle').textContent = 'Entité';
  document.getElementById('dd-title').textContent = entityName;
  document.getElementById('dd-amount').textContent = entity ? fmt(entity.net_assets) + ' (actuel)' : '';
  const showChart = snaps.length >= 2;
  document.getElementById('dd-body').innerHTML = `
    ${showChart ? '<div style="position:relative;height:200px;margin-bottom:1rem"><canvas id="entity-timeline-canvas"></canvas></div>' : ''}
    <p style="font-size:13px;color:var(--text-muted);margin-bottom:.75rem">
      Chaque modification de valeur crée une entrée datée. L'historique est utilisé pour reconstituer la valorisation aux dates passées.
    </p>
    <div class="table-scroll">
      <table class="data-table" id="snap-hist-table">
        <thead><tr>
          <th>Date</th>
          <th class="num">Actif brut</th>
          <th class="num">Dette</th>
          <th class="num">Actif net</th>
          <th></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;

  if (showChart) renderEntityTimeline(snaps);

  document.getElementById('snap-hist-table').addEventListener('click', async ev => {
    const btn = ev.target.closest('[data-action="del-snap"]');
    if (!btn) return;
    if (!await confirmDialog('Supprimer cette valorisation ?', 'Cette entrée historique sera supprimée définitivement.')) return;
    await api('DELETE', `/api/entity-snapshots/${btn.dataset.sid}`);
    S.entitySnapshots = S.entitySnapshots.filter(s => s.id !== parseInt(btn.dataset.sid));
    showEntitySnapshots(entityName);
    renderEntities();
  });

  document.getElementById('drilldown-panel').classList.remove('hidden');
}

export function openEntityModal(id = null) {
  S.editEntityId = id;
  document.getElementById('entity-modal-title').textContent =
    id ? 'Modifier l\'entité' : 'Ajouter une entité';

  if (id) {
    const e = S.entities.find(x => x.id === id);
    if (!e) return;
    document.getElementById('ent-name').value      = e.name;
    document.getElementById('ent-type').value      = e.type || '';
    document.getElementById('ent-valuation').value = e.valuation_mode || '';
    document.getElementById('ent-gross').value     = e.gross_assets || 0;
    document.getElementById('ent-debt').value      = e.debt || 0;
    document.getElementById('ent-comment').value   = e.comment || '';
  } else {
    document.getElementById('ent-name').value      = '';
    document.getElementById('ent-type').value      = '';
    document.getElementById('ent-valuation').value = '';
    document.getElementById('ent-gross').value     = 0;
    document.getElementById('ent-debt').value      = 0;
    document.getElementById('ent-comment').value   = '';
  }
  updateEntInfo();
  const warn = document.getElementById('ent-retro-warning');
  if (warn) warn.style.display = id ? '' : 'none';
  document.getElementById('entity-modal').classList.remove('hidden');
  document.getElementById('ent-name').focus();
}

export function updateEntInfo() {
  const gross = parseFloat(document.getElementById('ent-gross').value) || 0;
  const debt  = parseFloat(document.getElementById('ent-debt').value) || 0;
  document.getElementById('ent-computed-info').textContent =
    `Actif net entité : ${fmt(gross - debt)}`;
}

export async function saveEntity(e) {
  e.preventDefault();
  const data = {
    name:           document.getElementById('ent-name').value.trim(),
    type:           document.getElementById('ent-type').value || null,
    valuation_mode: document.getElementById('ent-valuation').value || null,
    gross_assets:   parseFloat(document.getElementById('ent-gross').value) || 0,
    debt:           parseFloat(document.getElementById('ent-debt').value) || 0,
    comment:        document.getElementById('ent-comment').value || null,
  };
  try {
    if (S.editEntityId) {
      await api('PUT', `/api/entities/${S.editEntityId}`, data);
    } else {
      await api('POST', '/api/entities', data);
    }
    closeModal('entity-modal');
    toast(S.editEntityId ? 'Entité mise à jour' : 'Entité ajoutée');
    await loadEntities();
    refreshEntitySelect();
  } catch (err) {
    toast(`Erreur : ${err.message}`, 'error');
  }
}

function renderEntityTimeline(snaps) {
  const canvas = document.getElementById('entity-timeline-canvas');
  if (!canvas) return;
  _entityTimelineChart = destroyChart(_entityTimelineChart);

  const sorted = [...snaps].sort((a, b) => a.date.localeCompare(b.date));
  const labels = sorted.map(s => fmtDate(s.date));
  const netData = sorted.map(s => (s.gross_assets || 0) - (s.debt || 0));
  const grossData = sorted.map(s => s.gross_assets || 0);
  const colors = getColors();
  const border = chartBorderColor();

  _entityTimelineChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Actif net',
          data: netData,
          borderColor: colors[0],
          backgroundColor: colors[0] + '22',
          fill: true,
          tension: 0.3,
          pointRadius: 4,
          borderWidth: 2,
        },
        {
          label: 'Actif brut',
          data: grossData,
          borderColor: colors[1],
          borderDash: [5, 3],
          tension: 0.3,
          pointRadius: 3,
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
        x: { ticks: { font: { size: 10 } }, grid: { display: false } },
      },
    },
  });
}

export async function deleteEntity(id) {
  const e = S.entities.find(x => x.id === id);
  const name = e?.name || `Entité #${id}`;
  if (!await confirmDialog(
    `Supprimer l'entité ?`,
    `<strong>${esc(name)}</strong><br>Les positions liées perdront leur référence entité.`
  )) return;

  try {
    await api('DELETE', `/api/entities/${id}`, null, { silent: true });
  } catch (err) {
    // 409: positions linked — ask for force confirmation
    if (err.message.includes('position(s) liée(s)')) {
      if (!await confirmDialog(
        'Positions liées',
        `${esc(err.message)}<br><br>La référence entité sera retirée de ces positions. Continuer ?`
      )) return;
      await api('DELETE', `/api/entities/${id}?force=1`);
    } else {
      toast(err.message, 'error');
      return;
    }
  }
  toast('Entité supprimée');
  await loadEntities();
  refreshEntitySelect();
}
