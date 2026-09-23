import { S } from '../state.js';
import { fmt, fmtDate, esc, sortArr, updateSortIndicators, getColors, gridColor, destroyChart, parseLocaleNumber, fmtAxis,
         tsJour, echelleTemps, titreDate } from '../utils.js';
import { api, refreshEntitySelect } from '../api.js';
import { confirmDialog, toast, closeModal } from '../dialogs.js';
import { switchTab } from '../main.js';
import { openPosModal } from './positions.js';
import { montantPanneau } from '../drilldown.js';

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
  // Ouverte d'office tant qu'il n'y a rien : c'est alors qu'on en a besoin.
  const aide = document.getElementById('ent-aide');
  if (aide && !S.entities.length) aide.open = true;
  if (!tbody._cable) { tbody.addEventListener('click', onEntTableClick); tbody._cable = true; }
  if (!S.entities.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="7">Aucune entité. Ajoutez une SCI ou une indivision.</td></tr>';
    return;
  }
  const snapMap = snapshotsByEntity();
  updateSortIndicators('entities-thead', 'entities');
  // Vue d'un titulaire : ses seules entites, et sa part sous chaque montant —
  // brut a sa part de propriete, dette a sa part de dette (66 / 34 sur une
  // residence detenue a moitie). L'entite reste montree entiere : c'est la
  // page des entites, et la part se lit contre le tout.
  const qui = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : null;
  const visibles = qui ? S.entities.filter(e => (S.entityPositions || []).some(p => p.entity === e.name && p.owner === qui))
                       : S.entities;
  if (qui && !visibles.length) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="7">${esc(qui)} ne détient de parts dans aucune entité.</td></tr>`;
    return;
  }
  tbody.innerHTML = sortArr(visibles, S.sort.entities.key, S.sort.entities.dir).map(e => {
    const linked   = (S.entityPositions || []).filter(p => p.entity === e.name);
    const siennes  = qui ? linked.filter(p => p.owner === qui) : [];
    const pPart = siennes.reduce((t, p) => t + (p.ownership_pct || 0), 0);
    const dPart = siennes.reduce((t, p) => t + (p.debt_pct ?? p.ownership_pct ?? 0), 0);
    const part = (v, k) => qui ? `<div class="ent-part">part de ${esc(qui)} : ${fmt(v * k)} · ${Math.round(k * 100)} %</div>` : '';
    const totalPct = linked.reduce((s, p) => s + (p.ownership_pct || 0), 0);
    const owners   = linked.map(p =>
      `<span class="badge badge-j27">${esc(p.owner)} ${Math.round((p.ownership_pct||0)*100)} %</span>`
    ).join('');
    // Moins de 100 % dans le foyer n'est pas une erreur : un bien indivis avec
    // un frere, une SCI avec un associe. Plus de 100 %, si.
    let repartition = '';
    if (linked.length && totalPct > 1.01) {
      repartition = `<div class="ent-alerte">Total ${Math.round(totalPct*100)} % : les parts dépassent l'entité</div>`;
    } else if (linked.length && totalPct < 0.99) {
      repartition = `<div class="ent-note">${Math.round((1 - totalPct)*100)} % hors foyer</div>`;
    }
    const noLink = linked.length === 0 ? '<span class="ent-note">Aucune position liée</span>' : '';
    const nature = [e.type, e.valuation_mode && e.valuation_mode.toLowerCase()].filter(Boolean).join(' · ');
    const snaps = snapMap[e.name] || [];
    const lastSnap = snaps[0];
    const snapCell = snaps.length
      ? `<button class="btn-icon ent-histo" data-id="${e.id}" data-name="${esc(e.name)}" data-action="snap-hist">${snaps.length} valeur${snaps.length > 1 ? 's' : ''}<span>${fmtDate(lastSnap.date)}</span></button>`
      : '<span class="ent-note">—</span>';
    return `<tr>
      <td class="ent-nom"><strong>${esc(e.name)}</strong>${nature ? `<div class="ent-note">${esc(nature)}</div>` : ''}${e.comment ? `<div class="ent-note">${esc(e.comment)}</div>` : ''}</td>
      <td class="num ent-valeur" data-lib="Valeur">${fmt(e.gross_assets)}${part(e.gross_assets, pPart)}</td>
      <td class="num ent-dette ${e.debt > 0 ? 'neg' : ''}" data-lib="Dette">${e.debt > 0 ? fmt(e.debt) : '—'}${e.debt > 0 ? part(e.debt, dPart) : ''}</td>
      <td class="num ent-net ${e.net_assets < 0 ? 'neg' : 'pos'}">${fmt(e.net_assets)}${qui
        ? `<div class="ent-part">part de ${esc(qui)} : ${fmt(e.gross_assets * pPart - (e.debt || 0) * dPart)}</div>` : ''}</td>
      <td class="ent-detenteurs">${owners}${noLink}${repartition}</td>
      <td class="ent-c-histo">${snapCell}</td>
      <td class="ent-actions">
        <button class="btn-icon add" data-action="add-pos-entity" data-name="${esc(e.name)}">+ Position</button>
        <button class="btn-icon edit" data-id="${e.id}" data-action="edit-ent">Éditer</button>
        <button class="btn-icon del"  data-id="${e.id}" data-action="del-ent" aria-label="Supprimer ${esc(e.name)}">Supprimer</button>
      </td>
    </tr>`;
  }).join('');
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
        <button class="btn-icon del ent-suppr" data-sid="${s.id}" data-action="del-snap"
          aria-label="Supprimer la valeur du ${fmtDate(s.date)}">×</button>
      </td>
    </tr>`;
  }).join('') || '<tr><td colspan="5" style="color:var(--text-muted);padding:.75rem">Aucune valorisation enregistrée.</td></tr>';

  document.getElementById('dd-subtitle').textContent = 'Entité';
  document.getElementById('dd-title').textContent = entityName;
  montantPanneau(entity ? fmt(entity.net_assets) + ' (actuel)' : '', entity?.net_assets || 0);
  const showChart = snaps.length >= 2;
  document.getElementById('dd-body').innerHTML = `
    ${showChart ? '<div style="position:relative;height:200px;margin-bottom:1rem"><canvas id="entity-timeline-canvas"></canvas></div>' : ''}
    <p style="font-size:13px;color:var(--text-muted);margin-bottom:.75rem">
      Chaque modification de valeur crée une entrée datée. L'historique est utilisé pour reconstituer la valorisation aux dates passées.
    </p>
    <div class="table-scroll" tabindex="0" role="region" aria-label="Valeurs enregistrées">
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
  const gross = parseLocaleNumber(document.getElementById('ent-gross').value, 0);
  const debt  = parseLocaleNumber(document.getElementById('ent-debt').value, 0);
  document.getElementById('ent-computed-info').textContent =
    `Actif net entité : ${fmt(gross - debt)}`;
}

