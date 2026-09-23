/**
 * Tresorerie des entites, lue sur leurs releves bancaires : pour une SCI a
 * credit, la mesure du levier. Les loyers couvrent-ils l'echeance, combien
 * les associes remettent-ils, et combien de capital ce complement rembourse.
 */
import { S } from '../state.js';
import { api } from '../api.js';
import { fmt, fmtDate, esc, sortArr, wireSortableTable, updateSortIndicators, parseLocaleNumber } from '../utils.js';
import { toast, promptDialog } from '../dialogs.js';

S.sort.operations = S.sort.operations || { key: 'date', dir: -1 };

let _donnees = null;
const MOIS_COURTS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const moisLib = m => `${MOIS_COURTS[+m.slice(5, 7) - 1]} ${m.slice(0, 4)}`;
const pct = v => v == null ? '—' : `${(v * 100).toFixed(1).replace('.', ',')} %`;
const signe = v => `${v >= 0 ? '+' : '−'}${fmt(Math.abs(v))}`;

export async function loadTresorerie() {
  const hote = document.getElementById('tresorerie-entites');
  if (!hote) return;
  try {
    _donnees = await api('GET', '/api/entites/tresorerie', null, { silent: true });
  } catch { return; }
  const blocs = (_donnees.entites || []).filter(b => b.periode);
  hote.innerHTML = blocs.length ? blocs.map(_bloc).join('') : `
    <p class="text-muted treso-vide">Importez les relevés du compte bancaire d'une SCI ou d'une holding :
      Financy en tire ce que l'entité reçoit, rembourse et coûte, et ce que ses associés y remettent.</p>`;
  blocs.forEach((b, i) => _cabler(hote.querySelector(`[data-treso="${i}"]`), b));
}

