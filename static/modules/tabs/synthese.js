import { S } from '../state.js';
import { natureDe } from '../categories.js';
import { dessinerCourbe } from '../courbe.js';
import { fmt, fmtDate, esc, parseLocaleNumber, sparkline, fmtPct } from '../utils.js';
import { api } from '../api.js';
import { loadTodo, renderTodo } from '../todo.js';
import { drilldownPositions } from '../drilldown.js';
import { loadUserAlerts } from '../alerts.js';
import { renderAllocationTargets } from '../targets.js';
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
    if (_argsObjectif) renderWealthTarget(..._argsObjectif);
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
                dates, objectif: !!_wealthTarget, immo, court: liqFiltered['J0–J1'] || 0 },
    repartition: { synthese: syn, owner, masque: isMasked() },
    comptes: { owner, date: S.syntheseDate },
    cache,
  });

  renderEntityWarnings(syn.entity_warnings || [], { cache });
  renderHistChart({ cache });
  renderSyntheseHistory({ cache });
  const posTitulaire = isFamily ? Object.values(S.synthese._positions_cache || {}).flat()
                                : (S.synthese._positions_cache?.[owner] || []);
  renderLiqBars(liqFiltered, posTitulaire);
  renderEntitiesSynthese();
  renderAllocationTargets();
  renderSnapshotDiff(owner, isFamily, { cache });
  renderSnapshotNote(syn);
  _argsObjectif = [kpi.net, isFamily, serie('net'), dates];
  renderWealthTarget(..._argsObjectif);
  _projectionSvelte({ positions: posTitulaire, famille: isFamily, net: kpi.net, objectif: _wealthTarget,
                     masque: isMasked() });
  appliquerDisposition();
}

/** « Evolution par categorie » : une ligne par groupe — nom, tendance,
 *  valeur, variation. Sept aires empilees ne se lisaient pas : l'epaisseur
 *  d'une bande qui flotte sur les autres ne se mesure pas a l'oeil, et une
 *  poche de 5 % n'y etait qu'un lisere. Ici chaque ligne a son echelle, et
 *  les chiffres se lisent sans survol. */
let _jetonHistoire = 0;
let _histoireCache = null;

