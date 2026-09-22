/**
 * « Vos comptes » : valeur, apports, performance, frais et rendement.
 *
 * Ces quatre chiffres existaient separement — la valeur dans la synthese, le
 * rendement dans l'onglet Performance, les frais nulle part — et ne se lisaient
 * jamais ensemble. C'est pourtant cote a cote qu'ils disent quelque chose : une
 * assurance-vie a +3,1 % dont 612 EUR de frais n'est pas la meme affaire qu'une
 * assurance-vie a +3,1 % sans frais.
 *
 * La performance affichee est un RENDEMENT PONDERE PAR LE TEMPS, deja calcule
 * par /api/performance. On ne recalcule rien ici : on met en regard.
 */
import { S } from '../state.js';
import { api } from '../api.js';
import { fmt, esc } from '../utils.js';

export async function loadComptes() {
  const carte = document.getElementById('comptes-card');
  if (!carte) return;
  const owner = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : '';
  let d;
  try {
    d = await api('GET', `/api/performance${owner ? `?owner=${encodeURIComponent(owner)}` : ''}`,
                  null, { silent: true });
  } catch { carte.style.display = 'none'; return; }

  const groupes = (d.groups || []).filter(g => g.value);
  if (!groupes.length) { carte.style.display = 'none'; return; }
  carte.style.display = '';
  carte.innerHTML = rendu(groupes, d);
}

function rendu(groupes, d) {
  const total = groupes.reduce((s, g) => s + (g.value || 0), 0);
  const frais = groupes.reduce((s, g) => s + (g.fees || 0), 0);

  return `
    <div class="card-head">
      <div>
        <h2>Vos comptes</h2>
        <p class="card-sub">Rendement pondéré par le temps, frais déduits${
          d.first_date ? ` · depuis le ${d.first_date.split('-').reverse().join('/')}` : ''}</p>
      </div>
      <button type="button" class="link-carte" data-tab-switch="performance">Tout voir</button>
    </div>
    <div class="comptes-wrap">
      <table class="comptes">
        <thead>
          <tr>
            <th scope="col">Compte</th>
            <th scope="col">Valeur</th>
            <th scope="col">Apports</th>
            <th scope="col">Frais</th>
            <th scope="col">Rendement</th>
          </tr>
        </thead>
        <tbody>
          ${groupes.map(ligne).join('')}
        </tbody>
        <tfoot>
          <tr>
            <td>${groupes.length} comptes</td>
            <td class="num">${fmt(total)}</td>
            <td class="num"></td>
            <td class="num">${frais ? fmt(frais) : '—'}</td>
            <td></td>
          </tr>
        </tfoot>
      </table>
    </div>`;
}

function ligne(g) {
  // Un compte non mesurable garde sa ligne et sa valeur : l'ecarter du calcul
  // ne doit pas l'effacer du patrimoine. Sa raison est dite, pas devinee.
  const mesurable = g.status === 'ok' && g.twr != null;
  const taux = mesurable ? g.twr * 100 : null;
  const classe = taux == null ? 'neutre' : taux >= 0 ? 'hausse' : 'baisse';

  return `
    <tr>
      <td>
        <span class="compte-n">${esc(g.label || '')}</span>
      </td>
      <td class="num">${fmt(g.value)}</td>
      <td class="num">${g.flux_net ? fmt(g.flux_net) : '—'}</td>
      <td class="num">${g.fees ? fmt(g.fees) : '—'}</td>
      <td>${mesurable
            ? `<span class="taux taux--${classe}">${taux >= 0 ? '+' : '−'}${
                Math.abs(taux).toFixed(1)} %</span>`
            : `<span class="taux taux--neutre" title="">${esc(g.reason || 'hors calcul')}</span>`}</td>
    </tr>`;
}
