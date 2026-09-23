import { api } from '../api.js';
import { S } from '../state.js';
import { dessinerCourbe } from '../courbe.js';
import { fmt, esc, fmtDate, fmtPct } from '../utils.js';

// Etat local : donnees, groupe isole, maille, tri de la liste.
// Le tri par defaut est celui que produit l'API — valeur decroissante — pour
// qu'ouvrir l'onglet et cliquer un en-tete ne donnent pas deux ordres sans
// rapport. Il survit au rechargement des donnees : reordonner puis changer de
// maille ne doit pas ramener a l'ordre initial.
const V = { data: null, focus: null, group: 'account',
            sort: { col: 'value', dir: 'desc' }, showExcluded: false,
            // Lignes dont le detail des ecarts inexpliques est deplie.
            suspectsOpen: new Set() };

// Cles de tri. Le nom concatene l'enveloppe et le libelle de compte, dans
// l'ordre ou la ligne les affiche.
const SORTS = {
  name: g => `${g.envelope || g.label || ''} ${g.account_label || ''}`.trim(),
  rend: g => rend(g)?.v,
  value: g => g.value,
};
// Sens du premier clic : decroissant sur un chiffre — on cherche le plus
// grand —, croissant sur un texte.
const SORT_DIR0 = { name: 'asc', rend: 'desc', value: 'desc' };

function sortRows(rows) {
  const { col, dir } = V.sort;
  const cle = SORTS[col] || SORTS.value;
  const sens = dir === 'asc' ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const x = cle(a), y = cle(b);
    // Une valeur absente reste en bas dans les deux sens : un groupe dont le
    // rendement n'est pas mesurable n'a pas a prendre la tete de la liste.
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return typeof x === 'string' ? sens * x.localeCompare(y, 'fr') : sens * (x - y);
  });
}

function setSort(col) {
  V.sort = V.sort.col === col
    ? { col, dir: V.sort.dir === 'asc' ? 'desc' : 'asc' }
    : { col, dir: SORT_DIR0[col] || 'desc' };
  renderPerformance();
}

/** Nombre brut. `fmt` de utils.js ajoute toujours l'euro : inutilisable pour un %.
 *  Non masque a dessein — sert aux compteurs (nombre d'arretes, de comptes), qui
 *  ne revelent aucun montant. Les euros passent par `fmt`. */