export async function renderSyntheseHistory(opts) {
  const cache = !!(opts && opts.cache === true);
  const card = document.getElementById('synthese-history-detail-card');
  const hote = document.getElementById('evolution-groupes');
  if (!card || !hote) return;
  if (S.historique.length < 2) { card.style.display = 'none'; return; }
  card.style.display = '';

  const groupBy = document.getElementById('synthese-history-group').value;
  const owner   = S.syntheseOwner === 'Famille' ? null : S.syntheseOwner;
  const url     = `/api/historique?group_by=${groupBy}${owner ? `&owner=${encodeURIComponent(owner)}` : ''}`;
  // Changer vite de titulaire ou de regroupement : seule la derniere ecrit.
  const jeton = ++_jetonHistoire;
  let history;
  if (cache && _histoireCache?.url === url) history = _histoireCache.history;
  else {
    history = await api('GET', url);
    if (jeton !== _jetonHistoire) return;
    _histoireCache = { url, history };
  }
  if (history.length < 2) { card.style.display = 'none'; return; }

  const d0 = history[0].date, d1 = history[history.length - 1].date;
  const groupes = [...new Set(history.flatMap(h => Object.keys(h.by_group || {})))];
  const lignes = groupes.map(g => {
    const serie = history.map(h => h.by_group?.[g] || 0);
    const debut = serie[0], fin = serie[serie.length - 1];
    return { g, serie, debut, fin, delta: fin - debut };
  }).filter(l => l.serie.some(v => Math.abs(v) >= 1))
    .sort((a, b) => Math.abs(b.fin) - Math.abs(a.fin));
  const totalFin = lignes.reduce((t, l) => t + Math.max(0, l.fin), 0);

  const sous = document.getElementById('evolution-groupes-sous');
  if (sous) sous.textContent = `Du ${fmtDate(d0)} au ${fmtDate(d1)} · une ligne ouvre sa composition`;
  hote.innerHTML = lignes.map(l => {
    const pct = l.debut ? (l.delta / Math.abs(l.debut)) * 100 : null;
    const sens = Math.abs(l.delta) < 1 ? 'evg-stable' : l.delta > 0 ? 'pos' : 'neg';
    const part = totalFin > 0 && l.fin > 0 ? fmtPct(l.fin / totalFin * 100, 0) : '';
    return `<button type="button" class="evg-ligne" data-groupe="${esc(l.g)}">
      <span class="evg-nom">${esc(l.g)}${part ? `<span class="evg-part">${part}</span>` : ''}</span>
      <span class="evg-spark">${sparkline(l.serie, { couleur: l.delta < 0 ? 'var(--danger)' : 'var(--primary)', dates: history.map(h => h.date) })}</span>
      <span class="evg-valeur">${fmt(l.fin)}</span>
      <span class="evg-delta ${sens}">${Math.abs(l.delta) < 1 ? 'stable'
        : `${l.delta > 0 ? '+' : '−'}${fmt(Math.abs(l.delta))}${pct != null && isFinite(pct) ? `<small>${fmtPct(pct, 1, true)}</small>` : ''}`}</span>
    </button>`;
  }).join('');

  hote.onclick = e => {
    const b = e.target.closest('.evg-ligne');
    if (!b) return;
    const group = b.dataset.groupe;
    api('GET', `/api/positions?date=${d1}`).then(positions => {
      let filtered = owner ? positions.filter(p => p.owner === owner) : positions;
      if (groupBy === 'category')      filtered = filtered.filter(p => p.category === group);
      else if (groupBy === 'envelope')  filtered = filtered.filter(p => (p.envelope || 'Autre') === group);
      drilldownPositions(filtered, `${group} — ${fmtDate(d1)}`, `Évolution par ${groupBy === 'category' ? 'catégorie' : 'enveloppe'}`, { showOwner: !owner });
    });
  };
}

export async function loadHistorique() {
  S.historique = await api('GET', '/api/historique');
  if (S.currentTab === 'synthese') renderHistChart();
}



/** « Evolution du patrimoine net » : la courbe du titulaire choisi, et sous
 *  elle ce qui explique la variation — l'epargne versee, puis l'effet des
 *  marches. Comparer ce patrimoine a un indice serait trompeur : il grossit
 *  aussi de ce qu'on y verse. La comparaison a un ETF vit dans Performance,
 *  ou le TWR neutralise les versements.
 *
 *  Le titulaire se lit dans S : appelee sans argument apres un rechargement
 *  de l'historique, l'ancienne version revenait a la famille sous un filtre
 *  nominatif. */
function renderHistChart({ cache = false } = {}) {
  const hote = document.getElementById('evolution-courbe');
  if (!hote || !S.historique.length) return;
  const owner = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : null;
  const points = S.historique.map(h => ({
    date: h.date, v: owner ? (h.by_owner?.[owner] || 0) : h.family_net,
  }));
  const qui = owner || 'Famille';
  const debut = points[0], fin = points[points.length - 1];
  dessinerCourbe(hote, {
    series: [{ nom: `Patrimoine net — ${qui}`, couleur: 'var(--primary)', points, aire: true }],
    formatV: v => fmt(v),
    aide: `Patrimoine net ${qui} : ${fmt(debut.v)} le ${fmtDate(debut.date)}, ${fmt(fin.v)} le ${fmtDate(fin.date)}.`,
    onPoint: date => api('GET', `/api/positions?date=${date}`).then(positions => {
      const lignes = owner ? positions.filter(p => p.owner === owner) : positions;
      drilldownPositions(lignes, `${qui} — ${fmtDate(date)}`, 'Composition à cette date', { showOwner: !owner });
    }),
  });
  const sous = document.getElementById('evolution-sous');
  if (sous) sous.textContent = `${points.length} arrêtés · du ${fmtDate(debut.date)} au ${fmtDate(fin.date)}`;
  _legendeEvolution(owner, debut, fin, { cache });
}

