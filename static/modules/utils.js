import { S } from './state.js';
import { isMasked, maskFormatted, maskAxis } from './mask.js';

const _nf = (n, dec) => new Intl.NumberFormat('fr-FR', {
  minimumFractionDigits: dec,
  maximumFractionDigits: dec,
}).format(n);

export const fmt = (n, dec = 0) => {
  if (n == null) return '—';
  const brut = _nf(n, dec);
  return (isMasked() ? maskFormatted(brut) : brut) + '\u202f€';
};

/** Quantite de titres. Masquee comme un montant : le cours etant public, une
 *  quantite visible suffit a retrouver la valorisation. */
export const fmtQty = (n, dec = 0) => {
  if (n == null) return '—';
  const brut = _nf(n, dec);
  return isMasked() ? maskFormatted(brut) : brut;
};

/** Libelle d'axe de graphe (notation compacte : "29 k€"). Cinq graphes le
 *  reformataient chacun de leur cote ; un seul endroit desormais, donc un seul
 *  endroit ou le masquage s'applique. */
const _axeFormats = {};
export const fmtAxis = (v, _i, ticks) => {
  if (isMasked()) return maskAxis();
  // Assez de decimales pour que deux graduations voisines ne se lisent pas
  // pareil : de 1,00 a 1,04 M€ par pas de 20 k€, « 1 M€ » s'affichait trois
  // fois. Chart.js passe la liste des graduations en troisieme argument.
  let dec = 0;
  if (ticks?.length > 1) {
    const pas = Math.abs(ticks[1].value - ticks[0].value);
    const unite = Math.abs(v) >= 1e9 ? 1e9 : Math.abs(v) >= 1e6 ? 1e6 : Math.abs(v) >= 1e3 ? 1e3 : 1;
    if (pas > 0 && pas < unite) dec = Math.min(2, Math.ceil(-Math.log10(pas / unite) - 1e-9));
  }
  const f = (_axeFormats[dec] ||= new Intl.NumberFormat('fr-FR', { notation: 'compact', maximumFractionDigits: dec }));
  return f.format(v) + '\u202f€';
};


/** Sparkline : la tendance d'un indicateur, sous son chiffre.
 *
 * Un montant seul ne dit pas s'il monte depuis six mois ou s'il vient de
 * rebondir. La forme le dit d'un coup d'oeil, sans place ni axe.
 *
 * Non masquee en mode discretion : sans echelle ni graduation, une courbe ne
 * revele aucun montant — seulement un sens, au meme titre qu'un pourcentage.
 *
 * @param {number[]} valeurs  serie chronologique, au moins deux points
 * @param {object}   opts     couleur CSS, inversion du sens « bon/mauvais »
 */
export function sparkline(valeurs, { couleur = 'var(--primary)', hauteur = 26 } = {}) {
  const pts = (valeurs || []).filter(v => typeof v === 'number' && isFinite(v));
  if (pts.length < 2) return '';            // un point ne fait pas une tendance

  const min = Math.min(...pts), max = Math.max(...pts);
  const amp = max - min;
  const L = 100, H = hauteur;
  // Une serie plate se dessine au milieu plutot que sur un bord : une division
  // par zero la collerait en haut et simulerait un sommet.
  const y = v => amp === 0 ? H / 2 : H - 2 - ((v - min) / amp) * (H - 4);
  const x = i => (i / (pts.length - 1)) * L;

  const d = pts.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  const dernier = { x: x(pts.length - 1), y: y(pts[pts.length - 1]) };

  // Le point final est un SEGMENT DE LONGUEUR NULLE a bout rond, pas un
  // `<circle>` : l'etirement en largeur (`preserveAspectRatio="none"`, qui
  // permet a la courbe de remplir la carte) transforme un cercle en ellipse,
  // alors qu'une epaisseur de trait non mise a l'echelle reste ronde.
  const pt = `${dernier.x.toFixed(1)} ${dernier.y.toFixed(1)}`;
  return `<svg class="spark" viewBox="0 0 ${L} ${H}" preserveAspectRatio="none"
               aria-hidden="true" focusable="false">
    <path d="${d} L${L} ${H} L0 ${H} Z" fill="${couleur}" fill-opacity=".10"/>
    <path d="${d}" fill="none" stroke="${couleur}" stroke-width="1.6"
          stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
    <path d="M${pt} L${pt}" stroke="${couleur}" stroke-width="4.5"
          stroke-linecap="round" vector-effect="non-scaling-stroke"/>
  </svg>`;
}