const n = (v, dec = 0) => v == null ? '—'
  : new Intl.NumberFormat('fr-FR', { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(v);

/** Rendement en fraction (0,079) ecrit en pourcent signe (+7,90 %). */
const pct = (v, dec = 2) => v == null ? '—' : fmtPct(v * 100, dec, true);

const sign = v => v == null ? '' : (v >= 0 ? 'positive' : 'negative');

/** Le rendement qu'on affiche en tete : le TRI, ce que l'argent a rapporte
 *  selon quand il a ete verse. Annuel au-dela de six mois d'historique ; en
 *  deca, le rendement de la periode, dit comme tel — annualiser deux mois
 *  fabriquerait un taux qu'on ne verra jamais. */
/** Le TWR ne s'affiche a cote du TRI que s'il en differe. Sans versement ni
 *  retrait sur la periode, les deux sont egaux par construction : ecrire deux
 *  fois « +7,95 % » n'apprend rien, et fait douter de l'un des deux. */
function twrDiffere(g) {
  const r = rend(g);
  if (!r || g.twr == null) return false;
  const t = g.tri != null ? (g.annualisable ? g.twr_annualise : null) : g.twr;
  return t != null && Math.abs(t - r.v) >= 0.0005;
}

function rend(g) {
  if (g?.tri != null) return { v: g.tri, sub: 'par an' };
  if (g?.tri_periode != null) return { v: g.tri_periode, sub: `sur ${duree(g.tri_jours)}` };
  return null;
}

function duree(days) {
  if (days == null) return '—';
  if (days < 62) return `${days} j`;
  const m = Math.round(days / 30.44);
  return m < 24 ? `${m} mois` : `${n(days / 365.25, 1)} ans`;
}

export async function loadPerformance() {
  const owner = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : null;
  const qs = new URLSearchParams({ group: V.group });
  if (owner) qs.set('owner', owner);
  V.data = await api('GET', `/api/performance?${qs}`);
  V.focus = null;
  renderPerformance();
}

// Les groupes sans rendement calculable restent affiches : les masquer ferait
// diverger le total de cet onglet de celui de la synthese, sans explication.
// Ne restent affiches que les comptes dont un rendement se mesure. Sont ecartes
// les comptes courants et les objets de valeur (aucun rendement a mesurer), et
// les capitaux propres negatifs (aucun rendement calculable sur une base
// negative, quel que soit l'historique). Le decompte figure dans l'en-tete pour
// que le total reste explicable.
const HIDDEN = new Set(['non_measurable', 'negative', 'closed']);
const visible = () => (V.data?.groups || []).filter(g => !HIDDEN.has(g.status));
// Motif de repli. Le motif precis vient de l'API, ou vit la regle : un libelle
// unique pour toutes les exclusions affichait "trésorerie, aucun rendement" en
// face d'une résidence principale.
const LABELS = { insufficient: 'historique insuffisant', negative: 'capital négatif',
                 non_measurable: 'aucun rendement à mesurer',
                 closed: 'compte clos' };
/** [libelle du compte, alerte] pour tous les groupes qui en portent. */
const alertes = d => (d?.groups || []).flatMap(
  g => (g.price_warnings || []).map(a => [g.label, a]));

const current = () => V.focus
  ? visible().find(g => g.key === V.focus) || V.data.global
  : V.data.global;

export function renderPerformance() {
  const d = V.data;
  const body = document.getElementById('perf-body');
  const empty = document.getElementById('perf-empty');
  if (!d || d.insufficient || !d.groups?.length) {
    body?.classList.add('hidden');
    empty?.classList.remove('hidden');
    return;
  }
  body?.classList.remove('hidden');
  empty?.classList.add('hidden');
  renderHeader(d);
  renderKpi(d);
  renderList(d);
  renderChart(d);
}

function renderHeader(d) {
  const host = document.getElementById('perf-controls');
  if (!host) return;
  host.innerHTML = `
    <div class="seg" role="group" aria-label="Maille d'agrégation">
      <button type="button" class="seg-btn ${V.group === 'account' ? 'is-on' : ''}" data-group="account"
        aria-pressed="${V.group === 'account'}" aria-describedby="perf-maille-aide">Par compte</button>
      <button type="button" class="seg-btn ${V.group === 'envelope' ? 'is-on' : ''}" data-group="envelope"
        aria-pressed="${V.group === 'envelope'}" aria-describedby="perf-maille-aide">Par enveloppe</button>
    </div>
    ${V.focus ? `<button type="button" class="btn btn-sm" id="perf-reset">↩ Tout afficher</button>` : ''}
    <span class="perf-meta">${d.dates.length} arrêtés · ${fmtDate(d.first_date)} → ${fmtDate(d.date)}${
      d.excluded?.length || alertes(d).length ? ` · <button type="button"
        class="perf-excl-toggle" id="perf-excl" aria-expanded="${V.showExcluded}">${
        d.excluded.length} hors calcul${
        alertes(d).length ? ` · ${alertes(d).length} cours à vérifier` : ''} ${
        V.showExcluded ? '▴' : '▾'}</button>` : ''}</span>
    <p class="form-aide perf-maille-aide" id="perf-maille-aide">${V.group === 'account'
      ? 'Un compte : une enveloppe chez un établissement, pour un titulaire. Chaque contrat a son propre rendement.'
      : 'Tous les contrats d’une même enveloppe fusionnés, titulaires et établissements confondus. Un écart avec la vue par compte signale une enveloppe qui agrège des contrats sans rapport.'}</p>`;
  host.querySelectorAll('[data-group]').forEach(b => b.addEventListener('click', () => {
    if (V.group === b.dataset.group) return;
    V.group = b.dataset.group;
    loadPerformance();
  }));
  document.getElementById('perf-reset')?.addEventListener('click', () => {
    V.focus = null; renderPerformance();
  });
  document.getElementById('perf-excl')?.addEventListener('click', () => {
    V.showExcluded = !V.showExcluded; renderPerformance();
  });
}

function renderKpi(d) {
  const host = document.getElementById('perf-kpi');
  if (!host) return;
  const g = current();
  if (!g) { host.innerHTML = ''; return; }
  // Meme gabarit que la synthese (.kpi-card + lisere colore) : deux onglets qui
  // presentent des indicateurs doivent se ressembler.
  const comptes = g.accounts || (V.data.groups || []).filter(x => x.status === 'ok').length;
  const tiles = [
    ['', `Valeur au ${fmtDate(d.date)}`, fmt(g.value),
      V.focus ? esc(g.label) : `${comptes} compte${comptes > 1 ? 's' : ''} mesuré${comptes > 1 ? 's' : ''}`],
    ['kpi-gross', 'Rendement de votre argent', rend(g) ? pct(rend(g).v) : '—',
      rend(g) ? `${rend(g).sub} · selon la date de vos versements` : 'historique insuffisant',
      sign(rend(g)?.v)],
    // Le TWR ne juge que le placement, versements neutralises : c'est la
    // mesure a comparer a un indice, ou d'un contrat a l'autre. Second plan.
    ['kpi-mobilizable', 'Pour comparer à un indice',
      g.annualisable ? pct(g.twr_annualise) : pct(g.twr),
      g.annualisable ? 'TWR, par an' : `TWR, sur ${duree(g.days)}`,
      sign(g.annualisable ? g.twr_annualise : g.twr)],
    // La periode est nommee sur la tuile elle-meme : "de la periode" sans dire
    // laquelle obligeait a aller la chercher a l'autre bout de l'ecran.
    ['kpi-debt', 'Apports nets', fmt(g.flux_net),
      `du ${fmtDate(d.first_date)} au ${fmtDate(d.date)} — `
      + `${g.flux_count} mouvement${g.flux_count > 1 ? 's' : ''}, hors dividendes`],
  ];
  host.innerHTML = tiles.map(([variant, k, v, s, cl = '']) => `
    <div class="kpi-card ${variant}">
      <div class="kpi-label">${esc(k)}</div>
      <div class="kpi-value ${cl}">${v}</div>
      <div class="kpi-sub">${s}</div>
    </div>`).join('');
}

/** Liste en grille plutot qu'un tableau : sept colonnes de chiffres se lisent
 *  mal, et la barre donne l'ordre de grandeur avant la lecture du nombre. */
function renderList(d) {
  const host = document.getElementById('perf-list');
  if (!host) return;
  const rows = sortRows(visible());
  const span = Math.max(0.02, ...rows.map(g => Math.abs(rend(g)?.v || 0)));
  const total = rows.filter(g => g.status === 'ok').length;
  const line = g => {
    const r = rend(g);
    const w = r == null ? 0 : Math.abs(r.v) / span * 50;
    const neg = (r?.v || 0) < 0;
    const sub = [g.establishment, g.owner].filter(Boolean).join(' · ')
      || (g.categories || []).join(', ');
    // Un seul badge de statut par ligne : "valeur negative" et "non mesurable"
    // cote a cote se contredisaient. Et une TWR negative est un resultat normal,
    // pas une anomalie : rien ne la signale. Seul « historique insuffisant »
    // reste dans la liste : les autres statuts sont dans HIDDEN, detailles dans
    // le panneau « hors calcul ».
    const STATUS_BADGE = {
      insufficient: ['historique insuffisant',
        'Il faut deux valorisations successives pour mesurer un rendement. Hors du total.'],
    };
    const st = STATUS_BADGE[g.status];
    const suspects = g.suspect_periods || [];
    const flags = [
      st ? `<span class="badge badge-blk">${st[0]}</span>` : '',
      g.price_warnings?.length
        ? `<span class="badge badge-30">cours à vérifier</span>` : '',
      suspects.length ? `<span class="badge badge-30">écart inexpliqué</span>` : '',
    ].join(' ');
    // Le motif et la liste des ecarts s'affichent sous la ligne, pas dans une
    // infobulle : ils conditionnent la lecture du rendement.
    const ouvert = V.suspectsOpen.has(g.key);
    const idDetail = `perf-susp-${esc(g.key).replace(/[^\w-]/g, '_')}`;
    const detail = st || suspects.length ? `
      <div class="perf-detail">
        ${st ? `<span>${esc(st[1])}</span>` : ''}
        ${suspects.length ? `<button type="button" class="perf-excl-toggle" data-suspects="${esc(g.key)}"
            aria-expanded="${ouvert}" aria-controls="${idDetail}">${suspects.length} période${
            suspects.length > 1 ? 's' : ''} à variation inexpliquée ${ouvert ? '▴' : '▾'}</button>
          <ul class="perf-detail-list" id="${idDetail}"${ouvert ? '' : ' hidden'}>${suspects.map(x => `
            <li>${fmtDate(x.from)} → ${fmtDate(x.to)} : ${pct(x.change)} inexpliqué (${
              x.delta >= 0 ? '+' : '−'}${fmt(Math.abs(x.delta))} de variation, ${
              x.flux ? fmt(x.flux) + ' de flux déclaré' : 'aucun flux déclaré'})</li>`).join('')}
          </ul>` : ''}
      </div>` : '';
    return `
      <div class="perf-item${V.focus === g.key ? ' is-focus' : ''}" data-key="${esc(g.key)}"
           tabindex="0" role="button" aria-pressed="${V.focus === g.key}">
        <div class="perf-name">
          <span class="perf-title">${esc(g.envelope || g.label)}${
            g.account_label ? ` <span class="perf-account">${esc(g.account_label)}</span>` : ''}</span>
          ${sub ? `<span class="perf-sub">${esc(sub)}</span>` : ''}
        </div>
        <div class="perf-bar" aria-hidden="true">
          <span class="perf-bar-fill ${neg ? 'neg' : 'pos'}"
                style="width:${w.toFixed(1)}%;${neg ? 'right' : 'left'}:50%"></span>
        </div>
        <div class="perf-num ${sign(r?.v)}">${r ? pct(r.v) : '—'}
          <span class="perf-num-sub">${
            r ? `${r.sub}${twrDiffere(g) ? ` · TWR ${pct(g.annualisable ? g.twr_annualise : g.twr)}` : ''}`
            : `${g.dates_count} arrêté${g.dates_count > 1 ? 's' : ''}`}</span>
        </div>
        <div class="perf-val">${fmt(g.value)}
          <span class="perf-num-sub">${flags || (g.flux_count ? `${g.flux_count} flux` : '')}</span>
        </div>
      </div>${detail}`;
  };
  const g = d.global;
  // En-tetes triables. La colonne de barres n'en est pas une : elle donne a
  // voir le rendement, que son propre en-tete trie deja.
  const th = (col, texte, cls = '') => {
    const actif = V.sort.col === col;
    const sens = actif ? V.sort.dir : null;
    // `aria-sort` n'existe que sur un en-tete de tableau : ici, une liste. Le
    // bouton dit donc son etat dans son nom, que le lecteur d'ecran annonce.
    const etat = actif ? `, trié par ordre ${sens === 'asc' ? 'croissant' : 'décroissant'}` : '';
    return `<span class="perf-th ${cls}${actif ? ' is-sorted' : ''}" data-sort="${col}"
        role="button" tabindex="0" aria-label="Trier par ${esc(texte.toLowerCase())}${etat}"
      >${texte}<i class="perf-caret" aria-hidden="true">${actif ? (sens === 'asc' ? '▲' : '▼') : ''}</i></span>`;
  };
  host.innerHTML = `
    <div class="perf-head">
      ${th('name', V.group === 'account' ? 'Compte' : 'Enveloppe')}
      <span class="perf-axis"><i>−</i><i>0</i><i>+</i></span>
      ${th('rend', 'Rendement', 'ta-r')}${th('value', 'Valeur', 'ta-r')}
    </div>
    ${rows.map(line).join('')}
    ${g && !V.focus && total > 1 ? `<div class="perf-item is-total">
      <div class="perf-name"><span class="perf-title">Ensemble mesurable</span>
        <span class="perf-sub">${(g.groups || []).length} ${V.group === 'account' ? 'compte' : 'enveloppe'}${(g.groups || []).length > 1 ? 's' : ''}</span></div>
      <div class="perf-bar"></div>
      <div class="perf-num ${sign(rend(g)?.v)}">${rend(g) ? pct(rend(g).v) : '—'}
        <span class="perf-num-sub">${rend(g) ? rend(g).sub : ''}${twrDiffere(g)
          ? ` · TWR ${pct(g.annualisable ? g.twr_annualise : g.twr)}` : ''}</span></div>
      <div class="perf-val">${fmt(g.value)}</div>
    </div>` : ''}
    ${V.showExcluded && alertes(d).length ? `<div class="perf-excluded">
      <div class="perf-excluded-head">Valorisations à vérifier — le modèle a préféré la
        valeur enregistrée au cours du jour</div>
      ${alertes(d).map(([lbl, a]) => `<div class="perf-excluded-row">
        <span>${esc(a.name || a.isin)}</span>
        <span class="perf-excl-why">${esc(a.reason)}</span>
        <span class="num">${esc(lbl)}</span>
      </div>`).join('')}
    </div>` : ''}
    ${V.showExcluded && d.excluded?.length ? `<div class="perf-excluded">
      <div class="perf-excluded-head">Hors calcul — ${d.excluded.length} compte${
        d.excluded.length > 1 ? 's' : ''}, présents dans la synthèse mais sans rendement mesurable</div>
      ${d.excluded.map(e => `<div class="perf-excluded-row">
        <span>${esc(e.label)}</span>
        <span class="perf-excl-why">${esc(e.reason || LABELS[e.status] || e.status)}${
          e.status === 'closed' && e.last_date
            ? ` · dernière valeur le ${fmtDate(e.last_date)}` : ''}</span>
        <span class="num">${fmt(e.value)}</span>
      </div>`).join('')}
    </div>` : ''}
    <p class="perf-note">Les pourcentages sont des rendements <strong>cumulés sur la
    période</strong> ; « /an » signale un équivalent annualisé, affiché à partir de
    ${d.min_days_annualise} jours d'historique seulement — extrapoler quelques semaines
    à l'année ne renseigne sur rien. Cliquez une ligne pour l'isoler, un en-tête pour
    trier.</p>`;
  host.querySelectorAll('.perf-th[data-sort]').forEach(el => {
    const trier = () => setSort(el.dataset.sort);
    el.addEventListener('click', trier);
    el.addEventListener('keydown', ev => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); trier(); }
    });
  });
  host.querySelectorAll('[data-suspects]').forEach(b => b.addEventListener('click', () => {
    const k = b.dataset.suspects;
    if (V.suspectsOpen.has(k)) V.suspectsOpen.delete(k); else V.suspectsOpen.add(k);
    renderPerformance();
    // Le rendu remplace le bouton : le focus clavier y revient.
    document.querySelector(`#perf-list [data-suspects="${CSS.escape(k)}"]`)?.focus();
  }));
  host.querySelectorAll('.perf-item[data-key]').forEach(el => {
    const pick = () => {
      V.focus = V.focus === el.dataset.key ? null : el.dataset.key;
      renderPerformance();
    };
    el.addEventListener('click', pick);
    el.addEventListener('keydown', ev => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(); }
    });
  });
}

