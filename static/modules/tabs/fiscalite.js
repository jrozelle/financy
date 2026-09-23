/**
 * « Si vous vendiez tout » : l'impot encore latent sur les plus-values.
 *
 * Le patrimoine brut affiche partout n'est pas ce qu'on toucherait. Entre les
 * deux il y a l'impot sur des gains qui n'existent que sur le papier, et qui
 * ne se materialise qu'a la vente — donc qui n'apparait sur aucun ecran.
 *
 * La carte montre trois chiffres et une reserve. La reserve n'est pas dans le
 * panneau depliable mais sous le montant, en clair : sur ces donnees, l'impot
 * ne porte que sur une part du patrimoine, et un « 800 EUR » presente seul
 * laisserait croire a un patrimoine quasi non taxe. La part couverte est donc
 * la premiere chose qu'on lit apres le montant.
 */
import { S } from '../state.js';
import { api } from '../api.js';
import { fmt, esc, fmtPct } from '../utils.js';

/** Part minimale du patrimoine couverte pour que la carte ait un sens. */
const COUVERTURE_MIN = 0.5;

export async function loadFiscalite() {
  const carte = document.getElementById('fiscalite-card');
  if (!carte) return;
  const p = new URLSearchParams();
  if (S.syntheseDate) p.set('date', S.syntheseDate);
  if (S.syntheseOwner && S.syntheseOwner !== 'Famille') p.set('owner', S.syntheseOwner);

  let d;
  try {
    d = await api('GET', `/api/impot-latent?${p}`, null, { silent: true });
  } catch { carte.style.display = 'none'; return; }

  if (!d || !d.brut) { carte.style.display = 'none'; return; }

  // Sous ce seuil, l'estimation ne porte pas sur assez du patrimoine pour
  // apprendre quoi que ce soit : mieux vaut ne rien montrer qu'un montant
  // qu'on lirait comme un total. La carte reapparait d'elle-meme des que les
  // versements ou les prix de revient sont saisis.
  const couverture = (d.brut - (d.valeur_ecartee || 0)) / d.brut;
  if (couverture < COUVERTURE_MIN) { carte.style.display = 'none'; return; }

  carte.style.display = '';
  carte.innerHTML = rendu(d);
  cabler(carte);
}

function rendu(d) {
  const couvert = d.brut - (d.valeur_ecartee || 0);
  const part = d.brut ? couvert / d.brut : 0;
  const nb = (d.non_calculees || []).length;

  return `
    <div class="card-head">
      <div>
        <h2>Si vous vendiez tout</h2>
        <p class="card-sub">Impôt latent sur les plus-values, au ${
          (d.date || '').split('-').reverse().join('/')}</p>
      </div>
    </div>

    <div class="fisc-chiffres">
      <div class="fisc-bloc">
        <span class="fisc-label">Patrimoine brut</span>
        <span class="fisc-val">${fmt(d.brut)}</span>
      </div>
      <div class="fisc-bloc fisc-bloc--impot">
        <span class="fisc-label">Impôt estimé</span>
        <span class="fisc-val">${d.impot ? '−' + fmt(d.impot) : fmt(0)}</span>
      </div>
      <div class="fisc-bloc fisc-bloc--net">
        <span class="fisc-label">Brut après impôt</span>
        <span class="fisc-val">${fmt(d.net_apres_impot)}</span>
      </div>
    </div>

    <p class="fisc-portee">
      Calculé sur <strong>${fmt(couvert)}</strong> du patrimoine, soit
      ${fmtPct(part * 100, 0)}.${nb ? ` ${nb} enveloppe${nb > 1 ? 's' : ''} sans assiette
      sûre ${nb > 1 ? 'restent' : 'reste'} hors du calcul.` : ''}
      L'ancienneté des assurances-vie et des PEA vient de leur date d'effet ; un
      contrat sans date est supposé mature, au régime le plus favorable.
    </p>

    <button type="button" class="fisc-detail-btn" aria-expanded="false"
            aria-controls="fisc-detail">Détail par enveloppe</button>
    <div class="fisc-detail hidden" id="fisc-detail">
      ${tableau(d)}
      ${ecartees(d)}
      <div id="fisc-contrats"></div>
    </div>`;
}

