/**
 * Projection du patrimoine net, en trois moteurs de certitude inegale :
 *
 * - le desendettement : le capital que les echeanciers rembourseront, connu a
 *   l'euro pres ;
 * - l'epargne NOUVELLE : l'argent qui entre dans le patrimoine, mesure sur la
 *   hausse des liquidites plus ce qui en part vers les placements ;
 * - le rendement du patrimoine financier : une hypothese, affichee comme telle.
 *
 * Le DCA n'est pas de l'epargne : il investit l'excedent de liquidites, le net
 * ne bouge pas, mais cet argent se met a rapporter — jusqu'a epuisement de
 * l'excedent, quand la repartition atteint sa cible.
 *
 * Les liquidites, l'immobilier et les biens sont tenus a valeur constante : les
 * revaloriser serait un pari de plus, et le montrer en pointille (net sans
 * rendement) dit ce qui ne depend pas des marches.
 */
import { api } from '../api.js';
import { natureDe } from '../categories.js';
import { dessinerCourbe } from '../courbe.js';
import { fmt, parseLocaleNumber } from '../utils.js';

// v2 : l'epargne a change de sens (nouvelle, et non plus versements) ; un
// reglage memorise sous l'ancienne cle y reinjecterait le rythme du DCA.
const CLE = 'financy_projection_v2';
let _ctx = null;
let _mesure = null;
let _crd = null;

function _reglages() {
  try { return JSON.parse(localStorage.getItem(CLE)) || {}; } catch { return {}; }
}
function _memoriser(r) {
  try { localStorage.setItem(CLE, JSON.stringify(r)); } catch { /* session privee */ }
}

/** Restant du total a une date, interpole entre les points de l'echeancier. */
function _crdA(t) {
  if (!_crd?.dates?.length) return 0;
  const ts = _crd.dates.map(d => Date.parse(d));
  if (t <= ts[0]) return _crd.total[0];
  for (let i = 1; i < ts.length; i++) {
    if (t <= ts[i]) {
      const k = (t - ts[i - 1]) / (ts[i] - ts[i - 1]);
      return _crd.total[i - 1] + k * (_crd.total[i] - _crd.total[i - 1]);
    }
  }
  return _crd.total[_crd.total.length - 1];
}

export async function renderProjection(positions, isFamily, net, objectif) {
  const carte = document.getElementById('card-projection');
  if (!carte) return;
  // La projection vise la famille, comme l'objectif : les credits d'une
  // entite ne se partagent pas proprement entre titulaires.
  carte.style.display = isFamily && positions.length ? '' : 'none';
  if (!isFamily || !positions.length) return;
  _ctx = { positions, net, objectif };
  if (_mesure == null || _crd == null) {
    const [e, c] = await Promise.all([
      api('GET', '/api/projection/epargne', null, { silent: true }).catch(() => null),
      api('GET', '/api/prets/projection', null, { silent: true }).catch(() => null),
    ]);
    _mesure = e || { nouvelle: { par_mois: 0, periodes: [] }, dca: { mensuel: 0, excedent: 0 } };
    _crd = c || { dates: [], total: [] };
    _cabler();
  }
  _dessiner();
}

const CHAMPS = {
  epargne:   { id: 'proj-epargne',   defaut: () => Math.round(_mesure.nouvelle.par_mois) },
  aInvestir: { id: 'proj-a-investir', defaut: () => Math.round(_mesure.dca.excedent) },
  dca:       { id: 'proj-dca',       defaut: () => Math.round(_mesure.dca.mensuel) },
  rendement: { id: 'proj-rendement', defaut: () => 3 },
  horizon:   { id: 'proj-horizon',   defaut: () => 10 },
};

function _remplir(r = {}) {
  Object.entries(CHAMPS).forEach(([k, c]) => {
    document.getElementById(c.id).value = String(r[k] ?? c.defaut());
  });
}

function _cabler() {
  _remplir(_reglages());
  const aide = document.getElementById('proj-epargne-aide');
  if (aide) {
    const n = _mesure.nouvelle.periodes || [];
    aide.textContent = `Épargne nouvelle mesurée : ${fmt(_mesure.nouvelle.par_mois)} par mois sur six mois — la hausse `
      + `des liquidités plus ce qui en est parti vers les placements (${n.length} périodes entre arrêtés). `
      + `Le DCA, lui, investit l'excédent de liquidités sur la cible du profil (${fmt(_mesure.dca.excedent)}) `
      + `au rythme de vos versements (${fmt(_mesure.dca.mensuel)} par mois) : il ne crée pas de patrimoine, il le fait travailler.`;
  }
  const maj = () => {
    const r = {};
    Object.entries(CHAMPS).forEach(([k, c]) => { r[k] = parseLocaleNumber(document.getElementById(c.id).value, 0); });
    _memoriser(r);
    _dessiner();
  };
  Object.values(CHAMPS).forEach(c => {
    const el = document.getElementById(c.id);
    el.addEventListener(el.tagName === 'SELECT' ? 'change' : 'input', maj);
  });
  document.getElementById('proj-reinit')?.addEventListener('click', () => {
    _memoriser({});
    _remplir();
    _dessiner();
  });
}