let _legendeJeton = 0;
let _legendeRequete = null;
async function _legendeEvolution(owner, debut, fin, { cache = false } = {}) {
  const hote = document.getElementById('evolution-legende');
  if (!hote) return;
  // Changer vite de titulaire lance deux requetes : seule la derniere ecrit.
  const jeton = ++_legendeJeton;
  const variation = fin.v - debut.v;
  const pct = debut.v ? variation / Math.abs(debut.v) * 100 : null;
  let decompo = '';
  try {
    const q = new URLSearchParams({ limit: '40' });
    if (owner) q.set('owner', owner);
    // La courbe se dessine deux fois au chargement — apres la synthese, puis
    // apres l'historique, qui arrivent dans un ordre variable. La meme
    // decomposition, demandee a quelques millisecondes d'intervalle, est
    // partagee plutot que redemandee.
    const cle = `${q}|${debut.date}|${fin.date}`;
    const perimee = !cache && Date.now() - (_legendeRequete?.t || 0) > 2000;
    if (!_legendeRequete || _legendeRequete.cle !== cle || perimee) {
      _legendeRequete = { cle, t: Date.now(), p: api('GET', `/api/contribution?${q}`, null, { silent: true }) };
    }
    const d = await _legendeRequete.p;
    if (jeton !== _legendeJeton) return;
    // L'epargne, le capital et les marches expliquent la variation seulement
    // s'ils couvrent la meme periode : au-dela de 40 arretes, le serveur
    // tronque, et les chiffres ne s'additionneraient plus.
    const du = d.periodes?.[0]?.debut, au = d.periodes?.[d.periodes.length - 1]?.fin;
    if (d.periodes?.length && du === debut.date && au === fin.date) {
      decompo = `<span><i style="background:var(--chart-4)"></i>Épargne nouvelle <b>${fmtSigne(d.total_epargne)}</b></span>`
              + (Math.abs(d.total_capital || 0) >= 1
                  ? `<span><i style="background:var(--chart-2)"></i>Capital remboursé <b>${fmtSigne(d.total_capital)}</b></span>` : '')
              + `<span><i style="background:var(--chart-1)"></i>Marchés <b>${fmtSigne(d.total_performance)}</b></span>`
              + (Math.abs(d.total_hors_suivi || 0) >= 1
                  ? `<span><i style="background:var(--text-muted)"></i>Comptes ajoutés ou retirés <b>${fmtSigne(d.total_hors_suivi)}</b></span>` : '');
    }
  } catch { /* la decomposition est un plus : sans elle, la courbe reste lisible */ }
  if (jeton !== _legendeJeton) return;
  hote.innerHTML = `
    <span>Variation <b>${fmtSigne(variation)}</b>${
      pct != null ? ` <b>${fmtPct(pct, 1, true)}</b>` : ''}</span>
    ${decompo}
    <span class="courbe-note">Chaque arrêté ouvre sa composition</span>`;
}

const fmtSigne = v => `${v >= 0 ? '+' : '−'}${fmt(Math.abs(v))}`;

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

