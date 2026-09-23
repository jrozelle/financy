/**
 * « Mettre a jour » : tous les soldes d'un arrete, sur un seul ecran.
 *
 * Mettre a jour son patrimoine demandait de dupliquer l'arrete depuis un menu
 * « ••• », puis d'ouvrir une modale d'edition par compte — vingt comptes,
 * vingt modales. C'est pourtant le geste qu'on fait le plus souvent.
 *
 * L'ecran liste chaque position avec son solde precedent et un champ pour le
 * nouveau. Tout s'enregistre d'un coup, en une transaction cote serveur.
 *
 * Trois modes de valorisation, et l'ecran les respecte au lieu de les
 * masquer : une position SAISIE s'edite ; une position a LIGNES DE TITRES est
 * valorisee par les cours (elle s'affiche, sans champ) ; une position liee a
 * une ENTITE tient sa valeur de l'entite, qui s'edite dans sa propre section —
 * c'est la que baisse, chaque mois, le capital restant du d'un credit.
 */
import { S } from './state.js';
import { api } from './api.js';
import { fmt, fmtDate, esc, today, parseLocaleNumber } from './utils.js';
import { toast } from './dialogs.js';

let _prep = null;
let _apres = null;     // injecte : ce qu'il faut recharger une fois enregistre

export function wireMiseAJour(apresEnregistrement) {
  _apres = apresEnregistrement;
  const modal = document.getElementById('maj-modal');
  if (!modal) return;
  modal.querySelectorAll('[data-fermer-maj]').forEach(b => b.addEventListener('click', fermer));
  document.getElementById('maj-date')?.addEventListener('change', e => ouvrir(e.target.value));
  document.getElementById('maj-form')?.addEventListener('submit', e => { e.preventDefault(); enregistrer(); });
  modal.addEventListener('input', e => { if (e.target.matches('[data-maj]')) majLigne(e.target); });
  // Entree passe au champ suivant : on saisit une colonne de soldes d'affilee.
  modal.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.stopPropagation(); fermer(); return; }
    if (e.key !== 'Enter' || !e.target.matches('[data-maj]')) return;
    e.preventDefault();
    const champs = [...modal.querySelectorAll('[data-maj]')];
    const i = champs.indexOf(e.target);
    (champs[i + 1] || document.getElementById('maj-enregistrer')).focus();
  });
}

export async function ouvrir(cible = today()) {
  const modal = document.getElementById('maj-modal');
  if (!modal) return;
  // Un arrete existe a cette date : on le modifie. Sinon on part du dernier
  // arrete qui la precede — ou du plus ancien, pour une date anterieure a tous.
  const dates = S.dates || [];                       // du plus recent au plus ancien
  if (!dates.length) { toast('Aucun arrêté : ajoutez d\u2019abord une position.', 'error'); return; }
  const src = dates.includes(cible) ? cible : (dates.find(d => d < cible) || dates[dates.length - 1]);
  try {
    _prep = await api('GET', `/api/snapshots/update?source=${src}&cible=${cible}`);
  } catch { return; }
  document.getElementById('maj-date').value = cible;
  rendu();
  modal.classList.remove('hidden');
  modal.querySelector('[data-maj]')?.focus();
}

function fermer() {
  document.getElementById('maj-modal')?.classList.add('hidden');
  _prep = null;
}

