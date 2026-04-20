import { S } from '../state.js';
import { esc, today } from '../utils.js';
import { api, getCsrfToken } from '../api.js';
import { confirmDialog, toast } from '../dialogs.js';
import { loadTargets, saveTargets } from '../targets.js';
import { refreshDates, renderDateSelects, reloadAll } from '../main.js';
import { loadHistorique } from './synthese.js';
import { loadEntities, renderEntities } from './entities.js';
import { renderFlux } from './flux.js';
import { renderSynthese } from './synthese.js';

// ─── Demo mode ───────────────────────────────────────────────────────────────

export function updateDemoBadge({ demo, llmMock } = {}) {
  const badge = document.getElementById('demo-badge');
  if (!badge) return;
  let label = '';
  if (demo) label = 'Mode démo';
  else if (llmMock) label = 'LLM mocké';
  if (label) {
    badge.textContent = label;
    badge.classList.remove('hidden');
    badge.setAttribute('aria-hidden', 'false');
  } else {
    badge.classList.add('hidden');
    badge.setAttribute('aria-hidden', 'true');
  }
}

export async function initDemoToggle() {
  const toggle = document.getElementById('demo-toggle');
  const status = document.getElementById('demo-status');
  const card   = document.getElementById('demo-card');
  if (!toggle || !status) return;

  try {
    const res = await api('GET', '/api/demo-mode');
    if (!res.available) {
      card.style.display = 'none';
      updateDemoBadge({ demo: res.demo });
      return;
    }
    toggle.checked = res.demo;
    status.textContent = res.demo ? 'Mode démo actif' : 'Données réelles';
    updateDemoBadge({ demo: res.demo });
  } catch {
    card.style.display = 'none';
    return;
  }

  toggle.addEventListener('change', async () => {
    const demo = toggle.checked;
    try {
      await api('PUT', '/api/demo-mode', { demo });
      status.textContent = demo ? 'Mode démo actif' : 'Données réelles';
      updateDemoBadge({ demo });
      toast(demo ? 'Mode démo activé' : 'Retour aux données réelles');
      await reloadAll();
    } catch (err) {
      toggle.checked = !demo;
      toast('Erreur : ' + err.message);
    }
  });
}

export async function importXlsx() {
  const file = document.getElementById('import-file').files[0];
  if (!file) { showImportResult('Sélectionne un fichier .xlsx.', false); return; }

  const fd = new FormData();
  fd.append('file', file);
  const btn = document.getElementById('btn-import');
  if (btn) { btn.disabled = true; btn.textContent = 'Import en cours…'; }
  try {
    const res  = await fetch('/api/import', {
      method: 'POST',
      body: fd,
      headers: { 'X-CSRF-Token': getCsrfToken() },
    });
    const data = await res.json();
    if (res.ok) {
      const parts = [`✓ ${data.imported} position(s)`];
      if (data.entities) parts.push(`${data.entities} entité(s)`);
      showImportResult(parts.join(' · ') + ' importée(s).', true);
      await refreshDates();
      await loadHistorique();
    } else {
      showImportResult(`Erreur : ${data.error}`, false);
    }
  } catch (err) {
    showImportResult(`Erreur : ${err.message}`, false);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Importer'; }
  }
}

function showImportResult(msg, ok) {
  document.getElementById('import-result').innerHTML =
    `<div class="alert alert-${ok ? 'success' : 'error'}">${esc(msg)}</div>`;
}

export async function importJson() {
  const file = document.getElementById('import-json-file').files[0];
  if (!file) { showJsonImportResult('Sélectionne un fichier .json.', false); return; }

  const btn = document.getElementById('btn-import-json');
  if (btn) { btn.disabled = true; btn.textContent = 'Import en cours…'; }
  try {
    const text = await file.text();
    const data = JSON.parse(text);

    if (data.allocation_targets && typeof data.allocation_targets === 'object') {
      await saveTargets(data.allocation_targets);
    }

    const result = await api('POST', '/api/import-json', data);
    const parts = [];
    if (result.positions)        parts.push(`${result.positions} position(s)`);
    if (result.flux)             parts.push(`${result.flux} flux`);
    if (result.entities)         parts.push(`${result.entities} entité(s)`);
    if (result.entity_snapshots) parts.push(`${result.entity_snapshots} snapshot(s) entité`);
    showJsonImportResult('✓ Importé : ' + (parts.join(', ') || 'rien de nouveau') + '.', true);
    await refreshDates();
    await loadHistorique();
    await loadEntities();
  } catch (err) {
    showJsonImportResult(`Erreur : ${err.message}`, false);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Importer'; }
  }
}

function showJsonImportResult(msg, ok) {
  document.getElementById('import-json-result').innerHTML =
    `<div class="alert alert-${ok ? 'success' : 'error'}">${esc(msg)}</div>`;
}

const _TABLE_LABELS = {
  positions:          'positions',
  flux:               'flux',
  entities:           'entités',
  entity_snapshots:   'snapshots entités',
  snapshot_notes:     'notes de snapshot',
  holdings:           'lignes holdings',
  holdings_snapshots: 'snapshots holdings',
  price_history:      'cours historiques',
  securities:         'securities',
};

export async function resetDb() {
  if (!await confirmDialog(
    'Vider TOUTE la base ?',
    'Positions, flux et entités seront supprimés <strong>définitivement</strong>.<br>Faites un export JSON avant si vous souhaitez conserver vos données.',
    { confirmText: 'Tout supprimer', danger: true }
  )) return;
  let result;
  try {
    result = await api('POST', '/api/reset');
  } catch { return; }
  S.dates = []; S.syntheseDate = null; S.positionsDate = null;
  S.positions = []; S.flux = []; S.entities = []; S.historique = [];
  await refreshDates();
  renderDateSelects();
  renderEntities();
  renderFlux();
  renderSynthese();
  // Recap detaille des lignes supprimees
  const lines = Object.entries(result?.deleted || {})
    .filter(([, n]) => n > 0)
    .map(([t, n]) => `<li>${n.toLocaleString('fr-FR')} ${esc(_TABLE_LABELS[t] || t)}</li>`)
    .join('');
  const total = result?.total || 0;
  document.getElementById('reset-result').innerHTML = `
    <div class="alert alert-success">
      Base vidée — <strong>${total.toLocaleString('fr-FR')}</strong> ligne(s) supprimée(s).
      ${lines ? `<ul style="margin:.4rem 0 0 1.1rem;font-size:12.5px">${lines}</ul>` : ''}
    </div>`;
  setTimeout(() => { document.getElementById('reset-result').innerHTML = ''; }, 8000);
}

export async function createBackup() {
  try {
    const result = await api('POST', '/api/backup');
    document.getElementById('backup-result').innerHTML =
      `<div class="alert alert-success">${esc('✓ Backup créé')} (${result.size_kb} Ko)</div>`;
    toast('Backup créé');
  } catch (err) {
    document.getElementById('backup-result').innerHTML =
      `<div class="alert alert-error">${esc('Erreur : ' + err.message)}</div>`;
  }
}

export async function exportJson() {
  const data = await api('GET', '/api/export');
  data.allocation_targets = await loadTargets();
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url;
  a.download = `patrimoine_${today()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}
