/**
 * « D'où vient la hausse » : épargne versée contre performance des marchés.
 *
 * Le chiffre de variation pose une question a laquelle il ne repond pas. Une
 * hausse de 200 000 EUR peut venir de l'epargne — qui se pilote — ou du marche
 * — qui se subit. Les deux appellent des decisions opposees.
 *
 * Barres empilees dessinees en SVG plutot qu'avec Chart.js : quatre a huit
 * barres a deux segments ne justifient pas une librairie, et le SVG inline suit
 * les variables de theme sans passer par un jeu d'options.
 */
import { S } from '../state.js';
import { api } from '../api.js';
import { fmt, esc, fmtDate } from '../utils.js';
import { isMasked } from '../mask.js';

export async function loadContribution() {
  const carte = document.getElementById('card-contribution');
  if (!carte) return;
  const owner = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : '';
  let d;
  try {
    const q = new URLSearchParams({ limit: '6' });
    if (owner) q.set('owner', owner);
    d = await api('GET', `/api/contribution?${q}`, null, { silent: true });
  } catch { carte.style.display = 'none'; return; }

  // Une periode sans mouvement ni apport n'apporte rien au graphe : elle y
  // occupe une colonne pour n'y montrer qu'un trait a zero.
  const periodes = (d.periodes || [])
    .filter(p => Math.abs(p.variation) > 100 || Math.abs(p.apports) > 100 || Math.abs(p.hors_suivi || 0) > 100);
  // Moins de deux periodes ne fait pas une comparaison : on n'affiche rien
  // plutot qu'une barre solitaire qui n'apprend rien.
  if (periodes.length < 2) { carte.style.display = 'none'; return; }
  carte.style.display = '';
  _periodes = periodes;
  dessiner(periodes);
  legende(d);
  _suivreLargeur();
}

let _periodes = null;
let _suivi = null;

/** Redessine a la largeur courante de la carte. Un seul observateur, pose au
 *  premier affichage ; `requestAnimationFrame` regroupe les rafales d'un
 *  redimensionnement de fenetre en un dessin. */
function _suivreLargeur() {
  const hote = document.getElementById('contribution-chart');
  if (_suivi || !hote || !('ResizeObserver' in window)) return;
  let largeur = hote.clientWidth, attente = 0;
  _suivi = new ResizeObserver(() => {
    if (Math.abs(hote.clientWidth - largeur) < 4 || !_periodes) return;
    largeur = hote.clientWidth;
    cancelAnimationFrame(attente);
    attente = requestAnimationFrame(() => dessiner(_periodes));
  });
  _suivi.observe(hote);
}

function dessiner(periodes) {
  const hote = document.getElementById('contribution-chart');
  if (!hote) return;

  // Le viewBox prend la LARGEUR REELLE de la carte, en pixels : le SVG est
  // alors affiche a l'echelle 1. Un viewBox fixe de 186 unites, etire en
  // `width: 100%` dans une carte de 700 px, multipliait tout par 3,8 — libelles
  // de 42 px, barres monumentales. On redessine donc quand la carte change de
  // taille, plutot que de laisser le navigateur agrandir un dessin trop petit.
  // 78 px par periode au minimum : en deca, le libelle de valeur deborde.
  const L = Math.max(Math.round(hote.clientWidth || 0), 78 * periodes.length + 30);
  const H = 150, BAS = 30, MARGE = 26;

  const parts3 = p => [p.apports, p.performance, p.hors_suivi || 0];
  const haut = Math.max(...periodes.map(p => parts3(p).reduce((t, v) => t + Math.max(0, v), 0)), 0);
  const bas  = Math.min(...periodes.map(p => parts3(p).reduce((t, v) => t + Math.min(0, v), 0)), 0);
  const etendue = (haut - bas) || 1;
  const zero = MARGE + (H - MARGE) * (haut / etendue);
  const ech = v => (Math.abs(v) / etendue) * (H - MARGE);

  const pas = (L - 30) / periodes.length;
  const barre = Math.min(pas * 0.5, 40);

  const parts = periodes.map((p, i) => {
    const cx = 15 + pas * (i + 0.5);
    const x = cx - barre / 2;
    let hautCumul = zero, basCumul = zero;
    const seg = (valeur, couleur) => {
      if (!valeur) return '';
      const h = ech(valeur);
      const y = valeur > 0 ? (hautCumul -= h) : basCumul;
      if (valeur < 0) basCumul += h;
      return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barre.toFixed(1)}" `
           + `height="${Math.max(h, 1).toFixed(1)}" fill="${couleur}" rx="2"/>`;
    };
    // Les segments d'abord : ce sont eux qui font monter `hautCumul`. Lire le
    // sommet avant de les dessiner posait le libelle sur la ligne zero, a
    // l'interieur de la barre.
    const segments = seg(p.performance, 'var(--chart-1)') + seg(p.apports, 'var(--chart-4)')
                   + seg(p.hors_suivi || 0, 'var(--text-muted)');
    const total = p.apports + p.performance + (p.hors_suivi || 0);
    const sommet = Math.min(hautCumul, zero);
    const yVal = sommet - 7;
    // Un libelle par barre, en mois abrege : la date complete se chevauchait
    // des quatre periodes.
    const mois = p.libelle || '';
    return segments
         + `<text x="${cx.toFixed(1)}" y="${(H + 15).toFixed(1)}" text-anchor="middle" `
         + `class="contrib-axe">${mois}</text>`
         + `<text x="${cx.toFixed(1)}" y="${yVal.toFixed(1)}" text-anchor="middle" `
         + `class="contrib-val">${_millier(total)}</text>`;
  }).join('');

  hote.innerHTML = `
    <svg class="contrib-svg" viewBox="0 0 ${L} ${H + BAS}"
         role="img" aria-label="Décomposition de la variation par période : apports et performance">
      <line x1="10" y1="${zero.toFixed(1)}" x2="${L - 10}" y2="${zero.toFixed(1)}" class="contrib-zero"/>
      ${parts}
    </svg>`;
}

