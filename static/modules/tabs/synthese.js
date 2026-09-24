import { S } from '../state.js';
import { fmt, fmtDate, parseLocaleNumber, fmtPct } from '../utils.js';
import { api } from '../api.js';
import { loadTodo, renderTodo } from '../todo.js';
import { loadUserAlerts } from '../alerts.js';
import { isMasked } from '../mask.js';
import { appliquerDisposition } from '../widgets.js';
import { toast, promptDialog } from '../dialogs.js';

function _owners() {
  return S.synthese?._owners || S.config.owners;
}

// Changer vite d'arrete ou de titulaire lance plusieurs chargements : seul le
// dernier ecrit. Sans ce jeton, une reponse lente reaffichait l'arrete quitte.
let _jetonSynthese = 0;

export async function loadSynthese() {
  if (!S.syntheseDate && S.dates.length) S.syntheseDate = S.dates[0];
  const jeton = ++_jetonSynthese;
  if (!S.syntheseDate) {
    _renderSyntheseEmpty();
    return;
  }
  _clearSyntheseEmpty();
  const date = S.syntheseDate;
  const [syn, positions] = await Promise.all([
    api('GET', `/api/synthese?date=${date}`),
    api('GET', `/api/positions?date=${date}`),
    loadWealthTarget(),
  ]);
  if (jeton !== _jetonSynthese) return;
  // Build owner list: union of config owners + actual data owners
  const dataOwners = [...new Set(positions.map(p => p.owner))];
  const allOwners = [...S.config.owners];
  for (const o of dataOwners) {
    if (!allOwners.includes(o)) allOwners.push(o);
  }
  syn._owners = allOwners;
  syn._positions_cache = {};
  for (const o of allOwners) {
    syn._positions_cache[o] = positions.filter(p => p.owner === o);
  }
  S.synthese = syn;
  renderSynthese();
}

function _renderSyntheseEmpty() {
  const host = document.getElementById('tab-synthese');
  if (!host || host.querySelector('.empty-state-synthese')) return;
  // Masquer le contenu existant pendant l'etat vide
  host.querySelectorAll('.kpi-grid, .charts-row, .card').forEach(el => el.classList.add('hidden'));
  const card = document.createElement('div');
  card.className = 'card empty-state empty-state-synthese';
  card.innerHTML = `
    <div style="text-align:center;padding:1.5rem .5rem">
      <h2 style="margin-bottom:.5rem">Aucun arrêté pour le moment</h2>
      <p class="text-muted" style="font-size:13.5px;margin-bottom:1.25rem;line-height:1.6">
        Commencez par ajouter une position ou importer un fichier existant
        pour que votre patrimoine s'affiche ici.
      </p>
      <div style="display:flex;gap:.5rem;justify-content:center;flex-wrap:wrap">
        <button class="btn btn-primary" data-tab-switch="positions">+ Ajouter une position</button>
        <button class="btn btn-secondary" data-tab-switch="import">&#8645; Importer des données</button>
      </div>
    </div>`;
  // L'onglet n'a pas d'en-tete de page : la carte passe en tete de l'onglet.
  host.prepend(card);
  // Delegue au listener global (main.js) qui appelle switchTab
}

function _clearSyntheseEmpty() {
  const host = document.getElementById('tab-synthese');
  host?.querySelector('.empty-state-synthese')?.remove();
  host?.querySelectorAll('.kpi-grid, .charts-row, .card').forEach(el => el.classList.remove('hidden'));
}

/** Redessine la synthese deja chargee. `cache` : reutilise les reponses
 *  deja recues (bascule du mode discretion) au lieu de tout redemander. */
let _svelte = null;
async function _cartesSvelte({ chiffres, repartition, comptes, cache = false }) {
  try {
    _svelte ??= await import('/dist/synthese.js');
  } catch {
    // Clone sans compilation : le dire dans la carte des chiffres.
    const hote = document.querySelector('.kpi-grid[data-carte="chiffres"]');
    if (hote && !hote.querySelector('.carte-non-compilee')) hote.insertAdjacentHTML('beforeend',
      `<p class="card text-muted carte-non-compilee">Écrans de la synthèse non compilés :
        <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>.</p>`);
    return;
  }
  const g = document.querySelector('.kpi-grid[data-carte="chiffres"]');
  if (g) {
    _svelte.afficherChiffres(g, chiffres);
    // Au premier montage, l'objectif avait ete ecrit dans l'ancien element
    // (le chargement du module est asynchrone) : on le reecrit dans le neuf.
  }
  const r = document.getElementById('repartition-card');
  if (r) _svelte.afficherRepartition(r, repartition);
  const c = document.getElementById('comptes-card');
  if (c) _svelte.rechargerComptes(c, comptes.owner, comptes.date);
  // D'ou vient la hausse, Impot latent : ecrans Svelte (lot 2).
  const h = document.getElementById('card-contribution');
  if (h) _svelte.rechargerContribution(h, isMasked(), cache, comptes.owner, S.syntheseDate, S.dates?.[0] || null);
  const f = document.getElementById('fiscalite-card');
  if (f) _svelte.rechargerFiscalite(f, isMasked(), comptes.owner, S.syntheseDate);
  _evolutionSvelte();
}