function _verdict(b) {
  const i = b.indicateurs, c = b.credit;
  const phrases = [];
  if (i.couverture != null) {
    phrases.push(`Les loyers paient <b>${pct(i.couverture)}</b> de l'échéance du crédit.`);
  }
  if (i.effort_mensuel > 0) {
    phrases.push(`Le reste, et les frais, demandent <b>${fmt(i.effort_mensuel)} par mois</b> aux associés.`);
  }
  // Les frais d'entree des parts : partis des l'achat, ils ne se voient qu'a
  // la revente. Le capital rembourse doit d'abord les rattraper.
  if (b.frais_latents > 0) {
    const annees = c?.capital ? b.frais_latents / c.capital * (12 / b.periode.mois) : null;
    phrases.push(`Au prix de retrait, les parts valent ${fmt(b.parts.valeur_retrait)} pour ${fmt(b.parts.montant_souscrit)}
      payés : <b>${fmt(b.frais_latents)} de frais d'entrée</b> déjà partis${annees
        ? `, soit ${annees.toFixed(1).replace('.', ',')} ans du capital remboursé aujourd'hui` : ''}.`);
  }
  if (c && c.capital) {
    phrases.push(`Sur la période, le crédit a coûté ${fmt(c.interets + c.assurance)} d'intérêts et d'assurance,
      et remboursé <b>${fmt(c.capital)} de capital</b> : c'est de ce capital que la SCI s'enrichit.`);
    const ecart = c.capital + (i.cash_flow_net || 0);
    phrases.push(ecart >= 0
      ? `Le capital remboursé dépasse l'effort de ${fmt(ecart)} : le levier enrichit déjà, avant toute revalorisation des parts.`
      : `L'effort dépasse le capital remboursé de ${fmt(-ecart)} — la part des intérêts que les loyers ne couvrent pas.
         Le montage s'enrichit dès que les parts se revalorisent de plus de
         <b>${(-ecart / (b.parts?.valeur_retrait || b.valeur || 1) * 100).toFixed(2).replace('.', ',')} % par an</b>, avant impôt.`);
  }
  return phrases.join(' ');
}

function _bloc(b, idx) {
  const i = b.indicateurs, c = b.credit, t = b.totaux;
  const nbReleves = new Set(b.operations.map(o => o.source)).size;
  const kpi = (lib, val, sous = '') => `<div class="treso-kpi"><span class="treso-kpi-l">${lib}</span>
    <span class="treso-kpi-v">${val}</span>${sous ? `<span class="treso-kpi-s">${sous}</span>` : ''}</div>`;
  return `
  <section class="treso" data-treso="${idx}" aria-label="Trésorerie de ${esc(b.entite)}">
    <div class="treso-tete">
      <h3>${esc(b.entite)}</h3>
      <span class="text-muted">${moisLib(b.periode.debut)} – ${moisLib(b.periode.fin)}, d'après ${nbReleves} relevé${nbReleves > 1 ? 's' : ''}</span>
    </div>
    <p class="treso-verdict">${_verdict(b)}</p>
    <div class="treso-kpis">
      ${kpi('Revenus', fmt(t.revenu), t.revenu_exceptionnel ? `+ ${fmt(t.revenu_exceptionnel)} exceptionnels` : 'distributions récurrentes')}
      ${kpi('Échéances', fmt(-t.echeance), c ? `dont ${fmt(c.capital)} de capital` : '')}
      ${kpi('Apports des associés', fmt(i.apports), i.capital_par_euro_apporte != null
          ? `${String(i.capital_par_euro_apporte).replace('.', ',')} € de capital remboursé par euro` : '')}
      ${kpi('Rendement distribué', pct(i.rendement), c?.taux ? `crédit à ${String(c.taux).replace('.', ',')} %` : '')}
      ${kpi('Trésorerie', fmt(b.tresorerie), 'tous comptes')}
    </div>
    <div class="courbe-cadre treso-graphe">
      <div class="courbe-bulle" hidden></div>
      ${_graphe(b)}
    </div>
    <div class="courbe-legende">
      <span><i class="treso-pastille" style="background:var(--success)"></i>Revenus</span>
      <span><i class="treso-pastille" style="background:var(--danger)"></i>Échéance et frais</span>
      <span><i class="treso-pastille treso-pastille--apport"></i>Apports des associés</span>
    </div>
    ${_parts(b, idx)}
    ${_fiscal(b, idx)}
    <details class="treso-ops">
      <summary>Les ${b.operations.length} opérations</summary>
      <div class="table-scroll" tabindex="0" role="region" aria-label="Opérations de ${esc(b.entite)}">
        <table class="data-table">
          <thead id="treso-thead-${idx}"><tr>
            <th data-sort="date">Date</th><th data-sort="libelle">Libellé</th>
            <th data-sort="nature">Nature</th><th class="num" data-sort="montant">Montant</th>
            <th data-sort="banque">Compte</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </details>
  </section>`;
}

/** Les parts detenues, valorisees au prix de retrait. Les prix se mettent a
 *  jour a chaque bulletin trimestriel ; sans prix de retrait publie, il est
 *  estime a la souscription moins 10 % de commission. */
function _parts(b, idx) {
  const lignes = b.parts?.lignes || [];
  const champ = (l, k, lib) => `<input type="text" inputmode="decimal" class="ref-input treso-prix" data-k="${k}"
    value="${l[k] ?? ''}" aria-label="${lib} de ${esc(l.nom)}">`;
  return `<details class="treso-parts"${lignes.length ? '' : ' open'}>
    <summary>Parts détenues${lignes.length ? ` : ${fmt(b.parts.valeur_retrait)} au prix de retrait` : ''}</summary>
    <div class="table-scroll" tabindex="0" role="region" aria-label="Parts de ${esc(b.entite)}">
      <table class="data-table" data-parts="${idx}">
        <thead><tr><th>Part</th><th class="num">Nombre</th><th class="num">Prix payé</th>
          <th class="num">Souscription</th><th class="num">Retrait</th><th class="num">Valeur de retrait</th><th>Prix au</th></tr></thead>
        <tbody>${lignes.map(l => `<tr data-nom="${esc(l.nom)}">
          <td>${esc(l.nom)}</td>
          <td class="num">${champ(l, 'parts', 'Nombre de parts')}</td>
          <td class="num">${champ(l, 'montant_souscrit', 'Prix payé')}</td>
          <td class="num">${champ(l, 'prix_souscription', 'Prix de souscription')}</td>
          <td class="num">${champ(l, 'prix_retrait', 'Prix de retrait')}${l.retrait_estime
            ? `<span class="treso-estime">estimé à ${fmt(l.prix_retrait_retenu)}</span>` : ''}</td>
          <td class="num">${l.valeur_retrait != null ? fmt(l.valeur_retrait) : '—'}</td>
          <td><input type="date" class="ref-input" data-k="date_prix" value="${l.date_prix || ''}" aria-label="Date des prix de ${esc(l.nom)}"></td>
        </tr>`).join('')}</tbody>
      </table>
    </div>
    <div class="treso-parts-actions">
      <button type="button" class="btn btn-secondary btn-sm" data-parts-ajouter="${idx}">Ajouter une part</button>
      <button type="button" class="btn btn-primary btn-sm" data-parts-enregistrer="${idx}">Enregistrer les prix</button>
    </div>
  </details>`;
}

/** Impot sur les societes : les exercices clos (d'apres les comptes du
 *  cabinet) et l'estimation de l'exercice en cours, deficits imputes. */
function _fiscal(b, idx) {
  const f = b.fiscal;
  const clos = f?.exercices || [];
  const ligne = e => `<tr><td><input type="date" class="ref-input" data-k="fin" value="${e.fin || ''}" aria-label="Clôture de l'exercice"></td>
    <td class="num"><input type="text" inputmode="decimal" class="ref-input treso-prix" data-k="resultat" value="${e.resultat ?? ''}" aria-label="Résultat fiscal"></td>
    <td><input type="text" class="ref-input" data-k="source" value="${esc(e.source || '')}" aria-label="Source"></td></tr>`;
  const p = f?.projection;
  const resume = f ? `<p class="treso-fiscal">Exercice ${f.annee}, projeté sur l'année : ${fmt(p.revenus)} de revenus,
      ${fmt(p.interets)} d'intérêts et d'assurance, ${fmt(p.frais)} de frais, soit un résultat de
      <b>${p.resultat >= 0 ? '' : '−'}${fmt(Math.abs(p.resultat))}</b>.
      ${f.impot > 0 ? `Impôt estimé : <b>${fmt(f.impot)}</b>, après ${fmt(f.deficit_reportable)} de déficits reportés.`
        : `<b>Pas d'impôt</b> : ${p.resultat < 0 ? 'nouveau déficit' : `bénéfice absorbé par les déficits antérieurs`},
           ${fmt(f.deficit_apres)} de déficits restant à reporter.`}
      Estimation en trésorerie, le cabinet travaille en droits constatés.</p>` : '';
  return `<details class="treso-parts treso-fisc">
    <summary>Impôt sur les sociétés${f ? ` : ${f.impot > 0 ? fmt(f.impot) + ' estimés' : 'pas d’impôt estimé'} en ${f.annee}` : ''}</summary>
    ${resume}
    <div class="table-scroll" tabindex="0" role="region" aria-label="Exercices clos de ${esc(b.entite)}">
      <table class="data-table" data-exercices="${idx}">
        <thead><tr><th>Exercice clos le</th><th class="num">Résultat fiscal</th><th>Source</th></tr></thead>
        <tbody>${clos.map(ligne).join('')}${ligne({})}</tbody>
      </table>
    </div>
    <p class="treso-note">Un résultat négatif est un déficit, reporté sur les bénéfices suivants.</p>
    <div class="treso-parts-actions">
      <button type="button" class="btn btn-primary btn-sm" data-exercices-enregistrer="${idx}">Enregistrer les exercices</button>
    </div>
  </details>`;
}

/** Douze colonnes : les entrees au-dessus de zero, les sorties en dessous. */
function _graphe(b) {
  const W = 640, H = 170, BAS = 0, n = b.mensuel.length;
  const haut = m => m.revenu + m.revenu_exceptionnel;
  const bas = m => -(m.echeance + m.frais);
  const max = Math.max(1, ...b.mensuel.map(m => Math.max(haut(m), bas(m), m.apport)));
  const zero = (H - BAS) / 2;
  const k = (zero - 6) / max;
  const col = W / n, larg = Math.min(26, col * .55);
  const barres = b.mensuel.map((m, i) => {
    const x = i * col + (col - larg) / 2;
    const hr = m.revenu * k, he = m.revenu_exceptionnel * k, hs = bas(m) * k;
    const ya = zero - m.apport * k;
    return `<g class="treso-col" data-i="${i}" tabindex="0" role="button"
        aria-label="${moisLib(m.mois)} : revenus ${fmt(haut(m))}, sorties ${fmt(bas(m))}, apports ${fmt(m.apport)}">
      <rect class="treso-zone" x="${i * col}" y="0" width="${col}" height="${H - BAS}"/>
      <rect x="${x}" y="${zero - hr}" width="${larg}" height="${hr}" fill="var(--success)" rx="2"/>
      ${he ? `<rect x="${x}" y="${zero - hr - he}" width="${larg}" height="${he}" fill="var(--success)" fill-opacity=".45" rx="2"/>` : ''}
      <rect x="${x}" y="${zero}" width="${larg}" height="${hs}" fill="var(--danger)" fill-opacity=".85" rx="2"/>
      ${m.apport ? `<line class="treso-apport" x1="${x - 3}" x2="${x + larg + 3}" y1="${ya}" y2="${ya}" vector-effect="non-scaling-stroke"/>` : ''}
    </g>`;
  }).join('');
  // Etire en largeur, hauteur fixe : les mois vont dessous en HTML, a taille
  // de texte constante — dans le SVG, ils grossissaient avec l'ecran.
  return `<svg class="courbe treso-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="group" aria-label="Flux mensuels">
    <line class="courbe-grille" x1="0" x2="${W}" y1="${zero}" y2="${zero}" vector-effect="non-scaling-stroke"/>${barres}</svg>
    <div class="treso-mois" style="grid-template-columns:repeat(${n},1fr)">${b.mensuel.map(m =>
      `<span>${MOIS_COURTS[+m.mois.slice(5, 7) - 1]}</span>`).join('')}</div>`;
}

function _cabler(sec, b) {
  // Bulle : detail du mois au survol, au focus ou au toucher.
  const cadre = sec.querySelector('.treso-graphe');
  const bulle = cadre.querySelector('.courbe-bulle');
  const svg = cadre.querySelector('svg');
  const ligne = (couleur, nom, v) => `<span class="courbe-bulle-l"><i style="background:${couleur}"></i>${nom}<b>${signe(v)}</b></span>`;
  const montrer = g => {
    const m = b.mensuel[+g.dataset.i];
    const net = m.revenu + m.revenu_exceptionnel + m.echeance + m.frais;
    bulle.innerHTML = `<span class="courbe-bulle-d">${moisLib(m.mois)}</span>`
      + ligne('var(--success)', 'Revenus', m.revenu)
      + (m.revenu_exceptionnel ? ligne('var(--success)', 'Exceptionnels', m.revenu_exceptionnel) : '')
      + ligne('var(--danger)', 'Échéance', m.echeance)
      + (m.frais ? ligne('var(--danger)', 'Frais', m.frais) : '')
      + `<span class="courbe-bulle-l contrib-bulle-total">Solde du mois<b>${signe(net)}</b></span>`
      + ligne('var(--text)', 'Apports des associés', m.apport);
    bulle.hidden = false;
    const r = g.getBoundingClientRect(), c = cadre.getBoundingClientRect();
    const w = bulle.offsetWidth || 200;
    bulle.style.left = `${Math.max(0, Math.min(r.left - c.left + r.width / 2 - w / 2, c.width - w))}px`;
    svg.querySelectorAll('.treso-col').forEach(x => x.classList.toggle('is-actif', x === g));
  };
  const cacher = () => { bulle.hidden = true; svg.querySelectorAll('.is-actif').forEach(x => x.classList.remove('is-actif')); };
  svg.addEventListener('pointerover', e => { const g = e.target.closest('.treso-col'); if (g) montrer(g); });
  svg.addEventListener('pointerleave', cacher);
  svg.addEventListener('focusin', e => { const g = e.target.closest('.treso-col'); if (g) montrer(g); });
  svg.addEventListener('focusout', cacher);

  // Parts : ajout d'une ligne, enregistrement de l'ensemble.
  sec.querySelector('[data-parts-ajouter]')?.addEventListener('click', async () => {
    const nom = (await promptDialog('Nom de la part', { placeholder: 'ex. : Immorente', confirmText: 'Ajouter' }))?.trim();
    if (!nom) return;
    const tr = document.createElement('tr');
    tr.dataset.nom = nom;
    tr.innerHTML = `<td>${esc(nom)}</td>` + ['parts', 'montant_souscrit', 'prix_souscription', 'prix_retrait'].map(k =>
      `<td class="num"><input type="text" inputmode="decimal" class="ref-input treso-prix" data-k="${k}" aria-label="${k}"></td>`).join('')
      + '<td class="num">—</td><td><input type="date" class="ref-input" data-k="date_prix" aria-label="Date des prix"></td>';
    sec.querySelector('[data-parts] tbody').appendChild(tr);
  });
  sec.querySelector('[data-parts-enregistrer]')?.addEventListener('click', async () => {
    const lignes = [...sec.querySelectorAll('[data-parts] tbody tr')].map(tr => {
      const l = { nom: tr.dataset.nom };
      tr.querySelectorAll('[data-k]').forEach(i => {
        l[i.dataset.k] = i.dataset.k === 'date_prix' ? (i.value || null)
          : (i.value.trim() === '' ? null : parseLocaleNumber(i.value, null));
      });
      return l;
    });
    try {
      await api('PUT', `/api/entites/${encodeURIComponent(b.entite)}/parts`, { parts: lignes });
      toast('Prix enregistrés : la prochaine mise à jour proposera la valeur au prix de retrait', 'success');
      loadTresorerie();
    } catch { /* toast deja affiche */ }
  });

  sec.querySelector('[data-exercices-enregistrer]')?.addEventListener('click', async () => {
    const exercices = [...sec.querySelectorAll('[data-exercices] tbody tr')].map(tr => {
      const v = k => tr.querySelector(`[data-k="${k}"]`).value.trim();
      return { fin: v('fin'), resultat: v('resultat') === '' ? null : parseLocaleNumber(v('resultat'), null), source: v('source') || null };
    }).filter(e => e.fin);
    try {
      await api('PUT', `/api/entites/${encodeURIComponent(b.entite)}/exercices`, { exercices });
      toast('Exercices enregistrés', 'success');
      loadTresorerie();
    } catch { /* toast deja affiche */ }
  });

  // Operations : triables, et reclassables quand le libelle a trompe le tri.
  const idx = sec.dataset.treso;
  const tbody = sec.querySelector('.treso-ops tbody');
  const rendre = () => {
    const { key, dir } = S.sort.operations;
    tbody.innerHTML = sortArr(b.operations, key, dir).map(o => `<tr>
      <td>${fmtDate(o.date)}</td>
      <td class="treso-lib">${esc(o.libelle)}</td>
      <td><select class="filter-select" data-op="${o.id}" aria-label="Nature de l'opération">
        ${Object.entries(_donnees.natures).map(([k, v]) => `<option value="${k}"${k === o.nature ? ' selected' : ''}>${esc(v)}</option>`).join('')}
      </select></td>
      <td class="num ${o.montant >= 0 ? 'pos' : 'neg'}">${signe(o.montant)}</td>
      <td class="text-muted">${esc(o.banque || '')}</td>
    </tr>`).join('');
    updateSortIndicators(`treso-thead-${idx}`, 'operations');
  };
  wireSortableTable(`treso-thead-${idx}`, 'operations', rendre);
  rendre();
  tbody.addEventListener('change', async e => {
    const sel = e.target.closest('select[data-op]');
    if (!sel) return;
    try {
      await api('PATCH', `/api/entites/operations/${sel.dataset.op}`, { nature: sel.value });
      toast('Opération reclassée', 'success');
      const ouvert = sec.querySelector('.treso-ops').open;
      await loadTresorerie();
      if (ouvert) document.querySelector(`[data-treso="${idx}"] .treso-ops`)?.setAttribute('open', '');
    } catch { /* toast deja affiche */ }
  });
}

// ─── Import de releves ───────────────────────────────────────────────────────

async function _envoyer(fichier, etape, entite) {
  const fd = new FormData();
  fd.append('file', fichier);
  if (entite) fd.append('entity', entite);
  const meta = document.querySelector('meta[name="csrf-token"]');
  const r = await fetch(`/api/entites/releves?step=${etape}`, { method: 'POST', body: fd,
    headers: meta ? { 'X-CSRF-Token': meta.content } : {} });
  const d = await r.json().catch(() => null);
  if (!r.ok) throw new Error(d?.error || `Import refusé (${r.status})`);
  return d;
}

let _fichiers = [];

export function initTresorerie() {
  const input = document.getElementById('treso-fichiers');
  if (!input || input.dataset.cable) return;
  input.dataset.cable = '1';
  document.getElementById('treso-importer')?.addEventListener('click', () => input.click());
  input.addEventListener('change', async () => {
    const hote = document.getElementById('treso-apercu');
    const lus = [], refus = [];
    for (const f of input.files) {
      try { lus.push({ f, r: (await _envoyer(f, 'preview')).releve }); }
      catch (e) { refus.push(`${f.name} : ${e.message}`); }
    }
    input.value = '';
    _fichiers = lus;
    if (!lus.length) { toast(refus[0] || 'Aucun relevé lisible', 'error'); return; }
    const proposee = lus.find(x => x.r.entite_proposee)?.r.entite_proposee;
    const options = (S.entities || []).map(e =>
      `<option value="${esc(e.name)}"${e.name === proposee ? ' selected' : ''}>${esc(e.name)}</option>`).join('');
    const n = lus.reduce((s, x) => s + x.r.operations, 0);
    hote.innerHTML = `
      <p><b>${lus.length} relevé${lus.length > 1 ? 's' : ''} vérifié${lus.length > 1 ? 's' : ''}</b>, ${n} opérations :
        chaque relevé redonne bien son solde final.</p>
      <ul class="treso-apercu-liste">${lus.map(x => `<li>${esc(x.r.banque)} · ${fmtDate(x.r.debut)} → ${fmtDate(x.r.fin)} ·
        ${x.r.operations} opération${x.r.operations > 1 ? 's' : ''} · solde ${fmt(x.r.solde_final)}</li>`).join('')}</ul>
      ${refus.length ? `<p class="import-alerte">Écartés : ${refus.map(esc).join(' ; ')}</p>` : ''}
      <div class="prets-apercu-champs">
        <label>Compte de l'entité <select id="treso-entite" class="filter-select">${options}</select></label>
        <button type="button" class="btn btn-primary btn-sm" id="treso-enregistrer">Enregistrer</button>
        <button type="button" class="btn btn-secondary btn-sm" id="treso-annuler">Annuler</button>
      </div>`;
    hote.hidden = false;
    document.getElementById('treso-annuler').onclick = () => { hote.hidden = true; hote.innerHTML = ''; _fichiers = []; };
    document.getElementById('treso-enregistrer').onclick = async () => {
      const entite = document.getElementById('treso-entite').value;
      let ajoutees = 0, deja = 0;
      try {
        for (const x of _fichiers) {
          const d = await _envoyer(x.f, 'commit', entite);
          ajoutees += d.ajoutees; deja += d.deja;
        }
      } catch (e) { toast(e.message, 'error'); return; }
      hote.hidden = true; hote.innerHTML = ''; _fichiers = [];
      toast(`${ajoutees} opération${ajoutees > 1 ? 's' : ''} ajoutée${ajoutees > 1 ? 's' : ''}`
        + (deja ? `, ${deja} déjà connue${deja > 1 ? 's' : ''}` : ''), 'success');
      loadTresorerie();
    };
  });
}
