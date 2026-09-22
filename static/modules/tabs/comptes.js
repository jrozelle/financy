/**
 * « Vos comptes » : valeur, apports, performance, frais et rendement.
 *
 * Ces quatre chiffres existaient separement — la valeur dans la synthese, le
 * rendement dans l'onglet Performance, les frais nulle part — et ne se lisaient
 * jamais ensemble. C'est pourtant cote a cote qu'ils disent quelque chose : une
 * assurance-vie a +3,1 % dont 612 EUR de frais n'est pas la meme affaire qu'une
 * assurance-vie a +3,1 % sans frais.
 *
 * Le rendement affiche est le TRI : ce que l'argent a rapporte par an, selon
 * la date ou il a ete verse. C'est la question qu'on se pose devant ses
 * comptes ; le TWR, qui juge le placement independamment des versements, reste
 * dans l'onglet Performance. Les deux viennent de /api/performance, calcules
 * sur les memes flux : on ne recalcule rien ici, on met en regard.
 */
import { S } from '../state.js';
import { api } from '../api.js';
import { fmt, esc, fmtPct } from '../utils.js';
import { estFinancier } from '../categories.js';

export async function loadComptes() {
  const carte = document.getElementById('comptes-card');
  if (!carte) return;
  const owner = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : '';
  let d;
  try {
    d = await api('GET', `/api/performance${owner ? `?owner=${encodeURIComponent(owner)}` : ''}`,
                  null, { silent: true });
  } catch { carte.style.display = 'none'; return; }

  // Un compte plus valorise au dernier arrete n'est plus detenu : le lister
  // avec son solde de cloture le fait passer pour un avoir du jour. Il sort du
  // tableau mais reste compte sous le titre — disparaitre sans un mot serait
  // pire que figurer a tort.
  // Une maison, une voiture ou des parts de SCI ne sont pas des comptes : on
  // ne les alimente pas, on ne les cloture pas, et leur « rendement » n'a pas
  // de sens. Les lister ici remplissait la carte de lignes sans apport ni
  // frais — et parfois d'un montant negatif, qui est une dette nette.
  const tous = (d.groups || []).filter(g => g.value && estFinancier(g.categories));
  const hors = (d.groups || []).length - tous.length;
  const groupes = tous.filter(g => g.status !== 'closed');
  const clotures = tous.length - groupes.length;

  if (!groupes.length) { carte.style.display = 'none'; return; }
  carte.style.display = '';
  carte.innerHTML = rendu(groupes, d, clotures, hors);
}

function rendu(groupes, d, clotures = 0, hors = 0) {
  const total = groupes.reduce((s, g) => s + (g.value || 0), 0);
  const frais = groupes.reduce((s, g) => s + (g.fees || 0), 0);

  return `
    <div class="card-head">
      <div>
        <h2>Vos comptes</h2>
        <p class="card-sub">Ce que votre argent a rapporté, selon la date de vos versements · frais déduits${
          d.first_date ? ` · depuis le ${d.first_date.split('-').reverse().join('/')}` : ''}${
          clotures ? ` · ${clotures} compte${clotures > 1 ? 's' : ''} clôturé${
            clotures > 1 ? 's' : ''}, non listé${clotures > 1 ? 's' : ''}` : ''}${
          hors ? ` · ${hors} ligne${hors > 1 ? 's' : ''} hors placements financiers
            (immobilier, biens, sociétés), à voir dans Répartition` : ''}</p>
      </div>
      <button type="button" class="link-carte" data-tab-switch="performance">Tout voir</button>
    </div>
    <div class="comptes-wrap" tabindex="0" role="region" aria-label="Vos comptes">
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
            <td>${piedRendement(d.global)}</td>
          </tr>
        </tfoot>
      </table>
    </div>`;
}

/** Le TRI annuel ; a defaut — moins de six mois de donnees — le rendement sur
 *  la periode, avec sa duree. Annualiser deux mois fabriquerait un taux qu'on
 *  ne verra jamais, et le presenter comme annuel serait mentir. */
function rendement(g) {
  if (g.tri != null) return { taux: g.tri * 100, suffixe: ' <span class="taux-duree">par an</span>' };
  if (g.tri_periode != null) {
    return { taux: g.tri_periode * 100, suffixe: ` <span class="taux-duree">sur ${g.tri_jours} j</span>` };
  }
  return null;
}

/** Le TRI de l'ensemble des comptes mesurables : un seul taux pour « ce que
 *  mon epargne financiere m'a rapporte ». */
function piedRendement(glob) {
  const r = glob ? rendement(glob) : null;
  if (!r) return '';
  const c = r.taux >= 0 ? 'hausse' : 'baisse';
  return `<span class="taux taux--${c}">${fmtPct(r.taux, 1, true)}</span>${r.suffixe}`;
}

function ligne(g) {
  // Un compte non mesurable garde sa ligne et sa valeur : l'ecarter du calcul
  // ne doit pas l'effacer du patrimoine. Sa raison est dite, pas devinee.
  const r = g.status === 'ok' ? rendement(g) : null;
  const mesurable = r != null;
  const taux = mesurable ? r.taux : null;
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
            ? `<span class="taux taux--${classe}">${fmtPct(taux, 1, true)}</span>${r.suffixe}${
                // Un taux calcule sur un journal incomplet est un taux faux : il
                // doit le dire ici, pas seulement dans l'onglet Performance.
                g.suspect_periods?.length ? ' <span class="taux-alerte">écart inexpliqué : un flux manque au journal ?</span>' : ''}`
            : `<span class="taux taux--neutre">${esc(g.reason || 'hors calcul')}</span>`}</td>
    </tr>`;
}
