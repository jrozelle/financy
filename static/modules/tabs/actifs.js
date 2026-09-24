/**
 * Onglet Actifs. L'ecran est en Svelte (frontend/src/actifs/, compile dans
 * /dist/actifs.js) ; ce module charge les lignes consolidees, lance le
 * rapprochement avec le journal et garde le bouton « Rafraichir les cours »
 * du menu.
 */
import { S } from '../state.js';
import { api } from '../api.js';
import { isMasked } from '../mask.js';
import { triggerPricesRefresh } from './tools.js';
import { loadReconcile } from './reconcile.js';
import { lirePref, ecrirePref } from '../preferences.js';

const ACTIFS_COLUMNS_STORAGE_KEY = 'financy_columns_actifs';
const ACTIFS_ESTABLISHMENTS_MIGRATION_KEY = 'financy_columns_actifs_establishments_v1';

/** La colonne Etablissement, ajoutee apres coup, s'affiche une fois d'office
 *  chez qui avait deja choisi ses colonnes. */
function ensureEstablishmentColumnPreference() {
  try {
    if (lirePref(ACTIFS_ESTABLISHMENTS_MIGRATION_KEY)) return;
    const saved = JSON.parse(lirePref(ACTIFS_COLUMNS_STORAGE_KEY) || '{}');
    saved.establishments = true;
    ecrirePref(ACTIFS_COLUMNS_STORAGE_KEY, JSON.stringify(saved));
    ecrirePref(ACTIFS_ESTABLISHMENTS_MIGRATION_KEY, '1');
  } catch {}
}

export async function loadActifs() {
  ensureEstablishmentColumnPreference();
  const owner = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : '';
  const params = new URLSearchParams();
  const date = S.syntheseDate || S.positionsDate || S.dates?.[0];
  if (date) params.set('date', date);
  if (owner) params.set('owner', owner);
  const qs = params.toString();
  let donnees;
  try {
    donnees = await api('GET', `/api/holdings/consolidated${qs ? `?${qs}` : ''}`, null, { silent: true });
  } catch { return; }
  const cible = document.getElementById('actifs-app');
  if (!cible) return;
  const { afficher } = await import('/dist/actifs.js');
  afficher(cible, { donnees, masque: isMasked() });
  // Le rapprochement avec le journal des operations vit au-dessus du tableau :
  // il repond a « ces quantites sont-elles a jour ? », question que les chiffres
  // affiches ne posent jamais d'eux-memes.
  loadReconcile();
}

export function wireActifsEvents() {
  ensureEstablishmentColumnPreference();
  document.getElementById('actifs-refresh-prices')?.addEventListener('click', async () => {
    await triggerPricesRefresh(false);
    loadActifs();
  });
}