/** Arrondi lisible : « +12 k » au-dessus de mille, la valeur exacte en deca —
 *  « +0 k » sur une periode a 400 EUR laisse croire a un mouvement nul. */
function _millier(v) {
  const signe = v >= 0 ? '+' : '−';
  // Ecrit a la main, ce libelle echappait au mode discretion.
  if (isMasked()) return `${signe}•••`;
  const a = Math.abs(v);
  return a >= 1000 ? `${signe}${Math.round(a / 1000)} k`
                   : `${signe}${Math.round(a)}`;
}

function legende(d) {
  const hote = document.getElementById('contribution-legend');
  if (!hote) return;
  const part = d.total_variation
    ? Math.round((d.total_performance / d.total_variation) * 100) : null;
  // Comptes entres ou sortis du suivi sans flux pour l'expliquer : leur valeur
  // n'est pas de la performance, et elle designe souvent un flux oublie. Le
  // detail se lit a l'ecran, compte par compte.
  const comptes = (d.periodes || []).flatMap(p => p.comptes_hors_suivi || []);
  const hors = d.total_hors_suivi || 0;
  hote.innerHTML = `
    <span><i style="background:var(--chart-4)"></i>Apports
      <b class="num">${fmt(d.total_apports)}</b></span>
    <span><i style="background:var(--chart-1)"></i>Performance
      <b class="num">${fmt(d.total_performance)}</b></span>
    ${Math.abs(hors) >= 1 ? `<button type="button" class="contrib-hors" aria-expanded="false" aria-controls="contrib-hors-liste">
      <i style="background:var(--text-muted)"></i>Comptes ajoutés ou retirés <b class="num">${fmt(hors)}</b>
      <span class="contrib-hors-voir">${comptes.length} compte${comptes.length > 1 ? 's' : ''} ▾</span></button>` : ''}
    ${part !== null && d.total_variation > 0
      ? `<span class="contrib-part">${part} % de la hausse vient des marchés</span>` : ''}
    ${comptes.length ? `<ul class="contrib-hors-liste" id="contrib-hors-liste" hidden>
      ${comptes.map(c => `<li><span>${esc(c.compte)}</span><span class="contrib-hors-date">${
        ({ entree: 'apparu', sortie: 'disparu', deplace: 'changé d’enveloppe' })[c.sens] || ''} au ${fmtDate(c.date)}</span><b class="num">${fmt(c.montant)}</b></li>`).join('')}
      <li class="contrib-hors-aide">Aucun versement ni retrait enregistré ne l'explique. Si l'argent venait
        d'un autre compte suivi, il manque un flux : ajoutez-le dans Flux, la part rejoindra les apports.</li>
    </ul>` : ''}`;
  const b = hote.querySelector('.contrib-hors');
  b?.addEventListener('click', () => {
    const ouvert = b.getAttribute('aria-expanded') === 'true';
    b.setAttribute('aria-expanded', String(!ouvert));
    hote.querySelector('#contrib-hors-liste').hidden = ouvert;
  });
}
