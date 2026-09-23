/**
 * Credits : les prets et leurs tableaux d'amortissement.
 *
 * Un echeancier dit la dette a toute date : la carte en tire la projection du
 * capital restant du jusqu'au dernier remboursement, la mensualite et les
 * interets qui restent a payer, et compare la dette saisie de chaque entite a
 * ce que l'echeancier prevoit — sans jamais la corriger en silence.
 */
import { S } from '../state.js';
import { api } from '../api.js';
import { fmt, fmtDate, esc, today, fmtPct, fmtAxis, parseLocaleNumber } from '../utils.js';
import { toast, confirmDialog } from '../dialogs.js';
import { dessinerCourbe } from '../courbe.js';

const COULEURS = ['var(--nature-immo)', 'var(--nature-liq)', 'var(--nature-biens)', 'var(--nature-fin)'];
let _cable = false;

export async function loadPrets() {
  const carte = document.getElementById('prets-carte');
  if (!carte) return;
  _cabler();
  let res, pj, echeancier, cal;
  try {
    [res, pj, echeancier, cal] = await Promise.all([
      api('GET', '/api/prets', null, { silent: true }),
      api('GET', '/api/prets/projection', null, { silent: true }),
      api('GET', `/api/prets/dettes?date=${today()}`, null, { silent: true }),
      api('GET', '/api/prets/calendrier', null, { silent: true }),
    ]);
  } catch { return; }
  const prets = res.prets || [];
  _kpi(prets);
  _prochaines(cal?.prochaines || [], prets);
  _annees(cal?.annees || []);
  document.getElementById('prets-liste').innerHTML = prets.length ? _liste(prets) : `
    <p class="text-muted prets-vide">Aucun prêt. Importez le tableau d'amortissement de votre banque (PDF Caisse d'Épargne
      ou Arkéa) : la dette de l'entité se projettera d'elle-même.</p>`;
  _courbe(pj, prets);
  _ecarts(echeancier, prets);
}

function _liste(prets) {
  const options = sel => ['<option value="">Aucune entité</option>',
    ...(S.entities || []).map(e => `<option value="${esc(e.name)}"${e.name === sel ? ' selected' : ''}>${esc(e.name)}</option>`)].join('');
  const dans = fin => {
    const mois = Math.round((Date.parse(fin) - Date.now()) / (30.44 * 864e5));
    return mois <= 0 ? 'remboursé' : mois < 24 ? `dans ${mois} mois` : `dans ${Math.round(mois / 12)} ans`;
  };
  return `<div class="prets-liste">${prets.map((p, i) => {
    const part = p.montant ? Math.max(0, Math.min(100, (p.rembourse / p.montant) * 100)) : 0;
    return `
    <div class="pret" data-id="${p.id}">
      <div class="pret-nom">
        <i style="background:${COULEURS[i % COULEURS.length]}"></i>
        <span><b>${esc(p.libelle)}</b><small>${esc(p.preteur || '')}${p.taux ? ` · ${String(p.taux).replace('.', ',')} %` : ''}
          · ${fmt(p.montant)} empruntés</small></span>
      </div>
      <label class="pret-entite"><span class="sr-only">Entité de ${esc(p.libelle)}</span>
        <select class="filter-select" data-pret-entite="${p.id}">${options(p.entity)}</select></label>
      <div class="pret-chiffre"><small>Restant dû</small><b>${fmt(p.crd)}</b></div>
      <div class="pret-chiffre"><small>${p.differe ? 'Échéance du mois' : 'Mensualité'}</small><b>${
        p.differe ? fmt(p.echeance_du_mois) : (p.mensualite != null ? fmt(p.mensualite) : '—')}</b>${
        p.differe ? `<small class="pret-differe">différé ${p.differe.type} jusqu'au ${fmtDate(p.differe.jusqu_au)}${
          p.mensualite ? `, puis ${fmt(p.mensualite)}` : ''}</small>` : ''}</div>
      <div class="pret-chiffre"><small>Fin</small><b>${fmtDate(p.fin)}</b><small>${dans(p.fin)}</small></div>
      <div class="pret-chiffre"><small>Intérêts restants</small><b>${fmt(p.interets_restants)}</b></div>
      <div class="pret-avancement" aria-label="${fmtPct(part, 0)} remboursé">
        <span class="pret-barre"><span style="width:${part.toFixed(1)}%"></span></span>
        <small>${fmtPct(part, 0)} remboursé</small>
      </div>
      <button type="button" class="btn-icon del" data-pret-suppr="${p.id}" aria-label="Supprimer ${esc(p.libelle)}">Supprimer</button>
      ${_solder(p)}
    </div>`;
  }).join('')}</div>`;
}

