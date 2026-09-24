// L'ecran Import / Export est en Svelte (frontend/src/import/, compile dans
// /dist/import.js). Restent ici le badge du mode demo, l'export et ce que les
// imports et la remise a zero changent dans le reste de l'application.
import { S } from '../state.js';
import { today } from '../utils.js';
import { api } from '../api.js';
import { loadTargets, saveTargets } from '../targets.js';
import { refreshDates, renderDateSelects, reloadAll } from '../main.js';
import { loadHistorique } from './synthese.js';
import { loadEntities, renderEntities } from './entities.js';
import { renderFlux } from './flux.js';
import { renderSynthese } from './synthese.js';

// ─── Demo mode ───────────────────────────────────────────────────────────────

let _demoMode = false;
let _llmMockMode = false;

export function updateDemoBadge({ demo, llmMock } = {}) {
  const badge = document.getElementById('demo-badge');
  if (!badge) return;
  if (typeof demo === 'boolean') _demoMode = demo;
  if (typeof llmMock === 'boolean') _llmMockMode = llmMock;
  const showLlmMock = _llmMockMode && S.currentTab === 'conseil';
  let label = '';
  if (_demoMode) label = 'Mode démo';
  else if (showLlmMock) label = 'LLM mocké';
  if (label) {
    badge.textContent = label;
    badge.classList.remove('hidden');
    badge.setAttribute('aria-hidden', 'false');
  } else {
    badge.classList.add('hidden');
    badge.setAttribute('aria-hidden', 'true');
  }
}

/** Au demarrage : l'etat du mode demo regle le badge, puis l'ecran se monte
 *  (il n'a pas de chargement propre, et la fenetre des Reglages peut l'ouvrir
 *  a tout moment). */
export async function initDemoToggle() {
  let demo;
  try {
    const res = await api('GET', '/api/demo-mode');
    demo = { available: !!res.available, demo: !!res.demo };
  } catch {
    demo = { available: false, demo: false };
  }
  updateDemoBadge({ demo: demo.demo });
  const cible = document.getElementById('import-app');
  if (!cible) return;
  const { afficher } = await import('/dist/import.js');
  afficher(cible, { demo, rappels: {
    // Ancien format : les cibles voyageaient a part. Le format 2 les porte dans
    // `config`, que le serveur n'applique que si elles manquent.
    avantImportJson: async data => {
      if (!data.format && data.allocation_targets && typeof data.allocation_targets === 'object') {
        await saveTargets(data.allocation_targets);
      }
    },
    apresImport: async json => {
      await refreshDates();
      await loadHistorique();
      if (json) await loadEntities();
    },
    apresReset: async () => {
      S.dates = []; S.syntheseDate = null; S.positionsDate = null;
      S.positions = []; S.flux = []; S.entities = []; S.historique = [];
      await refreshDates();
      renderDateSelects();
      renderEntities();
      renderFlux();
      renderSynthese();
    },
    basculerDemo: async demoActive => {
      updateDemoBadge({ demo: demoActive });
      await reloadAll();
    },
    exporter: exportJson,
  } });
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
