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
import { fmt, fmtDate, esc, today, fmtPct, fmtAxis } from '../utils.js';
import { toast, confirmDialog } from '../dialogs.js';
import { dessinerCourbe } from '../courbe.js';

const COULEURS = ['var(--nature-immo)', 'var(--nature-liq)', 'var(--nature-biens)', 'var(--nature-fin)'];
let _cable = false;

export async function loadPrets() {
  const carte = document.getElementById('prets-carte');
  if (!carte) return;
  _cabler();
  let res, pj, echeancier;
  try {
    [res, pj, echeancier] = await Promise.all([
      api('GET', '/api/prets', null, { silent: true }),
      api('GET', '/api/prets/projection', null, { silent: true }),
      api('GET', `/api/prets/dettes?date=${today()}`, null, { silent: true }),
    ]);
  } catch { return; }
  const prets = res.prets || [];
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
      <div class="pret-chiffre"><small>Mensualité</small><b>${p.mensualite != null ? fmt(p.mensualite) : '—'}</b></div>
      <div class="pret-chiffre"><small>Fin</small><b>${fmtDate(p.fin)}</b><small>${dans(p.fin)}</small></div>
      <div class="pret-chiffre"><small>Intérêts restants</small><b>${fmt(p.interets_restants)}</b></div>
      <div class="pret-avancement" aria-label="${fmtPct(part, 0)} remboursé">
        <span class="pret-barre"><span style="width:${part.toFixed(1)}%"></span></span>
        <small>${fmtPct(part, 0)} remboursé</small>
      </div>
      <button type="button" class="btn-icon del" data-pret-suppr="${p.id}" aria-label="Supprimer ${esc(p.libelle)}">Supprimer</button>
    </div>`;
  }).join('')}</div>`;
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
    if (e.target.closest('#prets-enregistrer')) _enregistrer();
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
