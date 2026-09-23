import { S } from '../state.js';
import { natureDe } from '../categories.js';
import { dessinerCourbe } from '../courbe.js';
import { fmt, fmtDate, esc, kpiDelta, parseLocaleNumber, sparkline, fmtPct } from '../utils.js';
import { api } from '../api.js';
import { loadTodo } from '../todo.js';
import { loadContribution } from './contribution.js';
import { renderRepartition } from './repartition.js';
import { loadComptes } from './comptes.js';
import { loadFiscalite } from './fiscalite.js';
import { drilldownPositions } from '../drilldown.js';
import { loadUserAlerts } from '../alerts.js';
import { renderAllocationTargets } from '../targets.js';
import { toast, promptDialog } from '../dialogs.js';

function _owners() {
  return S.synthese?._owners || S.config.owners;
}

export async function loadSynthese() {
  if (!S.syntheseDate && S.dates.length) S.syntheseDate = S.dates[0];
  if (!S.syntheseDate) {
    _renderSyntheseEmpty();
    return;
  }
  _clearSyntheseEmpty();
  const [syn, positions] = await Promise.all([
    api('GET', `/api/synthese?date=${S.syntheseDate}`),
    api('GET', `/api/positions?date=${S.syntheseDate}`),
    loadWealthTarget(),
  ]);
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
      <div style="font-size:32px;margin-bottom:.5rem;opacity:.5">&#128202;</div>
      <h2 style="margin-bottom:.5rem">Aucun snapshot pour le moment</h2>
      <p class="text-muted" style="font-size:13.5px;margin-bottom:1.25rem;line-height:1.6">
        Commence par ajouter une position ou importer un fichier existant
        pour que ton patrimoine s'affiche ici.
      </p>
      <div style="display:flex;gap:.5rem;justify-content:center;flex-wrap:wrap">
        <button class="btn btn-primary" data-tab-switch="positions">+ Ajouter une position</button>
        <button class="btn btn-secondary" data-tab-switch="import">&#8645; Importer des données</button>
      </div>
    </div>`;
  host.querySelector('.page-header')?.after(card);
  // Delegue au listener global (main.js) qui appelle switchTab
}

function _clearSyntheseEmpty() {
  const host = document.getElementById('tab-synthese');
  host?.querySelector('.empty-state-synthese')?.remove();
  host?.querySelectorAll('.kpi-grid, .charts-row, .card').forEach(el => el.classList.remove('hidden'));
}

export function renderSynthese() {
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
  const varHtml = (field, pctField, opts) => {
    const surAn = S.periodeComparaison === 'an';
    const source = surAn ? yoyVariation : variation;
    if (!source) return '';
    return kpiDelta(source, field, pctField, { ...opts, label: surAn ? 'sur 1 an' : null });
  };
  // Sparklines : la tendance sous le chiffre. Series prises dans l'historique
  // deja charge, filtrees sur le titulaire courant comme le reste de la page.
  const serie = cle => (S.historique || []).map(h =>
    isFamily ? h[`family_${cle}`] : h.by_owner_detail?.[owner]?.[cle]);
  const dates = (S.historique || []).map(h => h.date);

  // Le heros, au dessin de la maquette : le net, deux pastilles (depuis le
  // dernier arrete, et sur un an — ou depuis le debut tant qu'un an manque),
  // puis l'objectif s'il existe, sinon la tendance.
  document.getElementById('kpi-net').innerHTML = fmt(kpi.net)
    + _pastillesHeros(kpi.net, variation, serie('net'), dates);
  document.getElementById('kpi-hero-spark').innerHTML =
    (isFamily && _wealthTarget) ? '' : sparkline(serie('net'), { couleur: 'var(--primary)', dates });
  document.getElementById('kpi-gross').innerHTML       = fmt(kpi.gross) + varHtml('gross_delta')
    + sparkline(serie('gross'), { couleur: 'var(--primary)', dates });
  // La dette prend une couleur neutre : elle n'est ni bonne ni mauvaise en soi,
  // et la teindre en rouge ferait lire une baisse comme un probleme.
  document.getElementById('kpi-debt').innerHTML        = fmt(kpi.debt) + varHtml('debt_delta', null, { invert: true })
    + sparkline(serie('debt'), { couleur: 'var(--text-muted)', dates });
  document.getElementById('kpi-mobilizable').innerHTML = fmt(kpi.mob) + varHtml('mob_delta')
    + sparkline(serie('mob'), { couleur: 'var(--primary)', dates });

  // Sous-titres : un montant seul ne se situe pas. « 530 000 € » ne dit pas
  // ce qu'il contient ; « dont 280 000 € d'immobilier » le qualifie d'un mot.
  // Ces deux valeurs suivent le titulaire choisi, comme le chiffre qu'elles
  // qualifient. Les prendre au niveau famille faisait lire « dont 890 000 EUR
  // d'immobilier » sous des actifs bruts de 950 000 EUR pour une seule
  // personne — soit 94 %, alors que le montant etait celui des quatre.
  const macro = syn.totals_by_macro || {};
  const immoMacro = macro['Patrimoine immobilier'] || {};
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
  const court = liqFiltered['J0–J1'] || 0;
  const sous = (id, txt) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = txt;
  };
  sous('kpi-gross-sub', immo ? `dont ${fmt(immo)} d'immobilier` : '');
  sous('kpi-debt-sub', kpi.gross
    ? `${fmtPct(kpi.debt / kpi.gross * 100)} du brut`
    : '');
  sous('kpi-mob-sub', kpi.net
    ? `${fmtPct(kpi.mob / kpi.net * 100, 0)} du net`
      + (court ? ` · ${fmt(court)} sous 24\u202fh` : '')
    : '');

  document.getElementById('kpi-net-label').textContent   = isFamily ? 'Patrimoine net famille' : `Patrimoine net — ${owner}`;
  document.getElementById('kpi-gross-label').textContent = isFamily ? 'Actifs bruts' : `Actifs bruts — ${owner}`;
  document.getElementById('kpi-debt-label').textContent  = isFamily ? 'Dettes' : `Dettes — ${owner}`;
  document.getElementById('kpi-mob-label').textContent   = isFamily ? 'Mobilisable' : `Mobilisable — ${owner}`;

  renderRepartition();
  loadContribution();
  loadComptes();
  loadFiscalite();
  renderEntityWarnings(syn.entity_warnings || []);
  renderHistChart();
  renderSyntheseHistory();
  const posTitulaire = isFamily ? Object.values(S.synthese._positions_cache || {}).flat()
                                : (S.synthese._positions_cache?.[owner] || []);
  renderLiqBars(liqFiltered, posTitulaire);
  renderEntitiesSynthese();
  renderAllocationTargets();
  renderSnapshotDiff(owner, isFamily);
  renderSnapshotNote(syn);
  renderWealthTarget(kpi.net, isFamily, serie('net'), dates);
}

