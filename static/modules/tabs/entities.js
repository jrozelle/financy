import { S } from '../state.js';
import { fmt, fmtDate, esc, getColors, gridColor, destroyChart, parseLocaleNumber, fmtAxis,
         tsJour, echelleTemps, titreDate } from '../utils.js';
import { api, refreshEntitySelect } from '../api.js';
import { confirmDialog, toast, closeModal } from '../dialogs.js';
import { switchTab } from '../main.js';
import { openPosModal } from './positions.js';
import { montantPanneau } from '../drilldown.js';
import { isMasked } from '../mask.js';

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

// Le tableau est un ecran Svelte (frontend/src/entites/, compile dans
// /dist/entites.js) ; ce module charge les donnees et garde la fiche d'une
// entite et le panneau de son historique.
export async function renderEntities() {
  // Ouverte d'office tant qu'il n'y a rien : c'est alors qu'on en a besoin.
  const aide = document.getElementById('ent-aide');
  if (aide && !S.entities.length) aide.open = true;
  const cible = document.getElementById('entites-app');
  if (!cible) return;
  const { afficher } = await import('/dist/entites.js');
  afficher(cible, {
    entites: S.entities || [], arretes: S.entitySnapshots || [], positions: S.entityPositions || [],
    owner: S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : null, masque: isMasked(),
    onEditer: openEntityModal, onSupprimer: deleteEntity, onHistorique: showEntitySnapshots,
    onAjouterPosition: nom => switchTab('positions').then(() => openPosModal(null, { entity: nom })),
  });
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
  }).join('') || '<tr><td colspan="5" style="color:var(--text-muted);padding:var(--esp-12)">Aucune valorisation enregistrée.</td></tr>';

  document.getElementById('dd-subtitle').textContent = 'Entité';
  document.getElementById('dd-title').textContent = entityName;
  montantPanneau(entity ? fmt(entity.net_assets) + ' (actuel)' : '', entity?.net_assets || 0);
  const showChart = snaps.length >= 2;
  document.getElementById('dd-body').innerHTML = `
    ${showChart ? '<div style="position:relative;height:200px;margin-bottom:var(--esp-16)"><canvas id="entity-timeline-canvas"></canvas></div>' : ''}
    <p style="font-size:var(--fs-sm);color:var(--text-muted);margin-bottom:var(--esp-12)">
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
  document.getElementById('ent-supprimer')?.classList.toggle('hidden', !id);
  document.getElementById('entity-modal').classList.remove('hidden');
  if (!matchMedia('(pointer: coarse)').matches) document.getElementById('ent-name').focus();
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
  document.getElementById('entity-modal')?.classList.add('hidden');
  toast('Entité supprimée');
  await loadEntities();
  refreshEntitySelect();
}
