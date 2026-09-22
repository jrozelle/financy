/**
 * Courbe d'evolution en SVG, au dessin de la maquette validee le 22/09/2026 :
 * une serie pleine avec son aire, une serie de comparaison en pointille, un
 * point final, quatre graduations, des libelles en chasse fixe.
 *
 * Trois regles tiennent le module :
 *
 * 1. L'abscisse est proportionnelle au TEMPS (CLAUDE.md). Les arretes ne sont
 *    pas equidistants — deux en fevrier, un en avril —, et les espacer
 *    regulierement fausserait la pente, donc la lecture du rendement.
 * 2. Le dessin se fait a la largeur reelle du conteneur, redessine au
 *    redimensionnement : un viewBox etire deforme le texte et les points.
 * 3. Le detail se lit au survol ou au clavier, dans une bulle maison — jamais
 *    un attribut `title`, qui ne s'affiche ni sur mobile ni de facon fiable.
 */
import { fmtDate, fmtAxis, esc } from './utils.js';

const NS = 'http://www.w3.org/2000/svg';
const HAUT = 190, MARGE_G = 52, MARGE_D = 14, MARGE_H = 12, MARGE_B = 26;
const MOIS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const ms = iso => Date.parse(`${iso}T00:00:00Z`);

/** Graduations « rondes » couvrant [min, max] : 1, 2, 2,5 ou 5 x 10^n. */
function graduations(min, max, cible = 4) {
  if (min === max) { min -= 1; max += 1; }
  const brut = (max - min) / cible;
  const p = 10 ** Math.floor(Math.log10(brut));
  const pas = [1, 2, 2.5, 5, 10].map(k => k * p).find(k => k >= brut) || 10 * p;
  const debut = Math.floor(min / pas) * pas;
  const out = [];
  for (let v = debut; v <= max + pas * 0.001; v += pas) out.push(+v.toFixed(10));
  if (out[out.length - 1] < max) out.push(out[out.length - 1] + pas);
  return out;
}

/** Libelles de mois : au plus `n`, alignes sur des debuts de mois reels. */
function moisAffiches(t0, t1, n = 4) {
  const d0 = new Date(t0), d1 = new Date(t1);
  const tous = [];
  const c = new Date(Date.UTC(d0.getUTCFullYear(), d0.getUTCMonth(), 1));
  while (c <= d1) { if (+c >= t0) tous.push(+c); c.setUTCMonth(c.getUTCMonth() + 1); }
  if (!tous.length) return [t0];
  const saut = Math.max(1, Math.ceil(tous.length / n));
  return tous.filter((_, i) => i % saut === 0);
}
const libMois = t => { const d = new Date(t); return `${MOIS[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`; };

/**
 * @param {HTMLElement} hote
 * @param {object} o
 *   series:  [{ nom, couleur, points: [{date, v}], pointille, aire }] — la
 *            premiere est la serie principale ;
 *   formatY: (v) => texte d'axe (defaut fmtAxis) ;
 *   formatV: (v) => texte de bulle ;
 *   onPoint: (date) => void, au clic sur un arrete de la serie principale ;
 *   aide:    phrase annoncee aux lecteurs d'ecran.
 */
export function dessinerCourbe(hote, o) {
  if (!hote) return;
  hote._courbe = o;
  _dessiner(hote);
  if (!hote._suivi && 'ResizeObserver' in window) {
    let largeur = hote.clientWidth, attente = 0;
    hote._suivi = new ResizeObserver(() => {
      if (Math.abs(hote.clientWidth - largeur) < 4) return;
      largeur = hote.clientWidth;
      cancelAnimationFrame(attente);
      attente = requestAnimationFrame(() => _dessiner(hote));
    });
    hote._suivi.observe(hote);
  }
}