/** « Evolution par categorie » : une ligne par groupe — nom, tendance,
 *  valeur, variation. Sept aires empilees ne se lisaient pas : l'epaisseur
 *  d'une bande qui flotte sur les autres ne se mesure pas a l'oeil, et une
 *  poche de 5 % n'y etait qu'un lisere. Ici chaque ligne a son echelle, et
 *  les chiffres se lisent sans survol. */
export async function renderSyntheseHistory() {
  const card = document.getElementById('synthese-history-detail-card');
  const hote = document.getElementById('evolution-groupes');
  if (!card || !hote) return;
  if (S.historique.length < 2) { card.style.display = 'none'; return; }
  card.style.display = '';

  const groupBy = document.getElementById('synthese-history-group').value;
  const owner   = S.syntheseOwner === 'Famille' ? null : S.syntheseOwner;
  const url     = `/api/historique?group_by=${groupBy}${owner ? `&owner=${encodeURIComponent(owner)}` : ''}`;
  const history = await api('GET', url);
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
function renderHistChart() {
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
  _legendeEvolution(owner, debut, fin);
}

let _legendeJeton = 0;
let _legendeRequete = null;
async function _legendeEvolution(owner, debut, fin) {
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
    if (!_legendeRequete || _legendeRequete.cle !== cle || Date.now() - _legendeRequete.t > 2000) {
      _legendeRequete = { cle, t: Date.now(), p: api('GET', `/api/contribution?${q}`, null, { silent: true }) };
    }
    const d = await _legendeRequete.p;
    if (jeton !== _legendeJeton) return;
    // L'epargne et les marches expliquent la variation seulement s'ils couvrent
    // la meme periode : au-dela de 40 arretes, le serveur tronque, et les
    // trois chiffres ne s'additionneraient plus.
    const du = d.periodes?.[0]?.debut, au = d.periodes?.[d.periodes.length - 1]?.fin;
    if (d.periodes?.length && du === debut.date && au === fin.date) {
      decompo = `<span><i style="background:var(--chart-4)"></i>Épargne versée <b>${fmtSigne(d.total_apports)}</b></span>`
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

function renderEntityWarnings(warnings) {
  // Ces avertissements ne s'affichent plus dans leur propre bandeau : ils
  // rejoignent la zone « À traiter », avec les signaux calcules en base. Un
  // probleme se lit au meme endroit quelle que soit son origine.
  const signaux = [
    ...warnings.map(w => ({
      cle: `entite-${w.entity}-${w.type}`,
      severite: 'warn',
      titre: w.type === 'debt'
        ? `${w.entity} : total % dette = ${w.total_pct} %`
        : `${w.entity} : total % détention = ${w.total_pct} %`,
      detail: w.type === 'debt'
        ? 'Double-comptage sur la dette'
        : 'Double-comptage probable de la détention',
      action: 'Ouvrir Entités',
      onglet: 'entites',
    })),
    ...evalUserAlerts(),
  ];
  document.getElementById('entity-warnings-bar').innerHTML = '';
  loadTodo(S.syntheseDate, signaux);
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
    const fmtThresh = a.metric.endsWith('pct') ? a.threshold + ' %' : fmt(a.threshold);
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

  const rows = S.entities.map(e => {
    const linked = allPositions.filter(p => p.entity === e.name);
    const familyNet  = linked.reduce((s, p) => s + (p.net_attributed || 0), 0);
    const familyGross= linked.reduce((s, p) => s + (p.gross_attributed || 0), 0);
    const familyDebt = linked.reduce((s, p) => s + (p.debt_attributed || 0), 0);
    const familyPct  = e.gross_assets > 0 ? fmtPct(familyGross / e.gross_assets * 100, 0) : '—';

    const ownerNet   = !isFamily
      ? linked.filter(p => p.owner === owner).reduce((s, p) => s + (p.net_attributed || 0), 0)
      : null;
    const ownerPct   = !isFamily && e.gross_assets > 0
      ? linked.filter(p => p.owner === owner).reduce((s, p) => s + (p.ownership_pct || 0), 0)
      : null;

    return { e, familyGross, familyDebt, familyNet, familyPct, ownerNet, ownerPct };
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
      <tbody>${rows.map(({ e, familyGross, familyDebt, familyNet, familyPct, ownerNet, ownerPct }) => `
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
            ${ownerPct !== null ? `<span style="font-size:11px;color:var(--text-muted);margin-left:4px">${fmtPct(ownerPct * 100, 0)}</span>` : ''}
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

async function renderSnapshotDiff(owner, isFamily) {
  const el = document.getElementById('snapshot-diff');
  if (!el) return;
  const params = new URLSearchParams({ date: S.syntheseDate || '' });
  if (!isFamily && owner) params.set('owner', owner);
  let data;
  try { data = await api('GET', `/api/snapshot-diff?${params}`, null, { silent: true }); }
  catch { el.innerHTML = ''; return; }
  if (!data || !data.from_date) {
    el.innerHTML = '<p class="text-muted" style="font-size:13px">Aucun snapshot précédent à comparer.</p>';
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
      <span class="snapshot-note-icon">&#128221;</span>
      <span class="snapshot-note-text">${esc(note)}</span>
      <button class="btn-icon" id="btn-edit-snapshot-note" title="Modifier la note">&#9998;</button>
    </div>`;
    bar.querySelector('#btn-edit-snapshot-note')?.addEventListener('click', () => openSnapshotNoteEditor(date, note));
  }

  let noteBtn = document.getElementById('btn-add-snapshot-note');
  if (noteBtn) {
    noteBtn.innerHTML = note ? '&#128221; Modifier la note' : '&#128221; Note du snapshot';
    noteBtn.onclick = () => openSnapshotNoteEditor(date, note || '');
  }
}

async function openSnapshotNoteEditor(date, currentNote) {
  const note = await promptDialog(`Note pour le snapshot du ${fmtDate(date)}`, {
    defaultValue: currentNote || '', placeholder: 'Ex: achat RP, krach mars 2025…', confirmText: 'Enregistrer'
  });
  if (note === null) return; // cancelled
  await api('PUT', '/api/snapshot-notes', { date, notes: note });
  if (S.synthese) S.synthese.snapshot_note = note || null;
  renderSnapshotNote(S.synthese);
  toast(note ? 'Note enregistrée' : 'Note supprimée');
}

// ─── Wealth target gauge ─────────────────────────────────────────────────

let _wealthTarget = null;

export async function loadWealthTarget() {
  try {
    const data = await api('GET', '/api/wealth-target');
    _wealthTarget = data?.target || null;
  } catch { _wealthTarget = null; }
}

/** « 12 j », « 3 mois », « 1 an » : la duree qui separe deux arretes. */
function _duree(d0, d1) {
  const j = Math.round((Date.parse(d1) - Date.parse(d0)) / 864e5);
  if (j < 45) return `${j} j`;
  if (j < 335) return `${Math.round(j / 30.44)} mois`;
  const a = Math.round(j / 365.25);
  return `${a} an${a > 1 ? 's' : ''}`;
}

function _pastillesHeros(net, variation, valeurs, dates) {
  const puce = (delta, pct, duree) => {
    if (delta == null && pct == null) return '';
    const sens = (delta ?? pct) >= 0 ? 'pos' : 'neg';
    const montant = delta != null ? `${delta >= 0 ? '+' : '−'}${fmt(Math.abs(delta))}` : '';
    return `<span class="puce puce--${sens}">${montant}${pct != null ? ` ${fmtPct(pct, 1, true)}` : ''}<small>${duree}</small></span>`;
  };
  const courte = variation?.prev_date
    ? puce(variation.net_delta, variation.net_pct, _duree(variation.prev_date, S.syntheseDate || dates[dates.length - 1])) : '';
  // Sur un an si l'historique le permet ; sinon depuis le premier arrete.
  const i = dates.findIndex(d => d === (S.syntheseDate || dates[dates.length - 1]));
  const fin = i >= 0 ? i : dates.length - 1;
  const cible = new Date(Date.parse(dates[fin]) - 365 * 864e5).toISOString().slice(0, 10);
  let debut = dates.findIndex(d => d >= cible);
  if (debut < 0 || debut >= fin) debut = 0;
  const v0 = valeurs[debut], v1 = valeurs[fin];
  const longue = fin > debut && v0
    ? puce(null, (v1 - v0) / Math.abs(v0) * 100,
           dates[debut] <= cible ? '1 an' : `depuis le ${fmtDate(dates[debut])}`) : '';
  return (courte || longue) ? `<div class="hero-puces">${courte}${longue}</div>` : '';
}

function renderWealthTarget(currentNet, isFamily = true, valeurs = [], dates = []) {
  const bar = document.getElementById('wealth-target-bar');
  const menuBtn = document.getElementById('btn-open-wealth-target');
  if (menuBtn) {
    menuBtn.innerHTML = _wealthTarget ? '&#127919; Modifier objectif patrimoine' : '&#127919; Objectif patrimoine';
    menuBtn.onclick = openWealthTargetEditor;
  }
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
  const kpiNet = S.synthese?.family?.net || 0;
  renderWealthTarget(kpiNet);
  toast(target ? 'Objectif enregistré' : 'Objectif supprimé');
}