function renderEntitiesSynthese() {
  const card = document.getElementById('entities-synthese-card');
  if (!S.entities.length) { card.style.display = 'none'; return; }
  card.style.display = '';

  const owner    = S.syntheseOwner;
  const isFamily = owner === 'Famille';
  const cache    = S.synthese?._positions_cache || {};

  const allPositions = Object.values(cache).flat();

  // Vue d'un titulaire : ses seules entites. Lister les autres a « 0 € 0 % »
  // n'apprenait rien.
  const entites = isFamily ? S.entities
    : S.entities.filter(e => allPositions.some(p => p.entity === e.name && p.owner === owner));
  if (!entites.length) { card.style.display = 'none'; return; }
  const rows = entites.map(e => {
    const linked = allPositions.filter(p => p.entity === e.name);
    const familyNet  = linked.reduce((s, p) => s + (p.net_attributed || 0), 0);
    const familyGross= linked.reduce((s, p) => s + (p.gross_attributed || 0), 0);
    const familyDebt = linked.reduce((s, p) => s + (p.debt_attributed || 0), 0);
    const familyPct  = e.gross_assets > 0 ? fmtPct(familyGross / e.gross_assets * 100, 0) : '—';

    const ownerNet   = !isFamily
      ? linked.filter(p => p.owner === owner).reduce((s, p) => s + (p.net_attributed || 0), 0)
      : null;
    const siennes    = linked.filter(p => p.owner === owner);
    const ownerPct   = !isFamily && e.gross_assets > 0
      ? siennes.reduce((s, p) => s + (p.ownership_pct || 0), 0) : null;
    // Le net suit aussi la part de DETTE, qui peut differer de la propriete :
    // la dire, sinon « 50 % » ne colle pas au montant.
    const ownerDebtPct = !isFamily && e.debt > 0
      ? siennes.reduce((s, p) => s + (p.debt_pct ?? p.ownership_pct ?? 0), 0) : null;

    return { e, familyGross, familyDebt, familyNet, familyPct, ownerNet, ownerPct, ownerDebtPct };
  });

  const personCol = !isFamily
    ? `<th style="text-align:right">${esc(owner)}</th>` : '';

  document.getElementById('entities-synthese').innerHTML = `
    <table class="owners-table">
      <thead><tr>
        <th>Entité</th>
        <th>Type</th>
        <th style="text-align:right">Actif brut total</th>
        <th style="text-align:right">Dette totale</th>
        <th style="text-align:right">Net total</th>
        <th style="text-align:right">Quote-part famille</th>
        ${personCol}
      </tr></thead>
      <tbody>${rows.map(({ e, familyGross, familyDebt, familyNet, familyPct, ownerNet, ownerPct, ownerDebtPct }) => `
        <tr>
          <td><strong>${esc(e.name)}</strong></td>
          <td>${esc(e.type || '—')}</td>
          <td style="text-align:right">${fmt(e.gross_assets)}</td>
          <td style="text-align:right">${e.debt > 0 ? fmt(e.debt) : '—'}</td>
          <td style="text-align:right;font-weight:600" class="${e.net_assets >= 0 ? 'pos' : 'neg'}">${fmt(e.net_assets)}</td>
          <td style="text-align:right">
            ${fmt(familyNet)}
            <span style="font-size:11px;color:var(--text-muted);margin-left:4px">${familyPct !== '—' ? familyPct : ''}</span>
          </td>
          ${!isFamily ? `<td style="text-align:right;font-weight:700;color:var(--primary)">
            ${fmt(ownerNet)}
            ${ownerPct !== null ? `<span style="font-size:11px;color:var(--text-muted);margin-left:4px">${fmtPct(ownerPct * 100, 0)}${
              ownerDebtPct !== null && Math.abs(ownerDebtPct - ownerPct) > 0.005 ? ` du bien, ${fmtPct(ownerDebtPct * 100, 0)} de la dette` : ''}</span>` : ''}
          </td>` : ''}
        </tr>`).join('')}
      </tbody>
    </table>`;
}

/** « Si vous aviez besoin d'argent » : ce qui est disponible, par delai.
 *
 *  Les montants sont CUMULES : sous une semaine, on dispose aussi de ce qui
 *  etait deja mobilisable sous 24 h. Afficher des tranches disjointes obligeait
 *  a les additionner de tete pour repondre a la seule question qui compte —
 *  « de combien je dispose d'ici la ? ».
 */