export async function saveEntity(e) {
  e.preventDefault();
  const data = {
    name:           document.getElementById('ent-name').value.trim(),
    type:           document.getElementById('ent-type').value || null,
    valuation_mode: document.getElementById('ent-valuation').value || null,
    gross_assets:   parseLocaleNumber(document.getElementById('ent-gross').value, 0),
    debt:           parseLocaleNumber(document.getElementById('ent-debt').value, 0),
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
  // Echelle de temps : les valeurs d'une entite se saisissent a intervalles
  // irreguliers, et une echelle `category` les espacerait regulierement.
  const netData = sorted.map(s => ({ x: tsJour(s.date), y: (s.gross_assets || 0) - (s.debt || 0) }));
  const grossData = sorted.map(s => ({ x: tsJour(s.date), y: s.gross_assets || 0 }));
  const colors = getColors();
  const border = gridColor();

  _entityTimelineChart = new Chart(canvas, {
    type: 'line',
    data: {
      datasets: [
        {
          label: 'Actif net',
          data: netData,
          borderColor: colors[0],
          backgroundColor: colors[0] + '22',
          fill: true,
          cubicInterpolationMode: 'monotone',
          pointRadius: 4,
          borderWidth: 2,
        },
        {
          label: 'Actif brut',
          data: grossData,
          borderColor: colors[1],
          borderDash: [5, 3],
          cubicInterpolationMode: 'monotone',
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
        tooltip: { mode: 'nearest', intersect: false, callbacks: { title: titreDate, label: ctx => ` ${ctx.dataset.label} : ${fmt(ctx.parsed.y)}` } },
      },
      scales: {
        y: {
          ticks: {
            callback: fmtAxis,
            font: { size: 11 },
          },
          grid: { color: border },
        },
        x: echelleTemps(sorted.map(s => s.date)),
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