/** Solder aujourd'hui : le cout des IRA face aux interets evites. Le taux,
 *  quand le tableau ne l'imprime pas, est deduit de l'echeancier — et dit. */
function _solder(p) {
  if (!p.crd) return '';
  const taux = p.taux_retenu ? `${String(p.taux_retenu).replace('.', ',')} %${p.taux_deduit ? ' (déduit de l’échéancier)' : ''}` : 'taux inconnu';
  const gain = p.interets_restants - p.ira;
  return `<div class="pret-solder">
      <span>Solder aujourd'hui : <b>${fmt(p.crd + p.ira)}</b>, dont <b>${fmt(p.ira)}</b> d'IRA
        ${p.ira ? `(plafond légal : 6 mois d'intérêts à ${taux}, ou 3 % du restant dû)` : '(le contrat y renonce)'}
        — évite ${fmt(p.interets_restants)} d'intérêts et d'assurance à venir${gain > 0 ? `, soit ${fmt(gain)} de moins au total` : ''}.</span>
      <label class="pret-ira"><span class="sr-only">IRA de ${esc(p.libelle)}</span>
        <select class="filter-select" data-pret-ira="${p.id}">
          <option value="legale"${(p.ira_mode || p.ira_contrat) === 'aucune' ? '' : ' selected'}>IRA au plafond légal</option>
          <option value="aucune"${(p.ira_mode || p.ira_contrat) === 'aucune' ? ' selected' : ''}>Contrat sans IRA</option>
        </select></label>
    </div>`;
}

function _kpi(prets) {
  const hote = document.getElementById('credits-kpi');
  if (!hote) return;
  if (!prets.length) { hote.innerHTML = ''; return; }
  const crd = prets.reduce((t, p) => t + p.crd, 0);
  const mois = prets.reduce((t, p) => t + (p.echeance_du_mois || 0), 0);
  const interets = prets.reduce((t, p) => t + p.interets_restants, 0);
  const fin = prets.map(p => p.fin).sort().pop();
  const tuile = (lib, val, sous = '') => `<div class="kpi-card"><div class="kpi-label">${lib}</div>
    <div class="kpi-value">${val}</div>${sous ? `<div class="kpi-sub">${sous}</div>` : ''}</div>`;
  hote.innerHTML = `<div class="kpi-grid credits-grille">
    ${tuile('Restant dû', fmt(crd), `${prets.length} crédit${prets.length > 1 ? 's' : ''}`)}
    ${tuile('Échéances du mois', fmt(mois), 'assurance comprise')}
    ${tuile('Intérêts restants', fmt(interets), 'et assurance, jusqu’au bout')}
    ${tuile('Libre de dettes le', fmtDate(fin), '')}
  </div>`;
}

function _prochaines(liste, prets) {
  const hote = document.getElementById('credits-prochaines');
  if (!hote) return;
  if (!liste.length) { hote.innerHTML = '<p class="text-muted">Aucune échéance à venir.</p>'; return; }
  const couleur = id => COULEURS[prets.findIndex(p => p.id === id) % COULEURS.length];
  hote.innerHTML = `<table class="data-table credits-table"><thead><tr>
      <th>Date</th><th>Crédit</th><th class="num">Capital</th><th class="num">Intérêts</th><th class="num">Total</th></tr></thead>
    <tbody>${liste.map(e => `<tr><td>${fmtDate(e.date)}</td>
      <td><i class="pastille" style="background:${couleur(e.pret_id)}"></i>${esc(e.pret || '')}</td>
      <td class="num">${e.capital < 0 ? `<span class="text-muted">différé (+${fmt(-e.capital)})</span>` : fmt(e.capital)}</td>
      <td class="num">${fmt(e.interets + e.assurance)}</td>
      <td class="num"><b>${fmt(Math.max(e.capital, 0) + e.interets + e.assurance)}</b></td></tr>`).join('')}</tbody></table>`;
}

function _annees(liste) {
  const hote = document.getElementById('credits-annees');
  if (!hote) return;
  if (!liste.length) { hote.innerHTML = ''; return; }
  hote.innerHTML = `<table class="data-table credits-table"><thead><tr>
      <th>Année</th><th class="num">Capital remboursé</th><th class="num">Intérêts et assurance</th><th class="num">Restant dû au 31/12</th></tr></thead>
    <tbody>${liste.map(a => `<tr><td>${a.annee}</td><td class="num">${fmt(a.capital)}</td>
      <td class="num">${fmt(a.interets + a.assurance)}</td><td class="num"><b>${fmt(a.crd_fin)}</b></td></tr>`).join('')}</tbody></table>`;
}

function _courbe(pj, prets) {
  const hote = document.getElementById('prets-courbe');
  const legende = document.getElementById('prets-legende');
  if (!pj?.dates?.length || !prets.length) { hote.innerHTML = ''; legende.innerHTML = ''; return; }
  const pts = vals => pj.dates.map((d, i) => ({ date: d, v: vals[i] }));
  const series = [{ nom: 'Total restant dû', couleur: 'var(--primary)', points: pts(pj.total), aire: true }];
  if (pj.prets.length > 1) {
    pj.prets.forEach((p, i) => series.push({
      nom: p.libelle, couleur: COULEURS[prets.findIndex(x => x.id === p.id) % COULEURS.length],
      points: pts(p.points), pointille: true,
    }));
  }
  dessinerCourbe(hote, {
    series, formatY: fmtAxis, formatV: v => fmt(v),
    aide: `Capital restant dû : ${fmt(pj.total[0])} aujourd'hui, soldé le ${fmtDate(pj.dates[pj.dates.length - 1])}.`,
  });
  // Les jalons : la fin de chaque pret, dans l'ordre.
  legende.innerHTML = [...pj.prets].sort((a, b) => a.fin.localeCompare(b.fin)).map(p =>
    `<span><i style="background:${COULEURS[prets.findIndex(x => x.id === p.id) % COULEURS.length]}"></i>${esc(p.libelle)} soldé le <b>${fmtDate(p.fin)}</b></span>`).join('');
}