function renderLiqBars(byLiq, positions = []) {
  // Trois delais cumules, puis ce qui ne se mobilise pas. La ligne « Au-dela »
  // repetait le cumul du mois — rien n'est classe au-dela — et n'apprenait
  // rien ; la question utile est l'inverse : combien reste immobilise.
  const DELAIS = [
    { cles: ['J0–J1'], libelle: 'Sous 24 heures' },
    { cles: ['J0–J1', 'J2–J7'], libelle: 'Sous une semaine' },
    { cles: ['J0–J1', 'J2–J7', 'J8–J30'], libelle: 'Sous un mois' },
  ];
  if (byLiq['30J+']) DELAIS.push({ cles: ['J0–J1', 'J2–J7', 'J8–J30', '30J+'], libelle: 'Au-delà d’un mois' });
  const cumule = d => d.cles.reduce((s, k) => s + (byLiq[k] || 0), 0);
  const mobilisable = ['J0–J1', 'J2–J7', 'J8–J30', '30J+'].reduce((s, k) => s + (byLiq[k] || 0), 0);
  // « Bloque » = le FINANCIER qui ne se mobilise pas : PER, contrat nanti,
  // epargne bloquee, decote de sortie. L'immobilier et les biens n'y sont pas —
  // on ne les mobilise pas en un mois, cela va sans dire — et y compter la
  // residence principale noyait les 30 000 € d'un PER dans 700 000 €.
  const financier = positions.filter(p => ['liq', 'fin'].includes(natureDe(p.category, p.envelope)));
  const bloque = financier.reduce((s, p) => s + Math.max(0, (p.net_attributed || 0) - (p.mobilizable_value || 0)), 0);
  const horsFinancier = positions.filter(p => !financier.includes(p))
    .reduce((s, p) => s + (p.net_attributed || 0), 0);
  const base = Math.max(mobilisable + bloque, 1);

  const ligne = (libelle, valeur, couleur, cls = '') => `
    <div class="dispo-ligne ${cls}">
      <span class="dispo-n">${libelle}</span>
      <span class="dispo-v">${fmt(valeur)}</span>
      <span class="dispo-track"><span class="dispo-fill"
            style="width:${Math.min(100, (valeur / base) * 100).toFixed(1)}%;background:${couleur}"></span></span>
    </div>`;

  document.getElementById('liquidity-bars').innerHTML = `
    <div class="dispo">
      ${DELAIS.map(d => ligne(d.libelle, cumule(d), 'var(--chart-1)')).join('')}
      ${bloque >= 1 ? ligne('Ce qui reste bloqué', bloque, 'var(--text-muted)', 'dispo-bloque') : ''}
    </div>
    ${mobilisable || bloque ? `<p class="dispo-note">Délais cumulés : chaque ligne inclut la précédente.
      « Bloqué » : le patrimoine financier qui ne se mobilise pas — épargne retraite, contrat nanti,
      décote de sortie.${Math.abs(horsFinancier) >= 1 ? ` Immobilier, biens et sociétés, hors de ce décompte :
      ${fmt(horsFinancier)} de net.` : ''}</p>` : ''}`;
}

let _jetonDiff = 0;
let _diffCache = null;