function _dessiner() {
  const { positions, net, objectif } = _ctx;
  const val = id => parseLocaleNumber(document.getElementById(id).value, 0);
  const epargne = val('proj-epargne');
  let aInvestir = Math.max(0, val('proj-a-investir'));
  const dca = Math.max(0, val('proj-dca'));
  const taux = parseLocaleNumber(document.getElementById('proj-rendement').value, 0) / 100;
  const annees = +document.getElementById('proj-horizon').value || 10;
  const financier = positions.filter(p => natureDe(p.category, p.envelope) === 'fin')
    .reduce((s, p) => s + (p.net_attributed || 0), 0);

  const t0 = Date.now();
  const crd0 = _crdA(t0);
  const rm = (1 + taux) ** (1 / 12) - 1;
  const points = [], sansRendement = [];
  let F = financier, epargneCum = 0, dcaCum = 0, finDca = null, atteint = null;
  const parts = {};
  for (let m = 0; m <= annees * 12; m++) {
    if (m > 0) {
      // L'epargne nouvelle s'investit ; le DCA deplace l'excedent de
      // liquidites vers le financier, sans changer le net.
      const deplace = Math.min(dca, aInvestir);
      aInvestir -= deplace; dcaCum += deplace;
      F = F * (1 + rm) + epargne + deplace;
      epargneCum += epargne;
    }
    const t = new Date(t0); t.setMonth(t.getMonth() + m);
    const desendettement = crd0 - _crdA(+t);
    const rendement = F - financier - epargneCum - dcaCum;
    if (!finDca && dcaCum > 0 && aInvestir <= 0) finDca = t;
    const v = net + desendettement + epargneCum + rendement;
    const date = t.toISOString().slice(0, 10);
    if (m % 3 === 0 || m === annees * 12) {
      points.push({ date, v });
      sansRendement.push({ date, v: net + desendettement + epargneCum });
    }
    if (objectif && !atteint && v >= objectif && net < objectif) atteint = date;
    if (m === annees * 12) Object.assign(parts, { desendettement, epargneCum, rendement, v, date });
  }

  dessinerCourbe(document.getElementById('proj-courbe'), {
    series: [
      { nom: 'Net projeté', couleur: 'var(--chart-1)', points, aire: true },
      { nom: 'Sans rendement', couleur: 'var(--text-muted)', points: sansRendement, pointille: true },
    ],
    formatV: v => fmt(v),
    aide: `Projection du patrimoine net sur ${annees} ans`,
  });

  const an = parts.date.slice(0, 4);
  const ligne = (nom, v, note, signe = true) => `<li><span>${nom}</span><b>${
    signe ? (v >= 0 ? '+' : '−') + fmt(Math.abs(v)) : fmt(v)}</b><em>${note}</em></li>`;
  document.getElementById('proj-detail').innerHTML = `
    <p class="proj-total">En ${an} : <b>${fmt(parts.v)}</b>${objectif ? (atteint
      ? ` — objectif de ${fmt(objectif)} atteint en ${new Date(atteint).toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' })}`
      : net >= objectif ? '' : ` — objectif de ${fmt(objectif)} non atteint à cet horizon`) : ''}</p>
    <ul class="proj-moteurs">
      ${ligne('Aujourd’hui', net, 'patrimoine net actuel', false)}
      ${ligne('Désendettement', parts.desendettement, 'capital remboursé selon les échéanciers — certain')}
      ${ligne('Épargne nouvelle', parts.epargneCum, `${fmt(epargne)} par mois — l'argent qui entre`)}
      ${ligne('Rendement', parts.rendement, `${String(taux * 100).replace('.', ',')} % par an sur le financier (${fmt(financier)} aujourd'hui)`
        + (dcaCum ? `, renforcé de ${fmt(dcaCum)} investis en DCA${finDca ? ` jusqu'en ${finDca.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' })}` : ''}` : '')
        + ' — hypothèse')}
    </ul>
    <p class="proj-note">Liquidités, immobilier et biens restent à leur valeur d’aujourd’hui, sans revalorisation ni
      inflation ; montants avant impôt. La courbe en pointillé montre le net sans aucun rendement.</p>`;
}