/** Dette saisie de chaque entite contre son echeancier, aujourd'hui. Une
 *  echeance d'ecart est normale (saisie avant ou apres le prelevement du mois) ;
 *  au-dela, on le dit. */
function _ecarts(echeancier, prets) {
  const hote = document.getElementById('prets-ecarts');
  const lignes = Object.entries(echeancier || {}).map(([nom, prevu]) => {
    const ent = (S.entities || []).find(e => e.name === nom);
    if (!ent) return '';
    const mensu = prets.filter(p => p.entity === nom).reduce((t, p) => t + (p.mensualite || 0), 0);
    const ecart = (ent.debt || 0) - prevu;
    const ok = Math.abs(ecart) <= Math.max(mensu, 1);
    return `<li class="${ok ? '' : 'pret-ecart'}"><b>${esc(nom)}</b> : dette saisie ${fmt(ent.debt || 0)}, échéancier aujourd'hui ${fmt(prevu)}${
      ok ? (Math.abs(ecart) >= 1 ? ' — une échéance d’écart, normal' : ' — identiques')
         : ` — <strong>écart de ${fmt(Math.abs(ecart))}</strong>, plus d'une mensualité : un prêt manque ou la dette est à revoir`}</li>`;
  }).filter(Boolean);
  hote.innerHTML = lignes.length ? `<ul class="prets-ecarts">${lignes.join('')}</ul>` : '';
}

function _cabler() {
  if (_cable) return;
  _cable = true;
  const carte = document.getElementById('prets-carte');
  carte.addEventListener('change', async e => {
    const ira = e.target.closest('[data-pret-ira]');
    if (ira) {
      try { await api('PATCH', `/api/prets/${ira.dataset.pretIra}`, { ira: ira.value }); loadPrets(); } catch {}
      return;
    }
    const sel = e.target.closest('[data-pret-entite]');
    if (!sel) return;
    try {
      await api('PATCH', `/api/prets/${sel.dataset.pretEntite}`, { entity: sel.value || null });
      toast('Prêt rattaché', 'success');
      loadPrets();
    } catch {}
  });
  carte.addEventListener('click', async e => {
    const b = e.target.closest('[data-pret-suppr]');
    if (b) {
      const ok = await confirmDialog('Supprimer ce prêt ?', 'Son échéancier disparaît ; la dette des arrêtés déjà saisis ne change pas.');
      if (!ok) return;
      try { await api('DELETE', `/api/prets/${b.dataset.pretSuppr}`); loadPrets(); } catch {}
      return;
    }
    if (e.target.closest('#prets-annuler')) _fermerApercu();
    if (e.target.closest('#prets-definir')) ouvrirFormulaireCredit();
    if (e.target.closest('#pf-annuler')) document.getElementById('prets-formulaire').hidden = true;
    if (e.target.closest('#prets-enregistrer')) _enregistrer();
  });
  document.getElementById('prets-formulaire').addEventListener('submit', async e => {
    e.preventDefault();
    const v = id => document.getElementById(id).value.trim();
    try {
      await api('POST', '/api/prets', {
        libelle: v('pf-libelle'), preteur: v('pf-preteur') || null,
        montant: parseLocaleNumber(v('pf-montant')), taux: parseLocaleNumber(v('pf-taux')),
        mois: parseLocaleNumber(v('pf-mois')), premiere: v('pf-premiere'),
        assurance: v('pf-assurance') ? parseLocaleNumber(v('pf-assurance')) : 0,
        differe: v('pf-differe') ? parseLocaleNumber(v('pf-differe')) : 0,
        type_differe: v('pf-type-differe'), entity: v('pf-entite') || null,
      });
      toast('Crédit enregistré', 'success');
      document.getElementById('prets-formulaire').hidden = true;
      document.getElementById('prets-formulaire').reset();
      loadPrets();
    } catch {}
  });
  document.getElementById('prets-fichier').addEventListener('change', e => {
    const f = e.target.files?.[0];
    if (f) _apercu(f);
    e.target.value = '';
  });
}

