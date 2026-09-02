/**
 * Rapprochement de l'arrete affiche avec le journal des operations.
 *
 * Repond a deux questions restees sans reponse dans l'interface :
 * - « mes quantites sont-elles a jour ? » : les avis d'operes alimentent
 *   `transactions`, jamais `holdings`. Deux achats d'aout ont ainsi manque
 *   3 011 EUR a la valorisation sans que rien ne le signale, la ligne suivant
 *   le cours du jour sur une quantite perimee.
 * - « mon import est-il passe ? » : le journal n'etait affiche nulle part une
 *   fois la modale d'import fermee.
 *
 * Le panneau ne s'affiche que s'il a quelque chose a dire, et n'ecrit jamais
 * seul : l'utilisateur choisit les lignes a recaler.
 */
import { S } from '../state.js';
import { api } from '../api.js';
import { fmt, fmtDate, esc } from '../utils.js';
import { toast } from '../dialogs.js';

const V = {
  data: null,
  journal: null,
  ouvert: false,
  journalOuvert: false,
  selection: new Set(),
};

const HOST = 'reconcile-panel';

function _date() {
  return S.syntheseDate || S.positionsDate || S.dates?.[0] || null;
}

function _qty(n) {
  if (n == null) return '—';
  // Les parts d'OPCVM vont a 5 decimales, les ETF sont entiers : on n'affiche
  // des decimales que lorsqu'il y en a.
  return Number.isInteger(n) ? String(n) : n.toFixed(5).replace(/0+$/, '').replace(/\.$/, '');
}

function _signe(n) {
  return (n > 0 ? '+' : '') + _qty(n);
}

export async function loadReconcile() {
  const host = document.getElementById(HOST);
  if (!host) return;
  const date = _date();
  if (!date) { host.innerHTML = ''; return; }
  try {
    V.data = await api('GET', `/api/holdings/reconcile?date=${date}`, null, { silent: true });
  } catch { host.innerHTML = ''; return; }
  V.selection = new Set(V.data.ecarts.map(e => e.holding_id));
  render();
}

function render() {
  const host = document.getElementById(HOST);
  if (!host || !V.data) return;
  const d = V.data;
  const ecarts = d.ecarts || [];
  const absents = d.absents || [];
  const total = ecarts.length + absents.length;

  // Rien a signaler : on garde une ligne de confirmation discrete plutot que le
  // vide, sinon on ne sait pas si le controle a tourne.
  if (!total) {
    host.innerHTML = `
      <div class="rec-ok">Quantités conformes au journal des opérations
        <span class="rec-meta">${d.verifiees} ligne${d.verifiees > 1 ? 's' : ''} vérifiée${
          d.verifiees > 1 ? 's' : ''}${_motifs(d.ignores)}</span>
        ${_journalToggle()}
      </div>
      ${V.journalOuvert ? _journalHtml() : ''}`;
    wire();
    return;
  }

  const impact = ecarts.reduce((s, e) => s + Math.abs(e.cost_delta || 0), 0);
  host.innerHTML = `
    <div class="rec-panel">
      <button type="button" class="rec-head" id="rec-toggle" aria-expanded="${V.ouvert}"
              aria-controls="rec-body">
        <span class="rec-badge">${total}</span>
        <span class="rec-title">${total > 1 ? 'lignes' : 'ligne'} en retard sur le journal des opérations</span>
        <span class="rec-impact">${fmt(impact)} non pris en compte</span>
        <span class="rec-chevron">${V.ouvert ? '▴' : '▾'}</span>
      </button>
      <div id="rec-body" class="rec-body" ${V.ouvert ? '' : 'hidden'}>
        ${ecarts.map(_ecartHtml).join('')}
        ${absents.map(_absentHtml).join('')}
        ${ecarts.length ? `
          <div class="rec-actions">
            <span class="rec-meta" id="rec-count"></span>
            <button type="button" class="btn btn-primary btn-sm" id="rec-apply">Appliquer</button>
          </div>` : ''}
        <div class="rec-footer">
          ${V.data.verifiees} ligne${V.data.verifiees > 1 ? 's' : ''} vérifiée${
            V.data.verifiees > 1 ? 's' : ''}${_motifs(V.data.ignores)}
          ${_journalToggle()}
        </div>
      </div>
    </div>
    ${V.journalOuvert ? _journalHtml() : ''}`;
  wire();
  majCompteur();
}