/** Evolution du net, evolution par groupe, ce qui a bouge (lot 3a). Aussi
 *  appelee quand l'historique se recharge seul (loadHistorique). */
function _evolutionSvelte() {
  if (!_svelte) return;
  const owner = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : null;
  const masque = isMasked();
  const h = document.querySelector('.card[data-carte="historique"]');
  if (h) _svelte.afficherHistoriqueNet(h, { historique: S.historique || [], owner, masque });
  const g = document.getElementById('synthese-history-detail-card');
  if (g) _svelte.afficherEvolutionGroupes(g, { owner, arretes: (S.historique || []).length, masque });
  const m = document.querySelector('.card[data-carte="mouvements"]');
  if (m) _svelte.afficherMouvements(m, { owner, famille: !owner, date: S.syntheseDate, masque });
}

/** Liquidite, entites, ecart a la cible, note de l'arrete (lot 3b). */
async function _cartes3b({ liqFiltered, posTitulaire, owner, syn }) {
  try { _svelte ??= await import('/dist/synthese.js'); } catch { return; }
  const masque = isMasked();
  const l = document.querySelector('.card[data-carte="liquidite"]');
  if (l) _svelte.afficherLiquidite(l, { parLiquidite: liqFiltered, positions: posTitulaire, masque });
  const e = document.getElementById('entities-synthese-card');
  if (e) _svelte.afficherEntites(e, { entites: S.entities || [], owner, masque,
    positions: Object.values(syn._positions_cache || {}).flat() });
  const c = document.querySelector('.card[data-carte="cible"]');
  if (c) _svelte.afficherCible(c, { synthese: syn, owner, categories: S.config?.categories || [] });
  _noteSvelte(syn);
}

async function _noteSvelte(syn) {
  try { _svelte ??= await import('/dist/synthese.js'); } catch { return; }
  const n = document.getElementById('snapshot-note-bar');
  if (n) _svelte.afficherNote(n, { note: syn.snapshot_note || null,
    onModifier: () => openSnapshotNoteEditor(syn.date, syn.snapshot_note) });
}

async function _projectionSvelte(props) {
  try { _svelte ??= await import('/dist/synthese.js'); } catch { return; }
  const hote = document.getElementById('card-projection');
  if (hote) _svelte.afficherProjection(hote, props);
}