function tableau(d) {
  if (!d.enveloppes?.length) return '';
  return `
    <table class="fisc-table">
      <thead>
        <tr>
          <th scope="col">Enveloppe</th>
          <th scope="col">Valeur</th>
          <th scope="col">Plus-value</th>
          <th scope="col">Impôt</th>
          <th scope="col">Régime</th>
        </tr>
      </thead>
      <tbody>
        ${d.enveloppes.map(l => `
          <tr>
            <td>${esc(l.enveloppe)}</td>
            <td class="num">${fmt(l.valeur)}</td>
            <td class="num">${l.plus_value ? fmt(l.plus_value) : '—'}</td>
            <td class="num">${l.impot ? fmt(l.impot) : '—'}</td>
            <td class="fisc-regime">
              ${esc(l.motif || '')}
              ${l.reserve ? `<span class="fisc-reserve">${esc(l.reserve)}</span>` : ''}
              ${l.abattement ? `<span class="fisc-reserve">Abattement de ${
                fmt(l.abattement)} appliqué</span>` : ''}
            </td>
          </tr>`).join('')}
      </tbody>
    </table>`;
}

function ecartees(d) {
  if (!d.non_calculees?.length) return '';
  // Une enveloppe ecartee ne disparait pas : elle garde sa valeur et sa raison.
  return `
    <h3 class="fisc-h3">Hors calcul — ${fmt(d.valeur_ecartee)}</h3>
    <ul class="fisc-ecartees">
      ${d.non_calculees.map(e => `
        <li>
          <span class="fisc-ec-nom">${esc(e.enveloppe)}</span>
          <span class="fisc-ec-val">${fmt(e.valeur)}</span>
          <span class="fisc-ec-motif">${esc(e.motif)}</span>
        </li>`).join('')}
    </ul>`;
}

function cabler(carte) {
  const btn = carte.querySelector('.fisc-detail-btn');
  const zone = carte.querySelector('#fisc-detail');
  btn?.addEventListener('click', () => {
    const ouvert = zone.classList.toggle('hidden');
    btn.setAttribute('aria-expanded', String(!ouvert));
    if (!ouvert) contrats(carte);
  });
}

/** Les dates d'effet des contrats, qui fixent leur anciennete fiscale. */
async function contrats(carte) {
  const hote = carte.querySelector('#fisc-contrats');
  if (!hote || hote.dataset.charge) return;
  let d;
  try { d = await api('GET', '/api/contrats', null, { silent: true }); } catch { return; }
  hote.dataset.charge = '1';
  if (!d.contrats?.length) return;
  const date = v => v ? v.split('-').reverse().join('/') : '';
  hote.innerHTML = `
    <h3 class="fisc-h3">Ancienneté des contrats</h3>
    <table class="fisc-table fisc-contrats">
      <thead><tr><th scope="col">Contrat</th><th scope="col">Date d'effet</th><th scope="col">Échéance fiscale</th></tr></thead>
      <tbody>${d.contrats.map((c, i) => `<tr data-i="${i}">
        <td>${esc(c.envelope)} · ${esc(c.owner)}${c.establishment ? ` · ${esc(c.establishment)}` : ''}</td>
        <td><input type="date" class="ref-input" value="${c.date_effet || ''}" aria-label="Date d'effet du contrat ${esc(c.envelope)} de ${esc(c.owner)}"></td>
        <td>${c.maturite ? `${c.seuil_ans} ans le ${date(c.maturite)}${c.mature ? ' — atteint' : ''}`
          : `<span class="fisc-reserve">Sans date : supposé de plus de ${c.seuil_ans} ans</span>`}</td>
      </tr>`).join('')}</tbody>
    </table>
    <button type="button" class="btn btn-secondary btn-sm" id="fisc-contrats-ok">Enregistrer les dates</button>`;
  hote.querySelector('#fisc-contrats-ok').addEventListener('click', async () => {
    const lignes = [...hote.querySelectorAll('tbody tr')].map(tr => {
      const c = d.contrats[+tr.dataset.i];
      return { owner: c.owner, envelope: c.envelope, establishment: c.establishment,
               date_effet: tr.querySelector('input').value || null, numero: c.numero, source: c.source };
    });
    try {
      await api('PUT', '/api/contrats', { contrats: lignes });
      loadFiscalite();
    } catch { /* toast deja affiche */ }
  });
}