function rendu() {
  const p = _prep;
  document.getElementById('maj-sous-titre').textContent = p.en_place
    ? `Vous modifiez l’arrêté du ${fmtDate(p.target_date)}.`
    : `Nouvel arrêté, à partir de celui du ${fmtDate(p.source_date)}.`;
  const alerte = document.getElementById('maj-alerte');
  alerte.classList.toggle('hidden', !p.cible_existe);
  alerte.textContent = p.cible_existe
    ? `Un arrêté existe déjà au ${fmtDate(p.target_date)}. Choisissez cette date pour le modifier, ou une autre date.`
    : '';
  document.getElementById('maj-enregistrer').disabled = p.cible_existe;

  // Par titulaire, dans l'ordre ou on les lit ailleurs.
  const parTitulaire = {};
  p.positions.filter(x => x.mode !== 'entite').forEach(x => {
    (parTitulaire[x.owner] ||= []).push(x);
  });
  // Les soldes a saisir d'abord, les lignes valorisees par les cours ensuite :
  // intercalees, elles coupaient la colonne de champs qu'on remplit d'affilee.
  const sections = Object.entries(parTitulaire).map(([qui, lignes]) => {
    const libelles = lignes.map(x => nomBrut(x));
    const doublon = x => libelles.filter(l => l === nomBrut(x)).length > 1;
    const tries = [...lignes].sort((a, b) => (a.mode === 'titres') - (b.mode === 'titres'));
    return `
    <section class="maj-groupe">
      <h3>${esc(qui)}</h3>
      ${tries.map(x => ligne(x, doublon(x))).join('')}
    </section>`;
  }).join('');

  const entites = p.entites.length ? `
    <section class="maj-groupe">
      <h3>Biens et sociétés</h3>
      <p class="maj-aide">Valeur du bien et capital restant dû, pour la part totale de l’entité.</p>
      ${p.entites.map(ligneEntite).join('')}
    </section>` : '';

  document.getElementById('maj-corps').innerHTML = sections + entites;
  // Une dette pre-remplie d'apres l'echeancier est deja une modification :
  // son ecart et le resume se calculent des l'ouverture.
  document.querySelectorAll('#maj-corps [data-maj="debt"][data-entite]').forEach(majLigne);
  majResume();
}

function nomBrut(x) {
  return [x.envelope, x.label || x.establishment].filter(Boolean).join(' · ') || x.category || '—';
}

/** Deux contrats au meme libelle chez le meme titulaire — deux assurances-vie
 *  Boursorama — ne se distinguaient pas : la categorie les departage. */
function nom(x, precis = false) {
  return esc(precis && x.category ? `${nomBrut(x)} · ${x.category}` : nomBrut(x));
}

function ligne(x, precis = false) {
  if (x.mode === 'titres') {
    return `
      <div class="maj-ligne maj-ligne--fixe">
        <span class="maj-nom">${nom(x, precis)}</span>
        <span class="maj-avant">${fmt(x.value)}</span>
        <span class="maj-note">Valorisé par les cours · ${x.holdings_count} ligne${x.holdings_count > 1 ? 's' : ''}</span>
      </div>`;
  }
  const dette = x.debt ? `
        <label class="maj-champ maj-champ--dette">
          <span class="sr-only">Dette de ${nom(x, precis)}</span>
          <input type="text" inputmode="decimal" data-maj="debt" data-id="${x.id}"
                 data-avant="${x.debt}" value="${x.debt}" aria-label="Dette">
          <span class="maj-unite">dette</span>
        </label>` : '';
  return `
      <div class="maj-ligne" data-ligne="${x.id}">
        <span class="maj-nom">${nom(x, precis)}</span>
        <span class="maj-avant">${fmt(x.value)}</span>
        <label class="maj-champ">
          <span class="sr-only">Nouveau solde de ${nom(x, precis)}</span>
          <input type="text" inputmode="decimal" data-maj="value" data-id="${x.id}"
                 data-avant="${x.value}" value="${x.value}" aria-label="Nouveau solde">
        </label>
        <span class="maj-delta" aria-live="polite"></span>
        ${dette}
      </div>`;
}

function ligneEntite(e) {
  // La dette d'une entite a echeancier est pre-remplie d'apres le tableau
  // d'amortissement a la date de l'arrete ; l'ancienne valeur reste lisible.
  const echeancier = e.dette_echeancier;
  const propose = cle => (cle === 'debt' && echeancier != null) ? echeancier : e[cle];
  const champ = (cle, lib) => `
        <label class="maj-champ">
          <span class="maj-unite">${lib}</span>
          <input type="text" inputmode="decimal" data-maj="${cle}" data-entite="${esc(e.name)}"
                 data-avant="${e[cle]}" value="${propose(cle)}" aria-label="${lib} de ${esc(e.name)}">
        </label>`;
  const note = echeancier != null && Math.abs(echeancier - e.debt) >= 0.01
    ? `<span class="maj-echeancier">Dette selon l’échéancier au ${fmtDate(_prep.target_date)} : ${fmt(echeancier)} (précédente : ${fmt(e.debt)})</span>` : '';
  return `
      <div class="maj-ligne maj-ligne--entite" data-ligne="e:${esc(e.name)}">
        <span class="maj-nom">${esc(e.name)}</span>
        ${champ('gross_assets', 'valeur')}
        ${champ('debt', 'dette')}
        <span class="maj-delta" aria-live="polite"></span>
        ${note}
      </div>`;
}