export const fmtDate = d => {
  if (!d) return '—';
  const [y, m, day] = d.split('-');
  return `${day}/${m}/${y}`;
};

export const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

export const liqBadge = liq => {
  const map = {
    'J0\u2013J1':  'badge-j01',
    'J2\u2013J7':  'badge-j27',
    'J8\u2013J30': 'badge-j830',
    '30J+':        'badge-30',
    'Bloqu\u00e9': 'badge-blk',
  };
  return `<span class="badge ${map[liq] || 'badge-blk'}">${esc(liq) || '—'}</span>`;
};

export const fmtDelta = (n, dec = 0) => {
  if (n == null || n === 0) return '';
  // Le signe passe devant la valeur absolue : masquee, "-" colle a "???" se lit
  // mal, et fmt() gere deja le masquage.
  return (n > 0 ? '+' : '−') + fmt(Math.abs(n), dec);
};

export function kpiDelta(variation, deltaKey, pctKey = null, { invert = false, label = null } = {}) {
  if (!variation) return '';
  const delta = variation[deltaKey];
  if (delta == null || delta === 0) return '';
  const positive = invert ? delta < 0 : delta > 0;
  const cls = positive ? 'kpi-delta-pos' : 'kpi-delta-neg';
  const arrow = delta > 0 ? '\u25b2' : '\u25bc';
  let pctStr = '';
  if (pctKey && variation[pctKey] != null) {
    const pct = variation[pctKey];
    pctStr = ` (${fmtPct(pct, 1, true)})`;
  }
  const labelStr = label ? `<span class="kpi-delta-label">${label}</span> ` : '';
  return `<div class="${cls}">${labelStr}${arrow} ${fmtDelta(delta)}${pctStr}</div>`;
}

// `flux.amount` est toujours stocke en valeur absolue : c'est le TYPE qui porte
// le sens, comme dans le calcul du TRI et celui de la TWR. L'afficher tel quel
// donnait un retrait a +210 000 EUR, et un total qui additionnait les sorties
// aux entrees au lieu de les retrancher. Vu du compte : un versement et un
// coupon entrent, un retrait et des frais sortent. Un type inconnu garde le
// signe stocke, faute de mieux.
const FLUX_SENS = { 'Versement': 1, 'Dividende/Intérêt': 1, 'Retrait': -1, 'Frais': -1 };

/** Montant signe d'un flux, du point de vue du compte. */
export const fluxSigned = f =>
  (FLUX_SENS[f.type] ?? (Math.sign(f.amount || 0) || 1)) * Math.abs(f.amount || 0);

/** Montant avec son signe explicite : le "+" d'une entree se lit mieux. */
export const fmtSigned = (v, dec = 0) =>
  `${v > 0 ? '+' : v < 0 ? '−' : ''}${fmt(Math.abs(v), dec)}`;

export const today = () => new Date().toISOString().slice(0, 10);

const _pctFormats = {};
/** Un pourcentage a la francaise : virgule decimale, espace fine insecable
 *  avant le signe %. `toFixed` ecrivait « +13.9 % » dans toute l'application.
 *  @param {number} v       deja en pourcent (13.9, pas 0.139)
 *  @param {number} dec     decimales
 *  @param {boolean} signe  prefixe + ou − (le moins typographique)
 *  A reserver au TEXTE : une largeur CSS (`width:…%`) veut un point. */
export function fmtPct(v, dec = 1, signe = false) {
  if (v == null || Number.isNaN(v)) return '—';
  const f = (_pctFormats[dec] ||= new Intl.NumberFormat('fr-FR',
    { minimumFractionDigits: dec, maximumFractionDigits: dec }));
  const s = f.format(Math.abs(v)) + '\u202f%';
  if (!signe) return (v < 0 ? '−' : '') + s;
  return (v > 0 ? '+' : v < 0 ? '−' : '') + s;
}