export function renderSynthese({ cache = false } = {}) {
  const syn = S.synthese;
  if (!syn?.date) {
    ['kpi-net','kpi-gross','kpi-debt','kpi-mobilizable'].forEach(id => {
      document.getElementById(id).textContent = '—';
    });
    return;
  }

  const { family, totals_by_owner, totals_by_category, mobilizable_by_liquidity } = syn;
  const owner = S.syntheseOwner;
  const isFamily = (owner === 'Famille');

  const kpi = isFamily
    ? { gross: family.gross, debt: family.debt, net: family.net,
        mob: Object.values(totals_by_owner).reduce((s, o) => s + o.mobilizable, 0) }
    : { gross: totals_by_owner[owner]?.gross      || 0,
        debt:  totals_by_owner[owner]?.debt       || 0,
        net:   totals_by_owner[owner]?.net        || 0,
        mob:   totals_by_owner[owner]?.mobilizable|| 0 };

  // Variation vs precedent + YoY (par owner si pas famille)
  const variation = isFamily ? syn.variation : syn.variation?.by_owner?.[owner];
  const yoyVariation = isFamily ? syn.yoy_variation : syn.yoy_variation?.by_owner?.[owner];
  // Un seul jeu de deltas, celui de la periode choisie dans l'en-tete. Afficher
  // variation ET variation annuelle cote a cote doublait la charge de lecture
  // sur chaque indicateur, pour une comparaison qu'on ne fait pas a chaque fois.
  // Sparklines : la tendance sous le chiffre. Series prises dans l'historique
  // deja charge, filtrees sur le titulaire courant comme le reste de la page.
  const serie = cle => (S.historique || []).map(h =>
    isFamily ? h[`family_${cle}`] : h.by_owner_detail?.[owner]?.[cle]);
  const dates = (S.historique || []).map(h => h.date);

  const macro = syn.totals_by_macro || {};
  const immoMacro = macro['Patrimoine immobilier'] || {};
  // Les sous-titres suivent le titulaire choisi, comme le chiffre qu'ils
  // qualifient (« dont 280 000 € d'immobilier »).
  const immo = isFamily ? (immoMacro.gross || 0)
                        : (immoMacro.by_owner?.[owner]?.gross || 0);

  const liqFiltered = isFamily
    ? (mobilizable_by_liquidity || {})
    : (() => {
        const pos = S.synthese._positions_cache?.[owner];
        if (!pos) return mobilizable_by_liquidity || {};
        const byLiq = {};
        for (const p of pos) byLiq[p.liquidity] = (byLiq[p.liquidity] || 0) + (p.mobilizable_value || 0);
        return byLiq;
      })();

  // Chiffres de tete, Repartition et Vos comptes : ecrans Svelte
  // (frontend/src/synthese/), montes dans leurs elements.
  _cartesSvelte({
    chiffres: { kpi, owner, famille: isFamily, date: S.syntheseDate, variation: variation || null,
                variationAn: yoyVariation || null, surAn: S.periodeComparaison === 'an',
                series: { net: serie('net'), gross: serie('gross'), debt: serie('debt'), mob: serie('mob') },
                dates, objectif: _wealthTarget, immo, court: liqFiltered['J0–J1'] || 0 },
    repartition: { synthese: syn, owner, masque: isMasked() },
    comptes: { owner, date: S.syntheseDate },
    cache,
  });

  renderEntityWarnings(syn.entity_warnings || [], { cache });
  const posTitulaire = isFamily ? Object.values(S.synthese._positions_cache || {}).flat()
                                : (S.synthese._positions_cache?.[owner] || []);
  _cartes3b({ liqFiltered, posTitulaire, owner, syn });
  _projectionSvelte({ positions: posTitulaire, famille: isFamily, net: kpi.net, objectif: _wealthTarget,
                     masque: isMasked() });
  appliquerDisposition();
}

export async function loadHistorique() {
  S.historique = await api('GET', '/api/historique');
  if (S.currentTab === 'synthese') _evolutionSvelte();
}




/** Un pourcentage de controle : entier s'il l'est, une decimale sinon —
 *  100,5 % de detention ne doit pas s'arrondir a 101 %. */
const _pctControle = v => fmtPct(v, Number.isInteger(+v) ? 0 : 1);

function renderEntityWarnings(warnings, { cache = false } = {}) {
  // Ces avertissements ne s'affichent plus dans leur propre bandeau : ils
  // rejoignent la zone « À traiter », avec les signaux calcules en base. Un
  // probleme se lit au meme endroit quelle que soit son origine.
  const signaux = [
    ...warnings.map(w => ({
      cle: `entite-${w.entity}-${w.type}`,
      severite: 'warn',
      titre: w.type === 'debt'
        ? `${w.entity} : dette répartie à ${_pctControle(w.total_pct)}`
        : `${w.entity} : détention répartie à ${_pctControle(w.total_pct)}`,
      detail: w.type === 'debt'
        ? 'Double-comptage sur la dette'
        : 'Double-comptage probable de la détention',
      action: 'Ouvrir Entités',
      onglet: 'entites',
    })),
    ...evalUserAlerts(),
  ];
  document.getElementById('entity-warnings-bar').innerHTML = '';
  if (cache) renderTodo(signaux); else loadTodo(S.syntheseDate, signaux);
}