let _fichier = null;

async function _envoyer(fichier, etape, champs = {}) {
  const fd = new FormData();
  fd.append('file', fichier);
  Object.entries(champs).forEach(([k, v]) => v && fd.append(k, v));
  const meta = document.querySelector('meta[name="csrf-token"]');
  const r = await fetch(`/api/prets/import?step=${etape}`, { method: 'POST', body: fd,
    headers: meta ? { 'X-CSRF-Token': meta.content } : {} });
  const d = await r.json().catch(() => null);
  if (!r.ok) throw new Error(d?.error || `Import refusé (${r.status})`);
  return d;
}

async function _apercu(fichier) {
  const hote = document.getElementById('prets-apercu');
  try {
    const { pret: p } = await _envoyer(fichier, 'preview');
    _fichier = fichier;
    const options = ['<option value="">Aucune entité</option>',
      ...(S.entities || []).map(e => `<option value="${esc(e.name)}"${e.name === p.entite_proposee ? ' selected' : ''}>${esc(e.name)}</option>`)].join('');
    hote.innerHTML = `
      <p><b>${esc(p.libelle)}</b> · ${esc(p.preteur)}${p.emprunteur ? ` · emprunteur ${esc(p.emprunteur)}` : ''}</p>
      <p class="text-muted">${fmt(p.montant)} empruntés${p.taux ? ` à ${String(p.taux).replace('.', ',')} %` : ''} ·
        ${p.echeances} échéances, du ${fmtDate(p.debut)} au ${fmtDate(p.fin)}</p>
      <p class="prets-controle">${(p.controles || []).map(esc).join(' · ')}</p>
      ${p.deja ? `<p class="import-alerte">Ce prêt est déjà enregistré (« ${esc(p.deja.libelle)} »).</p>` : ''}
      <div class="prets-apercu-champs">
        <label>Libellé <input type="text" id="prets-libelle" class="ref-input" value="${esc(p.libelle)}"></label>
        <label>Dette de l'entité <select id="prets-entite" class="filter-select">${options}</select></label>
        <button type="button" class="btn btn-primary btn-sm" id="prets-enregistrer" ${p.deja ? 'disabled' : ''}>Enregistrer le prêt</button>
        <button type="button" class="btn btn-secondary btn-sm" id="prets-annuler">Annuler</button>
      </div>`;
    hote.hidden = false;
  } catch (e) {
    toast(e.message, 'error');
  }
}

function _fermerApercu() {
  const hote = document.getElementById('prets-apercu');
  hote.hidden = true; hote.innerHTML = ''; _fichier = null;
}

async function _enregistrer() {
  if (!_fichier) return;
  try {
    await _envoyer(_fichier, 'commit', {
      libelle: document.getElementById('prets-libelle').value.trim(),
      entity: document.getElementById('prets-entite').value,
    });
    toast('Prêt enregistré', 'success');
    _fermerApercu();
    loadPrets();
  } catch (e) { toast(e.message, 'error'); }
}

/** Le formulaire de credit, depuis le bouton « Ajouter » de l'en-tete. */
export function ouvrirFormulaireCredit() {
  const f = document.getElementById('prets-formulaire');
  if (!f) return;
  document.getElementById('pf-entite').innerHTML = ['<option value="">Aucune entité</option>',
    ...(S.entities || []).map(e => `<option value="${esc(e.name)}">${esc(e.name)}</option>`)].join('');
  f.hidden = false;
  document.getElementById('pf-libelle').focus();
}