export function parseLocaleNumber(value, fallback = NaN) {
  if (value == null) return fallback;
  if (typeof value === 'number') return Number.isFinite(value) ? value : fallback;
  let s = String(value).trim();
  if (!s) return fallback;
  s = s.replace(/\u2212/g, '-').replace(/[\s\u00a0\u202f_'’]/g, '');
  if (s.includes(',') && s.includes('.')) {
    s = s.lastIndexOf(',') > s.lastIndexOf('.')
      ? s.replace(/\./g, '').replace(',', '.')
      : s.replace(/,/g, '');
  } else {
    s = s.replace(',', '.');
  }
  const n = Number(s);
  return Number.isFinite(n) ? n : fallback;
}

export function sortArr(arr, key, dir) {
  if (!key) return arr;
  const vide = v => v === null || v === undefined || v === '';
  return [...arr].sort((a, b) => {
    const va = a[key], vb = b[key];
    // Une valeur absente reste en bas dans les deux sens. Remplacee par '',
    // elle faisait basculer toute la colonne en ordre alphabetique des qu'une
    // ligne en manquait : « 4596 » se classait avant « 788 ».
    if (vide(va) || vide(vb)) return vide(va) - vide(vb);
    if (typeof va === 'number' && typeof vb === 'number') return dir * (va - vb);
    return dir * String(va).localeCompare(String(vb), 'fr', { sensitivity: 'base' });
  });
}

export function wireSortableTable(theadId, stateKey, rerenderFn) {
  const thead = document.getElementById(theadId);
  if (!thead) return;
  // Delegation sur le thead : un en-tete reconstruit garde son comportement.
  const trier = th => {
    const key = th.dataset.sort;
    const st  = S.sort[stateKey];
    if (st.key === key) {
      st.dir = -st.dir;
    } else {
      st.key = key;
      st.dir = 1;
    }
    rerenderFn();
  };
  thead.addEventListener('click', e => {
    const th = e.target.closest('th[data-sort]');
    if (th) trier(th);
  });
  // Au clavier aussi : Entree ou Espace sur un en-tete triable.
  thead.addEventListener('keydown', e => {
    const th = e.target.closest('th[data-sort]');
    if (th && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); trier(th); }
  });
  updateSortIndicators(theadId, stateKey);
}

export function updateSortIndicators(theadId, stateKey) {
  const thead = document.getElementById(theadId);
  if (!thead) return;
  const { key, dir } = S.sort[stateKey];
  thead.querySelectorAll('th[data-sort]').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    // Atteignable au clavier, et l'etat du tri annonce aux lecteurs d'ecran.
    th.tabIndex = 0;
    const actif = th.dataset.sort === key;
    if (actif) th.classList.add(dir === 1 ? 'sort-asc' : 'sort-desc');
    th.setAttribute('aria-sort', actif ? (dir === 1 ? 'ascending' : 'descending') : 'none');
  });
}

// ─── Chart color cache (invalidated on theme change) ─────────────────────
let _colorCache = null;
let _cachedTheme = null;

function _readTheme() {
  return document.documentElement.dataset.theme || 'light';
}

function _ensureCache() {
  const theme = _readTheme();
  if (_colorCache && _cachedTheme === theme) return;
  const s = getComputedStyle(document.documentElement);
  _colorCache = {
    palette: Array.from({ length: 11 }, (_, i) => s.getPropertyValue(`--chart-${i + 1}`).trim()),
    border:  s.getPropertyValue('--chart-border').trim() || '#fff',
  };
  _cachedTheme = theme;
}

export function getColors() { _ensureCache(); return _colorCache.palette; }

export function chartBorderColor() { _ensureCache(); return _colorCache.border; }

export const liqText = l => l ? `Liq. ${l}` : '';

/**
 * Destroy a Chart.js instance safely and return null (for re-assignment).
 * Usage: myChart = destroyChart(myChart);
 */
export function destroyChart(chart) {
  if (chart) chart.destroy();
  return null;
}



// ─── Axe temporel Chart.js ─────────────────────────────────────────────────
// Jamais d'echelle `category` pour une serie temporelle (CLAUDE.md) : des
// arretes irreguliers y tombent a egale distance, et la pente ment. Sans
// adaptateur de dates, l'axe est lineaire sur l'epoch.

/** AAAA-MM-JJ -> epoch, a midi : une date ne glisse pas d'un jour selon le fuseau. */
export const tsJour = d => new Date(d + 'T12:00:00').getTime();

/** Echelle x bornee aux dates fournies. `jour` : libelle au jour pres (courtes
 *  periodes), sinon au mois. */
export function echelleTemps(dates, { jour = true, taille = 10, max = 6 } = {}) {
  const ts = dates.map(tsJour);
  return {
    type: 'linear', min: Math.min(...ts), max: Math.max(...ts),
    ticks: {
      font: { size: taille }, maxRotation: 0, autoSkip: true, maxTicksLimit: max,
      callback: v => new Date(v).toLocaleDateString('fr-FR',
        jour ? { day: '2-digit', month: 'short' } : { month: 'short', year: '2-digit' }),
    },
    grid: { display: false },
  };
}

/** Titre d'infobulle : la date du point survole. */
export const titreDate = items => items.length ? new Date(items[0].parsed.x).toLocaleDateString('fr-FR') : '';