// Cours de l'ETF de comparaison, gardes pour la periode affichee : changer de
// compte dans la liste ne doit pas les redemander.
// Une Map par periode, remplie au RETOUR de la requete : une reponse lente ne
// peut plus s'inscrire sous la cle d'une autre periode. Le jeton ecarte le
// rendu dont la reponse arrive apres celui d'un clic plus recent.
const _benchs = new Map();
let _rendu = 0;

/** La courbe des placements — ou du compte choisi dans la liste — face a un
 *  ETF World. Comparaison honnete ici, et ici seulement : le TWR neutralise
 *  les versements, comme un indice qui n'en recoit pas. (Sur la synthese, le
 *  patrimoine net grossit aussi de l'epargne : le comparer a un ETF ferait
 *  passer l'epargne pour du talent.) L'ETF est recale sur la premiere date
 *  commune, et l'ecart se chiffre sur cette periode, nommee. */
async function renderChart(d) {
  const hote = document.getElementById('perf-courbe');
  const legende = document.getElementById('perf-legende');
  if (!hote) return;
  // Sans compte choisi, la comparaison porte sur la part exposee aux marches :
  // l'epargne de precaution, sans risque, face a un indice actions, faisait
  // passer la prudence pour une contre-performance.
  const g = V.focus ? d.groups.find(x => x.key === V.focus) : (d.marche || d.global);
  const serie = (g?.serie || []).filter(p => p.index != null);
  if (serie.length < 2) {
    hote.innerHTML = '<p class="courbe-vide">Deux arrêtés valorisés au moins sont nécessaires pour une courbe.</p>';
    if (legende) legende.innerHTML = '';
    return;
  }
  const debut = serie[0].date, fin = serie[serie.length - 1].date;
  const jeton = ++_rendu, cle = debut + fin;
  if (!_benchs.has(cle)) {
    let b = null;
    try { b = await api('GET', `/api/benchmark?debut=${debut}&fin=${fin}`, null, { silent: true }); }
    catch { /* pas de comparaison, la courbe seule */ }
    _benchs.set(cle, b);
  }
  if (jeton !== _rendu) return;
  const etf = _benchs.get(cle);
  const cours = (etf?.points || []).filter(c => c.price > 0);
  // Le cours a une date d'arrete : le dernier connu a ce jour. Aligner l'ETF
  // sur les arretes garde une seule liste d'abscisses pour les deux series.
  const prixA = date => { let p = null; for (const c of cours) { if (c.date <= date) p = c.price; else break; } return p; };
  // Un historique de cours qui commence le lendemain d'un arrete ne doit pas
  // perdre cet arrete : pour le PREMIER point seulement, le premier cours sert
  // s'il suit de quatre jours au plus. La legende nomme alors sa date.
  const JOURS = 864e5, TOLERANCE = 4;
  const premierApres = date => cours.find(c => c.date > date
    && (Date.parse(c.date) - Date.parse(date)) / JOURS <= TOLERANCE);
  let communs = serie.filter(p => prixA(p.date) != null);
  let recale = null;
  const avant = serie.filter(p => prixA(p.date) == null);
  const proche = avant.length ? premierApres(avant[avant.length - 1].date) : null;
  if (proche) { recale = { arrete: avant[avant.length - 1].date, cours: proche }; communs = [avant[avant.length - 1], ...communs]; }
  const prixDe = date => (recale && date === recale.arrete ? recale.cours.price : prixA(date));
  let bench = null, comp = null;
  if (communs.length >= 2) {
    const a = communs[0], p0 = prixDe(a.date);
    bench = communs.map(p => ({ date: p.date, v: a.index * prixDe(p.date) / p0 }));
    const z = communs[communs.length - 1];
    comp = { debut: a.date, fin: z.date, moi: z.index / a.index - 1, etf: prixDe(z.date) / p0 - 1 };
  }
  const nom = V.focus ? g.label : (d.marche ? 'Vos placements exposés aux marchés' : 'Vos placements');
  const horsMarche = !V.focus && d.marche?.exclus
    ? `<span class="courbe-note">Hors ${d.marche.exclus} compte${d.marche.exclus > 1 ? 's' : ''} sans risque de marché — livrets, comptes, fonds euros — pour ${fmt(d.marche.exclus_valeur)}.</span>` : '';
  dessinerCourbe(hote, {
    series: [
      { nom, couleur: 'var(--primary)', points: serie.map(p => ({ date: p.date, v: p.index })), aire: true },
      ...(bench ? [{ nom: 'ETF World', couleur: 'var(--text-muted)', points: bench, pointille: true }] : []),
    ],
    formatY: v => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(v),
    formatV: v => pct(v / 100 - 1),
    aide: `${nom}, base 100 au ${fmtDate(debut)} : ${pct(serie[serie.length - 1].index / 100 - 1)} au ${fmtDate(fin)}.`,
  });
  if (!legende) return;
  if (!comp) {
    legende.innerHTML = `<span><i style="background:var(--primary)"></i>${esc(nom)} <b>${pct(serie[serie.length - 1].index / 100 - 1)}</b></span>
      <span class="courbe-note">Aucun ETF World dans l'historique des cours sur cette période : la comparaison apparaîtra avec lui.</span>`;
    return;
  }
  const ecart = (comp.moi - comp.etf) * 100;
  const pts = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(Math.abs(ecart));
  legende.innerHTML = `
    <span><i style="background:var(--primary)"></i>${esc(nom)} <b>${pct(comp.moi)}</b></span>
    <span><i style="background:var(--text-muted)"></i>${esc(etf.name || 'ETF World')} <b>${pct(comp.etf)}</b></span>
    <span class="courbe-note">${Math.abs(ecart) < 0.05 ? 'au niveau de l’ETF' : `${pts} point${Math.abs(ecart) >= 2 ? 's' : ''} ${ecart > 0 ? 'de mieux' : 'de moins'}`}
      du ${fmtDate(comp.debut)} au ${fmtDate(comp.fin)}${comp.debut !== debut ? ' — les cours de l’ETF commencent là' : ''}${
      recale ? ` (cours de l’ETF du ${fmtDate(recale.cours.date)} pour l’arrêté du ${fmtDate(recale.arrete)})` : ''}</span>
    ${etf.devise && etf.devise !== 'EUR' ? `<span class="courbe-note">L’ETF est coté en ${esc(etf.devise)} : l’écart inclut l’effet du change.</span>` : ''}
    ${horsMarche}`;
}