function _dessiner(hote) {
  const o = hote._courbe;
  const series = (o.series || []).filter(s => s.points?.length);
  hote.innerHTML = '';
  if (!series.length || series[0].points.length < 2) {
    hote.innerHTML = '<p class="courbe-vide">Deux arrêtés au moins sont nécessaires pour tracer une évolution.</p>';
    return;
  }
  const L = Math.max(280, Math.round(hote.clientWidth || 600));
  const formatY = o.formatY || fmtAxis;
  const formatV = o.formatV || (v => String(v));

  const toutes = series.flatMap(s => s.points);
  const t0 = Math.min(...toutes.map(p => ms(p.date))), t1 = Math.max(...toutes.map(p => ms(p.date)));
  const vals = toutes.map(p => p.v).filter(v => v != null);
  const ticks = graduations(Math.min(...vals), Math.max(...vals));
  const y0 = ticks[0], y1 = ticks[ticks.length - 1];
  const X = t => MARGE_G + (t1 === t0 ? 0 : (t - t0) / (t1 - t0)) * (L - MARGE_G - MARGE_D);
  const Y = v => MARGE_H + (1 - (v - y0) / ((y1 - y0) || 1)) * (HAUT - MARGE_H - MARGE_B);

  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'courbe');
  svg.setAttribute('viewBox', `0 0 ${L} ${HAUT}`);
  svg.setAttribute('width', L);
  svg.setAttribute('height', HAUT);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', o.aide || 'Évolution');
  const el = (nom, attrs, texte) => {
    const e = document.createElementNS(NS, nom);
    Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));
    if (texte != null) e.textContent = texte;
    svg.appendChild(e);
    return e;
  };

  ticks.forEach(v => {
    el('line', { class: 'courbe-grille', x1: MARGE_G, x2: L - MARGE_D, y1: Y(v), y2: Y(v) });
    el('text', { class: 'courbe-axe', x: MARGE_G - 8, y: Y(v) + 3.5, 'text-anchor': 'end' }, formatY(v));
  });
  moisAffiches(t0, t1).forEach((t, i, arr) => {
    const dernier = i === arr.length - 1 && X(t) > L - 60;
    el('text', { class: 'courbe-axe', x: X(t), y: HAUT - 8, 'text-anchor': dernier ? 'end' : (i === 0 && X(t) < MARGE_G + 20 ? 'start' : 'middle') }, libMois(t));
  });

  // Les series de comparaison d'abord : la principale passe au-dessus.
  [...series].reverse().forEach((s, i) => {
    const pts = s.points.filter(p => p.v != null).map(p => [X(ms(p.date)), Y(p.v)]);
    if (pts.length < 2) return;
    const d = pts.map(([x, y], k) => `${k ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
    if (s.aire) {
      el('path', { class: 'courbe-aire', d: `${d} L${pts[pts.length - 1][0].toFixed(1)} ${Y(y0).toFixed(1)} L${pts[0][0].toFixed(1)} ${Y(y0).toFixed(1)} Z`,
                   style: `fill:${s.couleur}` });
    }
    el('path', { class: s.pointille ? 'courbe-ligne courbe-ligne--comparaison' : 'courbe-ligne', d, style: `stroke:${s.couleur}` });
  });
  const princ = series[0].points.filter(p => p.v != null);
  const fin = princ[princ.length - 1];
  el('circle', { class: 'courbe-fin', cx: X(ms(fin.date)), cy: Y(fin.v), r: 4, style: `fill:${series[0].couleur}` });

  // ── Curseur : survol, clavier, clic ───────────────────────────────────
  const curseur = el('line', { class: 'courbe-curseur', x1: 0, x2: 0, y1: MARGE_H, y2: HAUT - MARGE_B });
  const marques = series.map(s => el('circle', { class: 'courbe-marque', r: 3.5, style: `fill:${s.couleur}` }));
  curseur.style.display = 'none'; marques.forEach(m => { m.style.display = 'none'; });

  const bulle = document.createElement('div');
  bulle.className = 'courbe-bulle';
  bulle.hidden = true;
  bulle.setAttribute('role', 'status');
  const cadre = document.createElement('div');
  cadre.className = 'courbe-cadre';
  cadre.append(svg, bulle);
  hote.append(cadre);

  const dates = princ.map(p => p.date);
  let actif = -1;
  const montrer = i => {
    actif = Math.max(0, Math.min(dates.length - 1, i));
    const date = dates[actif], x = X(ms(date));
    curseur.setAttribute('x1', x); curseur.setAttribute('x2', x); curseur.style.display = '';
    const lignes = series.map((s, k) => {
      // La valeur de la serie a cette date, ou la derniere connue avant.
      const avant = s.points.filter(p => p.v != null && p.date <= date);
      const p = avant[avant.length - 1];
      const m = marques[k];
      if (!p) { m.style.display = 'none'; return ''; }
      m.setAttribute('cx', X(ms(p.date))); m.setAttribute('cy', Y(p.v)); m.style.display = '';
      return `<span class="courbe-bulle-l"><i style="background:${s.couleur}"></i>${esc(s.nom)}<b>${esc(formatV(p.v, s))}</b></span>`;
    }).join('');
    bulle.innerHTML = `<span class="courbe-bulle-d">${fmtDate(date)}</span>${lignes}`
      + (o.onPoint ? '<span class="courbe-bulle-a">Ouvrir la composition</span>' : '');
    bulle.hidden = false;
    const w = bulle.offsetWidth || 180;
    bulle.style.left = `${Math.min(Math.max(0, x - w / 2), L - w)}px`;
  };
  const cacher = () => {
    curseur.style.display = 'none'; marques.forEach(m => { m.style.display = 'none'; });
    bulle.hidden = true; actif = -1;
  };
  const plusProche = clientX => {
    const r = svg.getBoundingClientRect();
    const x = (clientX - r.left) * (L / r.width);
    let meilleur = 0, ecart = Infinity;
    dates.forEach((d, i) => { const e = Math.abs(X(ms(d)) - x); if (e < ecart) { ecart = e; meilleur = i; } });
    return meilleur;
  };
  svg.addEventListener('pointermove', e => montrer(plusProche(e.clientX)));
  // Un clic donne aussi le focus : seul un focus CLAVIER garde la bulle quand
  // la souris s'en va, sinon elle restait figee jusqu'au clic suivant.
  const auClavier = () => document.activeElement === svg && svg.matches(':focus-visible');
  svg.addEventListener('pointerleave', () => { if (!auClavier()) cacher(); });
  if (o.onPoint) {
    svg.style.cursor = 'pointer';
    svg.addEventListener('click', e => o.onPoint(dates[plusProche(e.clientX)]));
  }
  // Au clavier : le graphe prend le focus, les fleches parcourent les arretes,
  // Entree ouvre la composition. Sans cela le detail n'existait qu'a la souris.
  svg.setAttribute('tabindex', '0');
  svg.addEventListener('focus', () => { if (svg.matches(':focus-visible')) montrer(dates.length - 1); });
  svg.addEventListener('blur', cacher);
  svg.addEventListener('keydown', e => {
    // Les fleches changent d'arrete ailleurs dans l'application : ici elles
    // parcourent le graphe, et seulement lui.
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) e.stopPropagation();
    // Au clavier apres un clic souris : la premiere fleche part du dernier arrete.
    if (actif < 0 && ['ArrowLeft', 'ArrowRight'].includes(e.key)) actif = dates.length;
    if (e.key === 'ArrowLeft') { e.preventDefault(); montrer(actif - 1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); montrer(actif + 1); }
    else if (e.key === 'Home') { e.preventDefault(); montrer(0); }
    else if (e.key === 'End') { e.preventDefault(); montrer(dates.length - 1); }
    else if ((e.key === 'Enter' || e.key === ' ') && o.onPoint && actif >= 0) { e.preventDefault(); o.onPoint(dates[actif]); }
  });
}
