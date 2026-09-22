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
import { fmt } from '../utils.js';

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

  const periodes = (d.periodes || []).filter(p => p.variation || p.apports);
  // Moins de deux periodes ne fait pas une comparaison : on n'affiche rien
  // plutot qu'une barre solitaire qui n'apprend rien.
  if (periodes.length < 2) { carte.style.display = 'none'; return; }
  carte.style.display = '';
  dessiner(periodes);
  legende(d);
}

function dessiner(periodes) {
  const hote = document.getElementById('contribution-chart');
  if (!hote) return;

  // Coordonnees ABSOLUES dans un viewBox proportionne, et surtout PAS de
  // `preserveAspectRatio="none"` : cet etirement deforme le texte autant que
  // les formes, ce qui rendait les libelles illisibles une fois la carte
  // etiree sur toute la largeur.
  // 78 px par periode : en deca, le libelle de valeur deborde sur ses voisins.
  const L = 78 * periodes.length + 30;
  const H = 150, BAS = 30, MARGE = 26;

  const haut = Math.max(...periodes.map(p => Math.max(0, p.apports) + Math.max(0, p.performance)), 0);
  const bas  = Math.min(...periodes.map(p => Math.min(0, p.apports) + Math.min(0, p.performance)), 0);
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
    const total = p.apports + p.performance;
    const yVal = total >= 0 ? hautCumul - 7 : basCumul + 14;
    // Un libelle par barre, en mois abrege : la date complete se chevauchait
    // des quatre periodes.
    const mois = new Date(p.fin + 'T12:00:00')
      .toLocaleDateString('fr-FR', { month: 'short', year: '2-digit' });
    return seg(p.performance, 'var(--chart-1)')
         + seg(p.apports, 'var(--chart-4)')
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
  const a = Math.abs(v);
  return a >= 1000 ? `${signe}${Math.round(a / 1000)} k`
                   : `${signe}${Math.round(a)}`;
}

function legende(d) {
  const hote = document.getElementById('contribution-legend');
  if (!hote) return;
  const part = d.total_variation
    ? Math.round((d.total_performance / d.total_variation) * 100) : null;
  hote.innerHTML = `
    <span><i style="background:var(--chart-4)"></i>Apports
      <b class="num">${fmt(d.total_apports)}</b></span>
    <span><i style="background:var(--chart-1)"></i>Performance
      <b class="num">${fmt(d.total_performance)}</b></span>
    ${part !== null && d.total_variation > 0
      ? `<span class="contrib-part">${part} % de la hausse vient des marchés</span>` : ''}`;
}