const lire = input => parseLocaleNumber(input.value, NaN);

function majLigne(input) {
  const v = lire(input);
  input.classList.toggle('is-invalide', Number.isNaN(v) || v < 0);
  const ligneEl = input.closest('.maj-ligne');
  const delta = ligneEl?.querySelector('.maj-delta');
  if (delta) {
    // L'ecart de ce qu'on possede : valeur moins dette, avant et apres.
    const net = champ => {
      const n = lire(champ); return Number.isNaN(n) ? Number(champ.dataset.avant) : n;
    };
    let d = 0;
    ligneEl.querySelectorAll('[data-maj]').forEach(c => {
      const signe = c.dataset.maj === 'debt' ? -1 : 1;
      d += signe * (net(c) - Number(c.dataset.avant));
    });
    delta.textContent = Math.abs(d) < 0.005 ? '' : `${d > 0 ? '+' : '−'}${fmt(Math.abs(d))}`;
    delta.className = `maj-delta ${d > 0 ? 'is-hausse' : d < 0 ? 'is-baisse' : ''}`;
  }
  majResume();
}

function modifies() {
  const soldes = {}, entites = {};
  let n = 0, total = 0, invalide = false;
  document.querySelectorAll('#maj-corps [data-maj]').forEach(c => {
    const v = lire(c);
    if (Number.isNaN(v) || v < 0) { invalide = true; return; }
    const avant = Number(c.dataset.avant);
    if (Math.abs(v - avant) < 0.005) return;
    n += 1;
    total += (c.dataset.maj === 'debt' ? -1 : 1) * (v - avant);
    if (c.dataset.id) (soldes[c.dataset.id] ||= {})[c.dataset.maj] = v;
    else {
      const e = (entites[c.dataset.entite] ||= {});
      e[c.dataset.maj] = v;
    }
  });
  // Une entite s'enregistre entiere : valeur ET dette, meme si une seule a bouge.
  Object.keys(entites).forEach(nomE => {
    const src = _prep.entites.find(e => e.name === nomE);
    entites[nomE] = { gross_assets: src.gross_assets, debt: src.debt, ...entites[nomE] };
  });
  return { soldes, entites, n, total, invalide };
}

function majResume() {
  const { n, total, invalide } = modifies();
  const r = document.getElementById('maj-resume');
  if (invalide) { r.textContent = 'Un montant est invalide : un solde est un nombre positif.'; r.className = 'maj-resume is-erreur'; return; }
  r.className = 'maj-resume';
  r.textContent = n
    ? `${n} montant${n > 1 ? 's' : ''} modifié${n > 1 ? 's' : ''} · ${total >= 0 ? '+' : '−'}${fmt(Math.abs(total))} sur le net`
    : (_prep?.en_place ? 'Aucun changement.' : 'Aucun changement : l’arrêté sera recopié tel quel.');
}

async function enregistrer() {
  const { soldes, entites, n, invalide } = modifies();
  if (invalide) return;
  if (!n && _prep.en_place) { fermer(); return; }
  const btn = document.getElementById('maj-enregistrer');
  btn.disabled = true;
  let res;
  try {
    res = await api('POST', '/api/snapshots/update', {
      source_date: _prep.source_date, target_date: _prep.target_date, soldes, entites,
    });
  } catch { btn.disabled = false; return; }
  btn.disabled = false;
  const cible = _prep.target_date;
  fermer();
  await _apres?.(cible);
  const faits = res.positions_maj + res.entites_maj;
  toast(`Arrêté du ${fmtDate(cible)} ${res.cree ? 'créé' : 'mis à jour'}`
        + (faits ? ` · ${faits} montant${faits > 1 ? 's' : ''} enregistré${faits > 1 ? 's' : ''}` : ''));
  if (res.refusees?.length) {
    toast(`${res.refusees.length} montant${res.refusees.length > 1 ? 's' : ''} non enregistré${res.refusees.length > 1 ? 's' : ''} : ${res.refusees[0].motif}`, 'error');
  }
}