async function renderSnapshotDiff(owner, isFamily, { cache = false } = {}) {
  const el = document.getElementById('snapshot-diff');
  if (!el) return;
  const params = new URLSearchParams({ date: S.syntheseDate || '' });
  if (!isFamily && owner) params.set('owner', owner);
  const cle = String(params);
  const jeton = ++_jetonDiff;
  let data;
  if (cache && _diffCache?.cle === cle) data = _diffCache.data;
  else {
    try { data = await api('GET', `/api/snapshot-diff?${params}`, null, { silent: true }); }
    catch { if (jeton === _jetonDiff) el.innerHTML = ''; return; }
    if (jeton !== _jetonDiff) return;
    _diffCache = { cle, data };
  }
  if (!data || !data.from_date) {
    el.innerHTML = '<p class="text-muted" style="font-size:13px">Aucun arrêté précédent à comparer.</p>';
    return;
  }
  const moves = (data.movements || []).filter(m => Math.abs(m.delta) >= 1 || m.status !== 'changed');
  if (!moves.length) {
    el.innerHTML = `<p class="text-muted" style="font-size:13px">Aucun mouvement depuis le ${fmtDate(data.from_date)}.</p>`;
    return;
  }
  const t = data.totals || {};
  const badge = s => s === 'new' ? ' <span class="h-badge h-badge-fresh">nouveau</span>'
    : s === 'closed' ? ' <span class="h-badge h-badge-expired">clôturé</span>' : '';
  // On lit un compte puis son chiffre, comme partout ailleurs : libelle a
  // gauche, montant a droite, aligne en colonne.
  const VISIBLES = 6;
  const ligne = (m, i) => `
        <div class="mv-item"${i >= VISIBLES ? ' data-mv-reste hidden' : ''}>
          <button type="button" class="mv-ligne" aria-expanded="false">
            <span class="mv-ou">${esc(m.label || '—')}${badge(m.status)}</span>
            <span class="mv-montant ${m.delta >= 0 ? 'pos' : 'neg'}">${
              m.delta >= 0 ? '+' : '−'}${fmt(Math.abs(m.delta))}</span>
            <span class="mv-qui">${esc([m.owner, m.establishment].filter(Boolean).join(' · '))}</span>
          </button>
          <p class="mv-detail" hidden>${
            m.status === 'new' ? `Ouvert depuis le ${fmtDate(data.from_date)} : ${fmt(m.net_after)} au ${fmtDate(data.to_date)}`
            : m.status === 'closed' ? `${fmt(m.net_before)} au ${fmtDate(data.from_date)}, absent au ${fmtDate(data.to_date)}`
            : `${fmt(m.net_before)} au ${fmtDate(data.from_date)} → ${fmt(m.net_after)} au ${fmtDate(data.to_date)}${
                m.net_before ? ` (${fmtPct((m.net_after / m.net_before - 1) * 100, 1, true)})` : ''}`}</p>
        </div>`;
  el.innerHTML = `
    <p class="mv-total">Variation nette
      <b class="${(t.delta || 0) >= 0 ? 'pos' : 'neg'}">${(t.delta || 0) >= 0 ? '+' : ''}${
        fmt(t.delta || 0)}</b> depuis le ${fmtDate(data.from_date)}</p>
    <div class="mv-liste">${moves.map(ligne).join('')}</div>
    ${moves.length > VISIBLES ? `<button type="button" class="btn-link mv-plus" aria-expanded="false">
      Voir les ${moves.length - VISIBLES} autres comptes</button>` : ''}`;
  // L'avant et l'apres ne sont plus affiches d'office : ils se deplient au
  // clic, a l'ecran, plutot que de dormir dans une infobulle.
  el.onclick = e => {
    const b = e.target.closest('.mv-ligne');
    if (b) {
      const ouvert = b.getAttribute('aria-expanded') === 'true';
      b.setAttribute('aria-expanded', String(!ouvert));
      b.nextElementSibling.hidden = ouvert;
      return;
    }
    const plus = e.target.closest('.mv-plus');
    if (plus) {
      const ouvert = plus.getAttribute('aria-expanded') === 'true';
      el.querySelectorAll('[data-mv-reste]').forEach(x => { x.hidden = ouvert; });
      plus.setAttribute('aria-expanded', String(!ouvert));
      plus.textContent = ouvert ? `Voir les ${moves.length - VISIBLES} autres comptes` : 'Réduire';
    }
  };
}

// ─── Snapshot notes ──────────────────────────────────────────────────────

function renderSnapshotNote(syn) {
  const bar = document.getElementById('snapshot-note-bar');
  if (!bar) return;
  const note = syn.snapshot_note;
  const date = syn.date;

  if (!note) {
    bar.style.display = 'none';
    bar.innerHTML = '';
  } else {
    bar.style.display = '';
    bar.innerHTML = `<div class="snapshot-note">
      <span class="snapshot-note-icon">Note</span>
      <span class="snapshot-note-text">${esc(note)}</span>
      <button type="button" class="btn-link" id="btn-edit-snapshot-note"
              aria-label="Modifier la note de l’arrêté">Modifier</button>
    </div>`;
    bar.querySelector('#btn-edit-snapshot-note')?.addEventListener('click', () => openSnapshotNoteEditor(date, note));
  }
}

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
    renderSnapshotNote(S.synthese);
  }
  toast(note ? 'Note enregistrée' : 'Note supprimée');
}

