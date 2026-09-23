/**
 * Projection du patrimoine net, en trois moteurs de certitude inegale :
 *
 * - le desendettement : le capital que les echeanciers rembourseront, connu a
 *   l'euro pres ;
 * - l'epargne : la mediane des apports mensuels mesures, modifiable ;
 * - le rendement du patrimoine financier : une hypothese, affichee comme telle.
 *
 * Les liquidites, l'immobilier et les biens sont tenus a valeur constante : les
 * revaloriser serait un pari de plus, et le montrer en pointille (net sans
 * rendement) dit ce qui ne depend pas des marches.
 */
import { api } from '../api.js';
import { natureDe } from '../categories.js';
import { dessinerCourbe } from '../courbe.js';
import { fmt, parseLocaleNumber } from '../utils.js';

const CLE = 'financy_projection';
let _ctx = null;
let _epargneMesuree = null;
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
  if (_epargneMesuree == null || _crd == null) {
    const [e, c] = await Promise.all([
      api('GET', '/api/projection/epargne', null, { silent: true }).catch(() => null),
      api('GET', '/api/prets/projection', null, { silent: true }).catch(() => null),
    ]);
    _epargneMesuree = e?.mediane ?? 0;
    _crd = c || { dates: [], total: [] };
    _cabler(e);
  }
  _dessiner();
}

function _cabler(mesure) {
  const r = _reglages();
  const ep = document.getElementById('proj-epargne');
  const rd = document.getElementById('proj-rendement');
  const hz = document.getElementById('proj-horizon');
  ep.value = r.epargne ?? Math.round(_epargneMesuree);
  rd.value = r.rendement ?? 3;
  hz.value = String(r.horizon ?? 10);
  const aide = document.getElementById('proj-epargne-aide');
  if (aide && mesure?.mois?.length) {
    aide.textContent = `Mesurée : ${fmt(_epargneMesuree)} par mois, médiane des apports des six derniers mois `
      + `(${mesure.mois.map(m => fmt(m.apports)).join(', ')}) — un versement exceptionnel n'est pas extrapolé.`;
  }
  const maj = () => {
    _memoriser({ epargne: parseLocaleNumber(ep.value, 0), rendement: parseLocaleNumber(rd.value, 0), horizon: +hz.value });
    _dessiner();
  };
  [ep, rd].forEach(x => x.addEventListener('input', maj));
  hz.addEventListener('change', maj);
  document.getElementById('proj-reinit')?.addEventListener('click', () => {
    _memoriser({});
    ep.value = Math.round(_epargneMesuree); rd.value = 3; hz.value = '10';
    _dessiner();
  });
}

function _dessiner() {
  const { positions, net, objectif } = _ctx;
  const epargne = parseLocaleNumber(document.getElementById('proj-epargne').value, 0);
  const taux = parseLocaleNumber(document.getElementById('proj-rendement').value, 0) / 100;
  const annees = +document.getElementById('proj-horizon').value || 10;
  const financier = positions.filter(p => natureDe(p.category, p.envelope) === 'fin')
    .reduce((s, p) => s + (p.net_attributed || 0), 0);

  const t0 = Date.now();
  const crd0 = _crdA(t0);
  const rm = (1 + taux) ** (1 / 12) - 1;
  const points = [], sansRendement = [];
  let F = financier, epargneCum = 0, atteint = null;
  const parts = {};
  for (let m = 0; m <= annees * 12; m++) {
    if (m > 0) {
      F = F * (1 + rm) + epargne;     // l'epargne s'investit dans le financier
      epargneCum += epargne;
    }
    const t = new Date(t0); t.setMonth(t.getMonth() + m);
    const desendettement = crd0 - _crdA(+t);
    const rendement = F - financier - epargneCum;
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
      ${ligne('Épargne', parts.epargneCum, `${fmt(epargne)} par mois — votre rythme`)}
      ${ligne('Rendement', parts.rendement, `${String(taux * 100).replace('.', ',')} % par an sur ${fmt(financier)} de financier — hypothèse`)}
    </ul>
    <p class="proj-note">Liquidités, immobilier et biens restent à leur valeur d’aujourd’hui, sans revalorisation ni
      inflation ; montants avant impôt. La courbe en pointillé montre le net sans aucun rendement.</p>`;
}