/** Decompte motive de ce qui n'a pas ete verifie : une ligne ecartee d'un
 *  controle ne disparait pas en silence. */
function _motifs(ig) {
  if (!ig) return '';
  const parts = [];
  if (ig.soldees) parts.push(`${ig.soldees} ligne${ig.soldees > 1 ? 's' : ''} soldée${ig.soldees > 1 ? 's' : ''}`);
  if (ig.hors_journal) parts.push(`${ig.hors_journal} sans opération enregistrée`);
  if (ig.sans_date_valeur) parts.push(`${ig.sans_date_valeur} sans date de valeur`);
  if (ig.ambigues) parts.push(`${ig.ambigues} rattachement ambigu`);
  return parts.length ? ` · ${parts.join(' · ')}` : '';
}

function _ecartHtml(e) {
  const coche = V.selection.has(e.holding_id) ? 'checked' : '';
  return `
    <label class="rec-row">
      <input type="checkbox" class="rec-check" data-id="${e.holding_id}" ${coche}>
      <span class="rec-row-main">
        <span class="rec-name">${esc(e.name)}</span>
        <span class="rec-ctx">${esc(e.owner)}${e.envelope ? ` · ${esc(e.envelope)}` : ''}${
          e.establishment ? ` · ${esc(e.establishment)}` : ''}</span>
        <span class="rec-delta">${_qty(e.quantity)} → <b>${_qty(e.expected)}</b> parts
          <span class="rec-diff">(${_signe(e.delta_quantity)})</span>
          <span class="rec-asof">photo du ${fmtDate(e.as_of_date)}</span>
        </span>
        <span class="rec-ops">${e.operations.map(o => `
          <span class="rec-op">${fmtDate(o.date)} · ${o.side === 'ACHAT' ? 'Achat' : 'Vente'}
            ${_qty(o.quantity)} parts · ${fmt(o.net_eur)}</span>`).join('')}</span>
      </span>
    </label>`;
}

/** Titre encore detenu d'apres le journal, absent de la photo : on le signale
 *  sans proposer de l'appliquer, faute de savoir a quelle position le rattacher. */
function _absentHtml(a) {
  return `
    <div class="rec-row rec-row-absent">
      <span class="rec-row-main">
        <span class="rec-name">${esc(a.name)}</span>
        <span class="rec-ctx">${esc(a.owner)}${a.envelope ? ` · ${esc(a.envelope)}` : ''}${
          a.establishment ? ` · ${esc(a.establishment)}` : ''}</span>
        <span class="rec-delta">absent de l'arrêté, <b>${_qty(a.expected)} parts</b>
          encore détenues d'après le journal</span>
        <span class="rec-ops">${a.operations.slice(-3).map(o => `
          <span class="rec-op">${fmtDate(o.date)} · ${o.side === 'ACHAT' ? 'Achat' : 'Vente'}
            ${_qty(o.quantity)} parts</span>`).join('')}</span>
        <span class="rec-hint">À saisir dans l'enveloppe concernée : le journal ne dit pas
          quelle ligne créer.</span>
      </span>
    </div>`;
}

function _journalToggle() {
  return `<button type="button" class="rec-journal-toggle" id="rec-journal"
    aria-expanded="${V.journalOuvert}" aria-controls="rec-journal-body">Journal des opérations ${
    V.journalOuvert ? '▴' : '▾'}</button>`;
}