// ─── Wealth target gauge ─────────────────────────────────────────────────

let _wealthTarget = null;
let _wealthTargetCharge = false;
// Derniers arguments de renderWealthTarget : l'objectif modifie se redessine
// pour le titulaire affiche, pas pour la famille par defaut.
let _argsObjectif = null;

export async function loadWealthTarget() {
  try {
    const data = await api('GET', '/api/wealth-target');
    _wealthTarget = data?.target || null;
    _wealthTargetCharge = true;
  } catch { _wealthTarget = null; }
}

/** « 12 j », « 3 mois », « 1 an » : la duree qui separe deux arretes. */
function renderWealthTarget(currentNet, isFamily = true, valeurs = [], dates = []) {
  const bar = document.getElementById('wealth-target-bar');
  if (!bar) return;

  const hoteBut = document.getElementById('kpi-hero-goal');
  // L'objectif vise le patrimoine de la famille : sous un titulaire, la jauge
  // melangeait son net a la progression de la famille.
  if (!_wealthTarget || !isFamily) {
    bar.style.display = 'none';
    bar.innerHTML = '';
    if (hoteBut) { hoteBut.innerHTML = ''; hoteBut.className = ''; }
    return;
  }

  const target = _wealthTarget;
  const pct = target > 0 ? Math.min((currentNet / target) * 100, 100) : 0;
  const cls = pct >= 100 ? 'pos' : '';

  bar.style.display = '';
  // L'objectif rejoint le chiffre qu'il vise : une trajectoire n'a de sens
  // qu'accolee au montant qu'elle projette, pas dans un bandeau separe en haut
  // de page. Le bandeau disparait donc, la jauge vit dans le heros.
  bar.style.display = 'none';
  bar.innerHTML = '';

  const hote = document.getElementById('kpi-hero-goal');
  if (!hote) return;

  // Rythme observe sur l'historique : de quoi dire QUAND l'objectif tombe, et
  // pas seulement ou l'on en est.
  let projection = '';
  if (valeurs.length >= 2 && currentNet < target) {
    const jours = (Date.parse(dates[dates.length - 1]) - Date.parse(dates[0])) / 864e5;
    const progression = (valeurs[valeurs.length - 1] || 0) - (valeurs[0] || 0);
    if (jours > 30 && progression > 0) {
      const restant = (target - currentNet) / (progression / jours);
      if (restant < 3650) {
        const quand = new Date(Date.now() + restant * 864e5);
        const opts = quand.getFullYear() === new Date().getFullYear()
          ? { day: 'numeric', month: 'short' } : { month: 'short', year: 'numeric' };
        projection = `Atteint le <b>${quand.toLocaleDateString('fr-FR', opts)}</b> au rythme actuel`;
        if (!opts.day) projection = projection.replace('Atteint le', 'Atteint en');
      }
    }
  } else if (currentNet >= target) {
    projection = '<b>Objectif atteint</b>';
  }

  hote.className = 'hero-goal';
  hote.innerHTML = `
    <div class="g-track"><span class="g-fill" style="width:${pct.toFixed(1)}%"></span></div>
    <div class="g-foot">
      <span>Objectif <b>${fmt(target)}</b></span>
      <span>${projection || `Reste <b>${fmt(Math.max(target - currentNet, 0))}</b>`}</span>
    </div>`;
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
  if (_argsObjectif && S.synthese) renderWealthTarget(..._argsObjectif);
  toast(target ? 'Objectif enregistré' : 'Objectif supprimé');
}