function evalUserAlerts() {
  const alerts = loadUserAlerts();
  if (!alerts.length || !S.synthese) return [];
  const syn   = S.synthese;
  const owner = S.syntheseOwner;
  const isFamily = owner === 'Famille';

  const family = syn.family || {};
  const byOwner = syn.totals_by_owner || {};
  const byCat   = syn.totals_by_category || {};

  const net   = isFamily ? (family.net   || 0) : (byOwner[owner]?.net   || 0);
  const gross = isFamily ? (family.gross || 0) : (byOwner[owner]?.gross || 0);

  // Le montant d'une categorie suit le titulaire, comme le net qui le divise :
  // sous un filtre, le pourcentage melangeait la famille et la personne.
  const netCat = cat => isFamily ? (byCat[cat]?.net || 0) : (byCat[cat]?.by_owner?.[owner] || 0);
  return alerts.map(a => {
    let actual = null;
    if (a.metric === 'cat_pct' && a.category) {
      actual = net > 0 ? (netCat(a.category) / net) * 100 : 0;
    } else if (a.metric === 'cat_abs' && a.category) {
      actual = netCat(a.category);
    } else if (a.metric === 'net')   actual = net;
    else if (a.metric === 'gross')   actual = gross;

    if (actual === null) return null;
    const triggered = a.op === '<' ? actual < a.threshold : actual > a.threshold;
    if (!triggered) return null;

    const fmtActual = a.metric.endsWith('pct') ? fmtPct(actual) : fmt(actual);
    const fmtThresh = a.metric.endsWith('pct') ? _pctControle(a.threshold) : fmt(a.threshold);
    return {
      cle: `seuil-${a.metric}-${a.category || ''}`,
      severite: 'info',
      titre: `${a.label || a.category || a.metric} : ${fmtActual}`,
      detail: `Seuil que vous avez défini : ${a.op === '<' ? 'moins de' : 'plus de'} ${fmtThresh}`,
      action: null, onglet: null,
    };
  }).filter(Boolean);
}

// ─── Snapshot notes ──────────────────────────────────────────────────────

/** Menu de l'arrete : « Note de l'arrete » et « Objectif de patrimoine ».
 *  Cables une fois au demarrage — poses dans renderSynthese, ils restaient
 *  sans effet tant que la synthese n'avait pas ete ouverte. L'arrete et la
 *  note se lisent au moment du clic. */
export function wireSyntheseMenu() {
  document.getElementById('btn-add-snapshot-note')?.addEventListener('click', async () => {
    const date = S.syntheseDate || S.dates?.[0];
    if (!date) { toast('Aucun arrêté : créez-en un d’abord', 'error'); return; }
    let note = S.synthese?.date === date ? (S.synthese.snapshot_note || '') : null;
    if (note === null) {
      try { note = (await api('GET', `/api/snapshot-notes?date=${encodeURIComponent(date)}`))?.notes || ''; }
      catch { return; }
    }
    openSnapshotNoteEditor(date, note);
  });
  document.getElementById('btn-open-wealth-target')?.addEventListener('click', async () => {
    if (!_wealthTargetCharge) await loadWealthTarget();
    openWealthTargetEditor();
  });
}

async function openSnapshotNoteEditor(date, currentNote) {
  const note = await promptDialog(`Note de l’arrêté du ${fmtDate(date)}`, {
    defaultValue: currentNote || '', placeholder: 'Ex: achat RP, krach mars 2025…', confirmText: 'Enregistrer'
  });
  if (note === null) return; // cancelled
  await api('PUT', '/api/snapshot-notes', { date, notes: note });
  if (S.synthese?.date === date) {
    S.synthese.snapshot_note = note || null;
    _noteSvelte(S.synthese);
  }
  toast(note ? 'Note enregistrée' : 'Note supprimée');
}

// ─── Wealth target gauge ─────────────────────────────────────────────────

let _wealthTarget = null;
let _wealthTargetCharge = false;

export async function loadWealthTarget() {
  try {
    const data = await api('GET', '/api/wealth-target');
    _wealthTarget = data?.target || null;
    _wealthTargetCharge = true;
  } catch { _wealthTarget = null; }
}

async function openWealthTargetEditor() {
  const current = _wealthTarget ? String(_wealthTarget) : '';
  const val = await promptDialog('Objectif patrimoine net (€)', {
    defaultValue: current, placeholder: 'Laisser vide pour supprimer', confirmText: 'Enregistrer'
  });
  if (val === null) return;
  const target = val.trim() ? parseLocaleNumber(val) : null;
  if (val.trim() && (isNaN(target) || target <= 0)) { toast('Montant invalide', 'error'); return; }
  await api('PUT', '/api/wealth-target', { target });
  _wealthTarget = target;
  if (S.synthese) renderSynthese({ cache: true });
  toast(target ? 'Objectif enregistré' : 'Objectif supprimé');
}
