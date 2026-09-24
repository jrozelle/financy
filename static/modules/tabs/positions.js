import { S } from '../state.js';
import { fmt, fmtDate, esc, today, parseLocaleNumber, fmtPct } from '../utils.js';
import { api } from '../api.js';
import { confirmDialog, promptDialog, toast, closeModal } from '../dialogs.js';
import { loadSynthese, loadHistorique } from './synthese.js';
import { refreshDates, ecrireContexte } from '../main.js';

// L'onglet n'a plus qu'une vue, l'arborescence (frontend/src/positions/,
// compilee dans /dist/positions.js) : le tableau faisait double emploi, et
// « A plat » classe tous les comptes sur un rang. Ce module garde la fiche
// d'une position et les actions sur l'arrete.
let _arbo = null;

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
    S.positions = [];
    await renderPositions();
    return;
  }
  S.positions = await api('GET', `/api/positions?date=${S.positionsDate}`);
  _arbo?.oublierTitres();      // des positions rechargees : leurs lignes aussi
  await renderPositions();
}

/** Les positions vues par le titulaire de l'en-tete. */
function filteredPositions() {
  const qui = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : '';
  return (S.positions || []).filter(p => !qui || p.owner === qui);
}

export async function renderPositions() {
  const hote = document.getElementById('positions-tree-wrap');
  if (!hote) return;
  try {
    const { afficher } = await import('/dist/positions.js');
    _arbo = afficher(hote, filteredPositions());
  } catch {
    // Clone sans compilation : dire quoi faire plutot qu'un onglet vide.
    hote.innerHTML = `<p class="text-muted">L'écran Positions n'est pas compilé :
      <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>, puis rechargez la page.</p>`;
  }
}

/** Date du snapshot sur lequel agissent les actions du menu global.
 *
 * Ces actions (dupliquer / renommer / supprimer) vivent dans le menu ⚙, donc
 * cliquables depuis n'importe quel onglet, alors que `S.positionsDate` n'est
 * renseigne qu'au premier rendu de l'onglet Positions. Sans repli, un clic
 * depuis la Synthese (onglet par defaut) ne faisait strictement rien.
 * `S.dates` est trie DESC et charge des l'init : [0] = snapshot le plus recent.
 */
function currentSnapshotDate() {
  return S.positionsDate || S.syntheseDate || S.dates?.[0] || null;
}

export async function duplicateSnapshot() {
  const sourceDate = currentSnapshotDate();
  if (!sourceDate) {
    toast('Aucun arrêté à dupliquer', 'error');
    return;
  }
  const newDate = await promptDialog(
    `Nouvelle date pour la copie de l'arrêté du ${fmtDate(sourceDate)}`,
    { placeholder: 'AAAA-MM-JJ', defaultValue: today(), confirmText: 'Dupliquer' }
  );
  if (!newDate) return;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(newDate)) {
    toast('Format invalide. Utilisez AAAA-MM-JJ (ex: 2026-04-01)', 'error');
    return;
  }
  if (newDate === sourceDate) {
    toast('La date de la copie doit différer de celle de l’arrêté source', 'error');
    return;
  }
  if (S.dates.includes(newDate) && !await confirmDialog('Arrêté existant',
    `Un arrêté du ${fmtDate(newDate)} existe déjà. L'écraser ?`,
    { confirmText: 'Écraser', danger: true })) return;
  // Duplication cote serveur : copie positions ET holdings via le helper
  // robuste, et fige holdings_snapshots. Evite de reconstruire les positions
  // sans leurs holdings (bug : actifs vides apres duplication).
  try {
    await api('POST', '/api/snapshots/duplicate',
              { source_date: sourceDate, target_date: newDate });
  } catch { return; }
  S.positionsDate = newDate;
  S.syntheseDate  = newDate;
  ecrireContexte();
  await refreshDates();
  await loadPositions();
  await loadHistorique();
  await loadSynthese();
  toast(`Arrêté dupliqué au ${fmtDate(newDate)}`);
}

export async function renameSnapshot() {
  const fromDate = currentSnapshotDate();
  if (!fromDate) {
    toast('Aucun arrêté à modifier', 'error');
    return;
  }
  const newDate = await promptDialog(
    `Nouvelle date pour l'arrêté du ${fmtDate(fromDate)}`,
    { placeholder: 'AAAA-MM-JJ', defaultValue: fromDate, confirmText: 'Modifier' }
  );
  if (!newDate) return;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(newDate)) {
    toast('Format invalide. Utilisez AAAA-MM-JJ (ex: 2026-07-01)', 'error');
    return;
  }
  if (newDate === fromDate) return;
  if (S.dates.includes(newDate)) {
    toast(`Un arrêté du ${fmtDate(newDate)} existe déjà`, 'error');
    return;
  }
  try {
    await api('POST', '/api/snapshots/rename',
              { from_date: fromDate, to_date: newDate });
  } catch { return; }
  S.positionsDate = newDate;
  S.syntheseDate  = newDate;
  ecrireContexte();
  await refreshDates();
  await loadPositions();
  await loadHistorique();
  toast('Date de l’arrêté modifiée');
}

export async function deleteSnapshot() {
  const date = currentSnapshotDate();
  if (!date) {
    toast('Aucun arrêté à supprimer', 'error');
    return;
  }
  const ok = await confirmDialog(
    'Supprimer cet arrêté',
    `Supprimer définitivement l'arrêté du ${fmtDate(date)} ` +
    `(positions, holdings, archives, note) ? ` +
    `L'historique des autres dates est conservé.`,
    { confirmText: 'Supprimer', danger: true }
  );
  if (!ok) return;
  try {
    await api('POST', '/api/snapshots/delete', { date });
  } catch { return; }
  // Repli sur la date restante la plus recente (S.dates est trie DESC).
  const fallback = S.dates.filter(d => d !== date)[0] || null;
  S.positionsDate = fallback;
  S.syntheseDate  = fallback;
  ecrireContexte();
  await refreshDates();
  await loadPositions();
  await loadHistorique();
  await loadSynthese();
  toast('Arrêté supprimé');
}

