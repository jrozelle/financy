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
import { fmt, fmtDate } from '../utils.js';

const H = 150;          // hauteur utile du dessin
const BASE = 22;        // place laissee sous l'axe pour les libelles

export async function loadContribution() {
  const carte = document.getElementById('card-contribution');
  if (!carte) return;
  const owner = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : '';
  let d;
  try {
    d = await api('GET', `/api/contribution${owner ? `?owner=${encodeURIComponent(owner)}` : ''}`,
                  null, { silent: true });
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

  // L'echelle couvre le plus grand empilement ET la plus grande baisse : une
  // periode negative sortirait du cadre si on ne mesurait que les hausses.
  const haut = Math.max(...periodes.map(p => Math.max(0, p.apports) + Math.max(0, p.performance)), 0);
  const bas  = Math.min(...periodes.map(p => Math.min(0, p.apports) + Math.min(0, p.performance)), 0);
  const etendue = (haut - bas) || 1;
  const zero = H * (haut / etendue);
  const ech = v => (Math.abs(v) / etendue) * H;

  const largeur = 100 / periodes.length;
  const barre = Math.min(largeur * 0.52, 9);

  const parts = periodes.map((p, i) => {
    const cx = largeur * (i + 0.5);
    const x = cx - barre / 2;
    let hautCumul = zero, basCumul = zero;
    const seg = (valeur, couleur) => {
      if (!valeur) return '';
      const h = ech(valeur);
      const y = valeur > 0 ? (hautCumul -= h) : basCumul;
      if (valeur < 0) basCumul += h;
      return `<rect x="${x}%" y="${y.toFixed(1)}" width="${barre}%" height="${h.toFixed(1)}"
                    fill="${couleur}" rx="1.5"/>`;
    };
    const total = p.apports + p.performance;
    return seg(p.performance, 'var(--chart-1)')
         + seg(p.apports, 'var(--chart-4)')
         + `<text x="${cx}%" y="${H + 14}" text-anchor="middle" class="contrib-axe">
              ${fmtDate(p.fin).slice(0, 5)}</text>`
         + `<text x="${cx}%" y="${(total >= 0 ? hautCumul - 5 : basCumul + 12).toFixed(1)}"
                  text-anchor="middle" class="contrib-val">${
              (total >= 0 ? '+' : '−') + Math.round(Math.abs(total) / 1000)}k</text>`;
  }).join('');

  hote.innerHTML = `
    <svg viewBox="0 0 100 ${H + BASE}" preserveAspectRatio="none" class="contrib-svg"
         role="img" aria-label="Décomposition de la variation par période, apports et performance">
      <line x1="0" y1="${zero.toFixed(1)}" x2="100" y2="${zero.toFixed(1)}" class="contrib-zero"/>
      ${parts}
    </svg>`;
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