function _journalHtml() {
  if (!V.journal) return `<div id="rec-journal-body" class="rec-journal">Chargement…</div>`;
  const rows = V.journal.transactions || [];
  if (!rows.length) {
    return `<div id="rec-journal-body" class="rec-journal">Aucune opération enregistrée.</div>`;
  }
  // L'API trie par date croissante et applique `limit` APRES le tri : on prend
  // donc la fin de la liste pour obtenir les plus recentes.
  const derniers = rows.slice(-25).reverse();
  return `
    <div id="rec-journal-body" class="rec-journal">
      <div class="rec-journal-head">${V.journal.count} opération${
        V.journal.count > 1 ? 's' : ''} enregistrée${V.journal.count > 1 ? 's' : ''} ·
        ${derniers.length} plus récentes</div>
      <table class="data-table rec-journal-table">
        <thead><tr>
          <th>Date</th><th>Sens</th><th>Valeur</th><th class="num">Quantité</th>
          <th class="num">Montant</th><th>Compte</th>
        </tr></thead>
        <tbody>${derniers.map(t => `
          <tr>
            <td>${fmtDate(t.date)}</td>
            <td class="${t.side === 'ACHAT' ? 'rec-buy' : 'rec-sell'}">${
              t.side === 'ACHAT' ? 'Achat' : 'Vente'}</td>
            <td>${esc(t.name || t.isin)}</td>
            <td class="num">${_qty(t.quantity)}</td>
            <td class="num">${fmt(t.net_eur)}</td>
            <td>${esc(t.owner)}${t.envelope ? ` · ${esc(t.envelope)}` : ''}</td>
          </tr>`).join('')}</tbody>
      </table>
    </div>`;
}

function majCompteur() {
  const el = document.getElementById('rec-count');
  if (!el) return;
  const n = V.selection.size;
  el.textContent = n
    ? `${n} ligne${n > 1 ? 's' : ''} sélectionnée${n > 1 ? 's' : ''}`
    : 'aucune ligne sélectionnée';
  const btn = document.getElementById('rec-apply');
  if (btn) btn.disabled = n === 0;
}

function wire() {
  document.getElementById('rec-toggle')?.addEventListener('click', () => {
    V.ouvert = !V.ouvert;
    render();
  });

  document.getElementById('rec-journal')?.addEventListener('click', async () => {
    V.journalOuvert = !V.journalOuvert;
    render();
    if (V.journalOuvert && !V.journal) {
      try {
        V.journal = await api('GET', '/api/transactions', null, { silent: true });
      } catch { V.journal = { count: 0, transactions: [] }; }
      render();
    }
  });

  document.querySelectorAll('.rec-check').forEach(cb => {
    cb.addEventListener('change', () => {
      const id = parseInt(cb.dataset.id, 10);
      if (cb.checked) V.selection.add(id); else V.selection.delete(id);
      majCompteur();
    });
  });

  document.getElementById('rec-apply')?.addEventListener('click', appliquer);
}

async function appliquer() {
  const ids = [...V.selection];
  if (!ids.length) return;
  const btn = document.getElementById('rec-apply');
  if (btn) { btn.disabled = true; btn.textContent = 'Application…'; }
  let res;
  try {
    res = await api('POST', '/api/holdings/reconcile/apply',
                    { date: V.data.date, holding_ids: ids });
  } catch {
    if (btn) { btn.disabled = false; btn.textContent = 'Appliquer'; }
    return;
  }
  const n = res.appliquees?.length || 0;
  const ignorees = res.ignorees?.length || 0;
  toast(n
    ? `${n} ligne${n > 1 ? 's' : ''} recalée${n > 1 ? 's' : ''}${
        ignorees ? ` · ${ignorees} déjà à jour` : ''}`
    : 'Aucune ligne à recaler (déjà à jour)', n ? 'success' : 'info');

  V.journal = null;   // les quantites ont bouge, le journal sera relu au besoin
  const { loadActifs } = await import('./actifs.js');
  const { loadSynthese } = await import('./synthese.js');
  await loadReconcile();
  await loadActifs();
  await loadSynthese();
}