export function openPosModal(id = null, prefill = {}) {
  S.editPosId = id;
  document.getElementById('pos-supprimer')?.classList.toggle('hidden', !id);
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
    // Au centime : une valeur deduite d'une entite s'affichait brute
    // (« 5367.970895604706 »).
    document.getElementById('pos-value').value         = Math.round((p.value || 0) * 100) / 100;
    document.getElementById('pos-debt').value          = Math.round((p.debt || 0) * 100) / 100;
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
    // Vu en famille, aucun titulaire n'est plus probable qu'un autre : le
    // premier de la liste s'imposait en silence. Le champ reste a choisir,
    // et `required` le rappelle a l'enregistrement.
    choisirTitulaire('pos-owner', prefill.owner);
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
  // Au doigt, un champ date qui prend le focus ouvre aussitot la roue d'iOS.
  if (!matchMedia('(pointer: coarse)').matches) document.getElementById('pos-date').focus();
}

/** Titulaire propose a la creation : celui de la vue, ou aucun en famille,
 *  avec une option « Choisir… » que le formulaire refuse (champ requis). */
export function choisirTitulaire(id, impose = null) {
  const sel = document.getElementById(id);
  if (!sel) return;
  if (!sel.querySelector('option[value=""]')) {
    sel.insertAdjacentHTML('afterbegin', '<option value="" disabled>Choisir le titulaire…</option>');
  }
  const vue = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : '';
  const cible = impose || vue;
  sel.value = [...sel.options].some(o => o.value === cible) ? cible : '';
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
  const value       = parseLocaleNumber(document.getElementById('pos-value').value, 0);
  const debt        = parseLocaleNumber(document.getElementById('pos-debt').value, 0);
  const ownerPct    = parseLocaleNumber(document.getElementById('pos-ownership').value, 100) / 100;
  const debtPct     = parseLocaleNumber(document.getElementById('pos-debt-pct').value, 100) / 100;
  const envelope    = document.getElementById('pos-envelope').value;
  const category    = document.getElementById('pos-category').value;

  const gross    = value * ownerPct;
  const debtAttr = debt * debtPct;
  const net      = gross - debtAttr;

  const envMeta    = S.config.envelope_meta[envelope] || { liquidity: '30J+', friction: 'Mixte' };
  const useOverride = document.getElementById('pos-mob-override-check').checked;
  const mobPct     = useOverride
    ? parseLocaleNumber(document.getElementById('pos-mob-override-pct').value, 0) / 100
    : (S.config.category_mobilizable[category] ?? 0.8);
  const mob      = net > 0 ? net * mobPct : 0;
  const overrideLabel = useOverride ? ', surchargé' : '';

  document.getElementById('pos-computed-info').textContent =
    `Net : ${fmt(net)}  ·  Liquidité : ${envMeta.liquidity}  ·  Mobilisable : ${fmt(mob)} (${fmtPct(mobPct * 100, 0)}${overrideLabel})`;
}

export async function savePosition(e) {
  e.preventDefault();
  // Edition en place d'une position existante -> ne PAS auto-creer un snapshot
  // "aujourd'hui" (evite un point parasite lors d'une correction a posteriori,
  // ex. actualisation des dettes quelques jours apres).
  const editingInPlace = S.editPosId && !document.getElementById('pos-snapshot-check').checked;
  if (!editingInPlace) await ensureTodaySnapshot();
  const data = {
    date:          document.getElementById('pos-date').value,
    owner:         document.getElementById('pos-owner').value,
    category:      document.getElementById('pos-category').value,
    envelope:      document.getElementById('pos-envelope').value || null,
    establishment: document.getElementById('pos-establishment').value || null,
    value:         parseLocaleNumber(document.getElementById('pos-value').value, 0),
    debt:          parseLocaleNumber(document.getElementById('pos-debt').value, 0),
    ownership_pct: parseLocaleNumber(document.getElementById('pos-ownership').value, 100) / 100,
    debt_pct:      parseLocaleNumber(document.getElementById('pos-debt-pct').value, 100) / 100,
    entity:        document.getElementById('pos-entity-select').value || null,
    label:         document.getElementById('pos-label').value || null,
    notes:         document.getElementById('pos-notes').value || null,
    mobilizable_pct_override: document.getElementById('pos-mob-override-check').checked
      ? parseLocaleNumber(document.getElementById('pos-mob-override-pct').value, 0) / 100
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
          !await confirmDialog('Arrêté existant',
            `L'arrêté du ${fmtDate(targetDate)} sera remplacé par une copie du ${fmtDate(sourceDate)} avec cette modification.`,
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
      ecrireContexte();
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
  const label = pos ? `${pos.envelope || pos.category} — ${pos.owner}` : `Position #${id}`;
  if (!await confirmDialog('Supprimer la position ?',
      `<strong>${esc(label)}</strong><br>Elle disparaît de l’arrêté du ${fmtDate(pos?.date || S.positionsDate)} seulement ; les autres arrêtés sont intacts.`,
      { confirmText: 'Supprimer', danger: true })) return;
  await api('DELETE', `/api/positions/${id}`);
  document.getElementById('position-modal')?.classList.add('hidden');
  toast('Position supprimée');
  await loadPositions();
  await loadSynthese();
  await loadHistorique();
}
