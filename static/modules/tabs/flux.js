import { S } from '../state.js';
import { esc, today, parseLocaleNumber, fluxSigned as signed, fmtSigned as eurSigned } from '../utils.js';
import { api } from '../api.js';
import { confirmDialog, toast, closeModal } from '../dialogs.js';
import { isMasked } from '../mask.js';
import { choisirTitulaire } from './positions.js';

// Le journal et l'import sont un ecran Svelte (frontend/src/flux/, compile
// dans /dist/flux.js) ; ce module charge les donnees et garde la fiche d'un
// flux, partagee avec la recherche et le bouton d'ajout.

export async function loadFlux() {
  S.flux = await api('GET', '/api/flux');
  // Suggestions d'etablissements de la fiche : ceux deja vus dans les flux et
  // dans les positions, pour eviter les variantes d'orthographe qui
  // creeraient des comptes fantomes ("BoursoBank" vs "Boursorama").
  const dl = document.getElementById('flux-etab-list');
  if (dl) {
    const known = new Set([
      ...S.flux.map(f => f.establishment).filter(Boolean),
      ...(S.positions || []).map(p => p.establishment).filter(Boolean),
    ]);
    dl.innerHTML = [...known].sort().map(e => `<option value="${esc(e)}">`).join('');
  }
  await renderFlux();
}

/** Personnes proposees a l'import.
 *
 *  Le referentiel et les donnees peuvent diverger — une base de test annonce
 *  "Personne 1..4" alors que les positions sont au nom de leur vrai proprietaire.
 *  Importer sous un nom absent des positions creerait des flux orphelins,
 *  invisibles dans la performance. On propose donc l'union des deux, et le choix
 *  reste affiche et modifiable avant l'enregistrement.
 */
function _ownerChoices() {
  const seen = new Set([
    ...(S.config?.owners || []),
    ...S.flux.map(f => f.owner).filter(Boolean),
    ...(S.positions || []).map(p => p.owner).filter(Boolean),
  ]);
  return [...seen].sort();
}

/** Priorite au titulaire de l'en-tete, puis a une personne ayant deja des
 *  flux (donc rattachable), en dernier recours au referentiel. */
function _defaultOwner(global) {
  return global || S.flux.map(f => f.owner).find(Boolean) || _ownerChoices()[0] || '';
}

export async function renderFlux() {
  const cible = document.getElementById('flux-app');
  if (!cible) return;
  const { afficher } = await import('/dist/flux.js');
  const owner = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : null;
  afficher(cible, {
    flux: S.flux || [], owner, masque: isMasked(),
    titulaires: _ownerChoices(), titulaireDefaut: _defaultOwner(owner),
    onEditer: openFluxModal, onSupprimer: deleteFlux, onEnregistre: loadFlux,
  });
}

export function openFluxModal(id = null) {
  S.editFluxId = id;
  document.getElementById('flux-modal-title').textContent =
    id ? 'Modifier le flux' : 'Ajouter un flux';

  if (id) {
    const f = S.flux.find(x => x.id === id);
    if (!f) return;
    document.getElementById('flux-date').value     = f.date;
    document.getElementById('flux-owner').value    = f.owner;
    document.getElementById('flux-envelope').value = f.envelope || '';
    document.getElementById('flux-establishment').value = f.establishment || '';
    document.getElementById('flux-category').value = f.category || '';
    document.getElementById('flux-type').value     = f.type || '';
    document.getElementById('flux-amount').value   = f.amount;
    document.getElementById('flux-notes').value    = f.notes || '';
  } else {
    document.getElementById('flux-date').value     = today();
    choisirTitulaire('flux-owner');
    document.getElementById('flux-envelope').value = '';
    document.getElementById('flux-establishment').value = '';
    document.getElementById('flux-category').value = '';
    document.getElementById('flux-type').value     = S.config.flux_types[0];
    document.getElementById('flux-amount').value   = '';
    document.getElementById('flux-notes').value    = '';
  }
  document.getElementById('flux-supprimer')?.classList.toggle('hidden', !id);
  document.getElementById('flux-modal').classList.remove('hidden');
  // Au doigt, le focus ouvrirait le clavier sur la fiche encore invisible.
  if (!matchMedia('(pointer: coarse)').matches) document.getElementById('flux-amount').focus();
}

export async function saveFlux(e) {
  e.preventDefault();
  const data = {
    date:     document.getElementById('flux-date').value,
    owner:    document.getElementById('flux-owner').value,
    envelope: document.getElementById('flux-envelope').value || null,
    establishment: document.getElementById('flux-establishment').value.trim() || null,
    category: document.getElementById('flux-category').value || null,
    type:     document.getElementById('flux-type').value || null,
    amount:   parseLocaleNumber(document.getElementById('flux-amount').value),
    notes:    document.getElementById('flux-notes').value || null,
  };
  if (S.editFluxId) {
    await api('PUT', `/api/flux/${S.editFluxId}`, data);
  } else {
    await api('POST', '/api/flux', data);
  }
  closeModal('flux-modal');
  toast(S.editFluxId ? 'Flux mis à jour' : 'Flux ajouté');
  await loadFlux();
}

export async function deleteFlux(id) {
  const f = S.flux.find(x => x.id === id);
  const label = f ? `${f.type || 'Flux'} — ${eurSigned(signed(f))} (${f.owner})` : `Flux #${id}`;
  if (!await confirmDialog('Supprimer ce flux ?', `<strong>${esc(label)}</strong><br>Cette action est irréversible.`)) return;
  await api('DELETE', `/api/flux/${id}`);
  document.getElementById('flux-modal')?.classList.add('hidden');
  toast('Flux supprimé');
  await loadFlux();
}
