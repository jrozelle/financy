/**
 * Répartition : une carte, quatre angles, et le levier rendu visible.
 *
 * Elle remplace quatre cartes qui posaient la MEME question — par categorie,
 * par enveloppe, par poche, par personne. Ce n'etaient pas quatre informations
 * mais un total sous quatre angles, et les separer interdisait de les comparer :
 * il fallait faire l'aller-retour entre deux camemberts eloignes.
 *
 * Deux references coexistent, et c'est deliberement dit a l'ecran :
 * - la LONGUEUR des barres se lit sur le brut, leurs cumuls font 100 % ;
 * - la colonne « % net » se lit sur le net.
 * L'ecart entre les deux EST la dette. Un camembert du net seul l'efface, un
 * camembert du brut cache ce qui revient vraiment au foyer.
 */
import { S } from '../state.js';
import { fmt, esc } from '../utils.js';

const ANGLES = [
  { cle: 'macro',    libelle: 'Poche',     source: 'totals_by_macro' },
  { cle: 'category', libelle: 'Catégorie', source: 'totals_by_category' },
  { cle: 'envelope', libelle: 'Enveloppe', source: 'totals_by_envelope' },
  { cle: 'owner',    libelle: 'Personne',  source: 'totals_by_owner' },
];

let _angle = 'macro';
try { _angle = localStorage.getItem('financy_repartition') || 'macro'; } catch { /* session privee */ }

export function renderRepartition() {
  const hote = document.getElementById('repartition-card');
  if (!hote || !S.synthese) return;

  const angle = ANGLES.find(a => a.cle === _angle) || ANGLES[0];
  const source = S.synthese[angle.source] || {};

  const lignes = Object.entries(source)
    .map(([nom, t]) => ({
      nom,
      gross: t.gross || 0,
      net: t.net || 0,
      debt: t.debt || 0,
    }))
    .filter(l => l.gross || l.net)
    .sort((a, b) => b.gross - a.gross);

  const brut = lignes.reduce((s, l) => s + l.gross, 0);
  const net = lignes.reduce((s, l) => s + l.net, 0);
  const dette = lignes.reduce((s, l) => s + l.debt, 0);

  hote.innerHTML = `
    <div class="card-head">
      <div>
        <h2>Répartition</h2>
        <p class="card-hint">Longueurs cumulées = 100 % du brut ·
          plein : ce qui vous revient · hachuré : financé par emprunt</p>
      </div>
      <div class="seg" role="group" aria-label="Angle de répartition">
        ${ANGLES.map(a => `<button type="button" class="seg-btn" data-angle="${a.cle}"
           aria-pressed="${a.cle === _angle}">${a.libelle}</button>`).join('')}
      </div>
    </div>
    ${lignes.length ? tableau(lignes, brut, net, dette)
                    : '<p class="rep-vide">Aucune position à cet arrêté.</p>'}`;

  hote.querySelectorAll('[data-angle]').forEach(b => {
    b.addEventListener('click', () => {
      _angle = b.dataset.angle;
      try { localStorage.setItem('financy_repartition', _angle); } catch { /* idem */ }
      renderRepartition();
    });
  });
}

function tableau(lignes, brut, net, dette) {
  const pct = (v, total) => total ? (v / total) * 100 : 0;
  const couleur = i => `var(--chart-${(i % 11) + 1})`;

  return `
    <div class="rep-wrap">
      <table class="rep">
        <thead>
          <tr>
            <th scope="col">${esc(ANGLES.find(a => a.cle === _angle).libelle)}</th>
            <th scope="col">Brut</th>
            <th scope="col">Net</th>
            <th scope="col">% brut</th>
            <th scope="col">% net</th>
            <th scope="col">Levier</th>
          </tr>
        </thead>
        <tbody>
          ${lignes.map((l, i) => {
            // Les deux segments se mesurent sur le BRUT TOTAL : ainsi les
            // longueurs de toutes les lignes cumulent exactement 100 %.
            const pNet = pct(l.net, brut).toFixed(2);
            const pDette = pct(l.debt, brut).toFixed(2);
            const levier = l.gross ? (l.debt / l.gross) * 100 : 0;
            return `
            <tr>
              <td>
                <span class="rep-n"><i class="dot" style="background:${couleur(i)}"></i>${esc(l.nom)}</span>
                <span class="rep-bar">
                  <span class="fill" style="width:${pNet}%;background:${couleur(i)}"></span>
                  ${l.debt ? `<span class="fill lev" style="width:${pDette}%;background:${couleur(i)}"></span>` : ''}
                </span>
              </td>
              <td class="num">${fmt(l.gross)}</td>
              <td class="num">${fmt(l.net)}</td>
              <td class="num">${pct(l.gross, brut).toFixed(1)} %</td>
              <td class="num">${pct(l.net, net).toFixed(1)} %</td>
              <td>${levier > 0.05
                    ? `<span class="tag tag-lev">${levier.toFixed(0)} %</span>`
                    : '<span class="rep-none">—</span>'}</td>
            </tr>`;
          }).join('')}
        </tbody>
        <tfoot>
          <tr>
            <td>Total</td>
            <td class="num">${fmt(brut)}</td>
            <td class="num">${fmt(net)}</td>
            <td class="num">100 %</td>
            <td class="num">100 %</td>
            <td>${dette > 0
                  ? `<span class="tag tag-lev-tot">${((dette / brut) * 100).toFixed(1)} %</span>`
                  : '<span class="rep-none">—</span>'}</td>
          </tr>
        </tfoot>
      </table>
    </div>`;
}
