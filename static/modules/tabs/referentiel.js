import { S } from '../state.js';
import { esc, parseLocaleNumber } from '../utils.js';
import { api, buildSelects, refreshEntitySelect } from '../api.js';
import { confirmDialog, toast } from '../dialogs.js';
import { reloadAll } from '../main.js';
import { isMasked } from '../mask.js';
import { loadUserAlerts, saveUserAlerts } from '../alerts.js';
import { fmt } from '../utils.js';

export async function loadReferential() {
  S.referential = await api('GET', '/api/referential');
  renderReferential();
}

function renderReferential() {
  if (!S.referential) return;
  renderRefOwners();
  renderRefCategories();
  renderRefEnvelopes();
  renderRefLists();
  renderRefAlerts();
}

function renderRefOwners() {
  const el = document.getElementById('ref-owners-chips');
  if (!el) return;
  const owners = S.referential.owners || [];
  el.innerHTML = owners.map((o, i) => `
    <span class="ref-chip">
      ${esc(o)}
      <button class="chip-del" data-section="owners" data-index="${i}" title="Supprimer">×</button>
    </span>`).join('') + `
    <div style="display:flex;gap:.5rem;align-items:center;margin-top:.25rem">
      <input type="text" id="new-owner-input" class="ref-input" placeholder="Prénom / entité">
      <button class="btn btn-secondary btn-sm" id="btn-add-owner">+ Ajouter</button>
    </div>`;

  el.querySelectorAll('.chip-del[data-section="owners"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const owner = S.referential.owners[parseInt(btn.dataset.index)];
      const { positions: posCount, flux: fluxCount } = await _usage('owner', owner);
      if (posCount || fluxCount) {
        const lines = [];
        if (posCount)  lines.push(`${posCount} position(s)`);
        if (fluxCount) lines.push(`${fluxCount} flux`);
        if (!await confirmDialog('Supprimer la personne ?',
          `<strong>${esc(owner)}</strong> est référencé(e) dans ${lines.join(' et ')}.<br>Ces données ne seront pas supprimées, mais la personne n'apparaîtra plus dans les filtres.`,
          { confirmText: 'Supprimer', danger: true })) return;
      }
      S.referential.owners.splice(parseInt(btn.dataset.index), 1);
      renderRefOwners();
    });
  });
  document.getElementById('btn-add-owner')?.addEventListener('click', () => {
    const val = document.getElementById('new-owner-input').value.trim();
    if (!val) return;
    if (S.referential.owners.includes(val)) return;
    S.referential.owners.push(val);
    renderRefOwners();
  });
  document.getElementById('new-owner-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); document.getElementById('btn-add-owner').click(); }
  });
}

function renderRefCategories() {
  const el = document.getElementById('ref-categories-body');
  if (!el) return;
  const cats = S.referential.categories || [];
  const mob  = S.referential.category_mobilizable || {};
  el.innerHTML = cats.map((cat, i) => `
    <tr>
      <td><input class="ref-input ref-cat-name" data-index="${i}" value="${esc(cat)}" style="width:100%"></td>
      <td style="text-align:right">
        <input class="ref-input ref-cat-mob" data-cat="${esc(cat)}" type="text" inputmode="decimal" min="0" max="100" step="5"
               value="${Math.round((mob[cat] ?? 0.8) * 100)}"
               style="width:65px;text-align:right"> %
      </td>
      <td>
        <button class="btn-icon del" data-section="categories" data-index="${i}">Supprimer</button>
      </td>
    </tr>`).join('') + `
    <tr id="ref-cat-add-row">
      <td><input type="text" id="new-cat-name" class="ref-input" placeholder="Nouvelle catégorie" style="width:100%"></td>
      <td style="text-align:right">
        <input type="text" inputmode="decimal" id="new-cat-mob" class="ref-input" min="0" max="100" step="5" value="80"
               style="width:65px;text-align:right"> %
      </td>
      <td><button class="btn btn-secondary btn-sm" id="btn-add-cat">+ Ajouter</button></td>
    </tr>`;

  el.querySelectorAll('.ref-cat-name').forEach(inp => {
    inp.addEventListener('change', () => {
      const i = parseInt(inp.dataset.index);
      const oldCat = S.referential.categories[i];
      const newCat = inp.value.trim();
      if (!newCat || oldCat === newCat) return;
      if (S.referential.categories.includes(newCat)) {
        toast(`« ${newCat} » existe déjà : deux catégories ne fusionnent pas par renommage`, 'error');
        inp.value = oldCat;
        return;
      }
      S.referential.categories[i] = newCat;
      S.referential.category_mobilizable[newCat] = S.referential.category_mobilizable[oldCat] ?? 0.8;
      delete S.referential.category_mobilizable[oldCat];
      _noterRenommage('category', oldCat, newCat);
      // Le champ % suit le nouveau nom : il gardait l'ancien et recreait la cle.
      inp.closest('tr')?.querySelectorAll('[data-cat]').forEach(x => { x.dataset.cat = newCat; });
    });
  });
  el.querySelectorAll('.ref-cat-mob').forEach(inp => {
    inp.addEventListener('change', () => {
      S.referential.category_mobilizable[inp.dataset.cat] = parseLocaleNumber(inp.value, 0) / 100;
    });
  });
  el.querySelectorAll('.btn-icon.del[data-section="categories"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const i = parseInt(btn.dataset.index);
      const cat = S.referential.categories[i];
      const { positions: posCount, flux: fluxCount } = await _usage('category', cat);
      if (posCount || fluxCount) {
        const lines = [];
        if (posCount)  lines.push(`${posCount} position(s)`);
        if (fluxCount) lines.push(`${fluxCount} flux`);
        if (!await confirmDialog(
          `Supprimer la catégorie "${cat}" ?`,
          `Elle est utilisée dans ${lines.join(' et ')}.<br>Ces données ne seront pas supprimées, mais la catégorie n'apparaîtra plus dans les filtres.`,
          { confirmText: 'Supprimer quand même', danger: true }
        )) return;
      }
      S.referential.categories.splice(i, 1);
      delete S.referential.category_mobilizable[cat];
      renderRefCategories();
    });
  });
  document.getElementById('btn-add-cat')?.addEventListener('click', () => {
    const name = document.getElementById('new-cat-name').value.trim();
    const mob  = parseLocaleNumber(document.getElementById('new-cat-mob').value) / 100;
    if (!name) return;
    S.referential.categories.push(name);
    S.referential.category_mobilizable[name] = isNaN(mob) ? 0.8 : mob;
    renderRefCategories();
  });
}

function renderRefEnvelopes() {
  const el = document.getElementById('ref-envelopes-body');
  if (!el) return;
  const meta = S.referential.envelope_meta || {};
  const envNames = Object.keys(meta);

  el.innerHTML = envNames.map((name, i) => {
    const m = meta[name];
    return `<tr>
      <td><input class="ref-input ref-env-name" data-index="${i}" data-orig="${esc(name)}" value="${esc(name)}" style="width:100%"></td>
      <td>
        <select class="ref-input ref-env-liq" data-env="${esc(name)}" style="width:100%">
          ${(S.config?.liquidity_order || ['J0–J1','J2–J7','J8–J30','30J+','Bloqué']).map(l =>
            `<option value="${esc(l)}"${l === m.liquidity ? ' selected' : ''}>${esc(l)}</option>`
          ).join('')}
        </select>
      </td>
      <td><input class="ref-input ref-env-friction" data-env="${esc(name)}" value="${esc(m.friction || '')}" style="width:100%"></td>
      <td><button class="btn-icon del" data-section="envelopes" data-env="${esc(name)}">Supprimer</button></td>
    </tr>`;
  }).join('') + `
    <tr>
      <td><input type="text" id="new-env-name" class="ref-input" placeholder="Nom de l'enveloppe" style="width:100%"></td>
      <td>
        <select id="new-env-liq" class="ref-input" style="width:100%">
          ${(S.config?.liquidity_order || ['J0–J1','J2–J7','J8–J30','30J+','Bloqué']).map(l =>
            `<option value="${esc(l)}">${esc(l)}</option>`).join('')}
        </select>
      </td>
      <td><input type="text" id="new-env-friction" class="ref-input" placeholder="ex: Fiscale" style="width:100%"></td>
      <td><button class="btn btn-secondary btn-sm" id="btn-add-env">+ Ajouter</button></td>
    </tr>`;

  el.querySelectorAll('.ref-env-name').forEach(inp => {
    inp.addEventListener('change', () => {
      const orig   = inp.dataset.orig;
      const newName = inp.value.trim();
      if (!newName || newName === orig) return;
      if (S.referential.envelope_meta[newName]) {
        toast(`« ${newName} » existe déjà : deux enveloppes ne fusionnent pas par renommage`, 'error');
        inp.value = orig;
        return;
      }
      _noterRenommage('envelope', orig, newName);
      const existing = meta[orig];
      delete S.referential.envelope_meta[orig];
      S.referential.envelope_meta[newName] = existing;
      inp.dataset.orig = newName;
      inp.closest('tr').querySelectorAll('[data-env]').forEach(el => el.dataset.env = newName);
    });
  });
  el.querySelectorAll('.ref-env-liq').forEach(sel => {
    sel.addEventListener('change', () => {
      if (S.referential.envelope_meta[sel.dataset.env])
        S.referential.envelope_meta[sel.dataset.env].liquidity = sel.value;
    });
  });
  el.querySelectorAll('.ref-env-friction').forEach(inp => {
    inp.addEventListener('change', () => {
      if (S.referential.envelope_meta[inp.dataset.env])
        S.referential.envelope_meta[inp.dataset.env].friction = inp.value;
    });
  });
  el.querySelectorAll('.btn-icon.del[data-section="envelopes"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const env = btn.dataset.env;
      const { positions: posCount, flux: fluxCount } = await _usage('envelope', env);
      if (posCount || fluxCount) {
        const lines = [];
        if (posCount)  lines.push(`${posCount} position(s)`);
        if (fluxCount) lines.push(`${fluxCount} flux`);
        if (!await confirmDialog(
          `Supprimer l'enveloppe "${env}" ?`,
          `Elle est utilisée dans ${lines.join(' et ')}.<br>Ces données ne seront pas supprimées, mais l'enveloppe n'apparaîtra plus dans les filtres.`,
          { confirmText: 'Supprimer quand même', danger: true }
        )) return;
      }
      delete S.referential.envelope_meta[env];
      renderRefEnvelopes();
    });
  });
  document.getElementById('btn-add-env')?.addEventListener('click', () => {
    const name = document.getElementById('new-env-name').value.trim();
    const liq  = document.getElementById('new-env-liq').value;
    const fric = document.getElementById('new-env-friction').value.trim();
    if (!name) return;
    S.referential.envelope_meta[name] = { liquidity: liq, friction: fric || 'Mixte' };
    renderRefEnvelopes();
  });
}

function renderRefLists() {
  renderRefSimpleList('ref-entity-types',    'entity_types',    'Type d\'entité');
  renderRefSimpleList('ref-valuation-modes', 'valuation_modes', 'Mode de valorisation');
  renderRefSimpleList('ref-flux-types',      'flux_types',      'Type de flux');
}

function renderRefSimpleList(containerId, refKey, placeholder) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const items = S.referential[refKey] || [];
  el.innerHTML = items.map((v, i) => `
    <span class="ref-chip">
      ${esc(v)}
      <button class="chip-del" data-ref-key="${refKey}" data-index="${i}">×</button>
    </span>`).join('') + `
    <div style="display:flex;gap:.5rem;align-items:center;margin-top:.25rem">
      <input type="text" id="new-${containerId}" class="ref-input" placeholder="${esc(placeholder)}">
      <button class="btn btn-secondary btn-sm" id="btn-add-${containerId}">+ Ajouter</button>
    </div>`;

  el.querySelectorAll(`.chip-del[data-ref-key="${refKey}"]`).forEach(btn => {
    btn.addEventListener('click', () => {
      S.referential[refKey].splice(parseInt(btn.dataset.index), 1);
      renderRefSimpleList(containerId, refKey, placeholder);
    });
  });
  document.getElementById(`btn-add-${containerId}`)?.addEventListener('click', () => {
    const val = document.getElementById(`new-${containerId}`)?.value.trim();
    if (!val || S.referential[refKey].includes(val)) return;
    S.referential[refKey].push(val);
    renderRefSimpleList(containerId, refKey, placeholder);
  });
}

function renderRefAlerts() {
  const el = document.getElementById('ref-alerts-list');
  if (!el) return;
  const alerts = loadUserAlerts();
  const cats   = S.config?.categories || [];

  const metricOptions = `
    <option value="cat_pct">Catégorie — % du patrimoine net</option>
    <option value="cat_abs">Catégorie — montant net (€)</option>
    <option value="net">Patrimoine net total (€)</option>
    <option value="gross">Actifs bruts totaux (€)</option>`;

  if (!alerts.length) {
    el.innerHTML = '<p class="text-muted" style="font-size:12.5px">Aucune alerte configurée.</p>';
  } else {
    el.innerHTML = alerts.map((a, i) => {
      const needsCat = a.metric === 'cat_pct' || a.metric === 'cat_abs';
      const catSel = needsCat
        ? `<select class="filter-select alert-cat" data-i="${i}" style="width:auto">
             ${cats.map(c => `<option value="${esc(c)}" ${a.category === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}
           </select>` : '';
      return `<div class="alert-row" data-i="${i}">
        <input class="ref-input alert-label" data-i="${i}" value="${esc(a.label || '')}" placeholder="Label…" style="width:110px">
        <select class="filter-select alert-metric" data-i="${i}" style="width:auto">${metricOptions.replace(`value="${a.metric}"`, `value="${a.metric}" selected`)}</select>
        ${catSel}
        <select class="filter-select alert-op" data-i="${i}" style="width:60px">
          <option value="<" ${a.op === '<' ? 'selected' : ''}>&lt;</option>
          <option value=">" ${a.op === '>' ? 'selected' : ''}>&gt;</option>
        </select>
        <input class="ref-input alert-threshold" data-i="${i}" type="text" inputmode="decimal"
          ${isMasked() && a.metric !== 'cat_pct' ? `value="" placeholder="masqué"` : `value="${a.threshold || 0}"`} style="width:80px">
        <button class="btn-icon del alert-del" data-i="${i}">Supprimer</button>
      </div>`;
    }).join('');
  }

  el.querySelectorAll('.alert-label, .alert-metric, .alert-cat, .alert-op, .alert-threshold').forEach(inp => {
    inp.addEventListener('change', () => {
      const i = parseInt(inp.dataset.i);
      if (inp.classList.contains('alert-label'))     alerts[i].label     = inp.value;
      if (inp.classList.contains('alert-metric'))    { alerts[i].metric  = inp.value; renderRefAlerts(); return; }
      if (inp.classList.contains('alert-cat'))       alerts[i].category  = inp.value;
      if (inp.classList.contains('alert-op'))        alerts[i].op        = inp.value;
      if (inp.classList.contains('alert-threshold')) {
        if (!inp.value.trim()) return;       // champ masque laisse vide : seuil inchange
        alerts[i].threshold = parseLocaleNumber(inp.value, 0);
      }
      saveUserAlerts(alerts);
    });
  });
  el.querySelectorAll('.alert-del').forEach(btn => {
    btn.addEventListener('click', () => {
      alerts.splice(parseInt(btn.dataset.i), 1);
      saveUserAlerts(alerts);
      renderRefAlerts();
    });
  });

  const addBtn = document.getElementById('btn-add-alert');
  if (addBtn) {
    addBtn.onclick = () => {
      alerts.push({ label: '', metric: 'cat_pct', category: cats[0] || '', op: '<', threshold: 10 });
      saveUserAlerts(alerts);
      renderRefAlerts();
    };
  }
}

/** Positions et flux qui portent cette valeur, TOUTES dates confondues. Le
 *  decompte local ne voyait que l'arrete charge — ou rien si l'onglet
 *  Positions n'avait pas ete ouvert : on supprimait une categorie utilisee
 *  sans avertissement. */
async function _usage(champ, valeur) {
  try {
    return await api('GET', `/api/referential/usage?champ=${champ}&valeur=${encodeURIComponent(valeur)}`, null, { silent: true });
  } catch { return { positions: 0, flux: 0 }; }
}

// Renommages en attente : envoyes avec le referentiel, que le serveur
// propage aux positions et aux flux dans la meme transaction.
let _renommages = [];
function _noterRenommage(champ, ancien, nouveau) {
  // a → b puis b → c : un seul renommage a → c.
  const deja = _renommages.find(r => r.champ === champ && r.nouveau === ancien);
  if (deja) deja.nouveau = nouveau;
  else _renommages.push({ champ, ancien, nouveau });
  _renommages = _renommages.filter(r => r.ancien !== r.nouveau);
}

export async function saveReferential() {
  const btn = document.getElementById('btn-save-referential');
  if (btn) { btn.disabled = true; btn.textContent = 'Enregistrement…'; }
  try {
    const res = await api('PUT', '/api/referential', { ...S.referential, renommages: _renommages });
    const faits = (res?.renommages || []).filter(r => r.positions || r.flux);
    if (faits.length) {
      toast(faits.map(r => `« ${r.ancien} » → « ${r.nouveau} » : ${r.positions} position${r.positions > 1 ? 's' : ''}, ${r.flux} flux`).join(' · '), 'success');
    }
    _renommages = [];
    // Positions et flux charges portent l'ancien nom : on relit tout.
    if (faits.length) reloadAll();
    S.config = await api('GET', '/api/config');
    buildSelects();
    refreshEntitySelect();
    updateSavedRef();
    const status = document.getElementById('ref-save-status');
    if (status) {
      status.textContent = '✓ Référentiel enregistré.';
      status.className = 'alert alert-success';
      setTimeout(() => { status.textContent = ''; status.className = ''; }, 3000);
    }
  } catch (err) {
    const status = document.getElementById('ref-save-status');
    if (status) { status.textContent = `Erreur : ${err.message}`; status.className = 'alert alert-error'; }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Enregistrer le référentiel'; }
  }
}

let _templates = null;
let _savedRef = null;

export async function initTemplateSelect() {
  const sel = document.getElementById('ref-template-select');
  if (!sel) return;
  try {
    _templates = await api('GET', '/api/referential/templates');
    _savedRef = await api('GET', '/api/referential');
    rebuildTemplateOptions();
    sel.addEventListener('change', onTemplateChange);
  } catch { /* api() shows toast on failure; template select stays empty */ }
}

function rebuildTemplateOptions() {
  const sel = document.getElementById('ref-template-select');
  if (!sel || !_templates) return;
  sel.innerHTML = '<option value="">Parcourir les modèles…</option>' +
    `<option value="__saved__">Mon référentiel (enregistré)</option>` +
    Object.keys(_templates).map(name =>
      `<option value="${esc(name)}">${esc(name)}</option>`
    ).join('');
}

async function onTemplateChange() {
  const sel = document.getElementById('ref-template-select');
  const name = sel.value;
  if (!name) return;

  const preview = document.getElementById('ref-template-preview');

  if (name === '__saved__') {
    // Recharger le référentiel enregistré en DB (annuler les modifs en cours)
    S.referential = await api('GET', '/api/referential');
    _savedRef = { ...S.referential };
    renderReferential();
    if (preview) preview.style.display = 'none';
    sel.value = '';
    return;
  }

  const tpl = _templates[name];
  if (!tpl) return;

  // Afficher un aperçu avant de charger
  if (preview) {
    const owners = (tpl.owners || []).join(', ');
    const cats = (tpl.categories || []).join(', ');
    const envs = Object.keys(tpl.envelope_meta || {}).join(', ');
    preview.style.display = '';
    preview.innerHTML = `
      <div class="template-preview">
        <div><strong>Propriétaires :</strong> ${esc(owners)}</div>
        <div><strong>Catégories :</strong> ${esc(cats)}</div>
        <div><strong>Enveloppes :</strong> ${esc(envs)}</div>
        <div style="margin-top:.5rem;display:flex;gap:.5rem">
          <button class="btn btn-primary btn-sm" id="btn-apply-template">Appliquer ce modèle</button>
          <button class="btn btn-secondary btn-sm" id="btn-cancel-template">Annuler</button>
        </div>
      </div>`;
    preview.querySelector('#btn-apply-template').addEventListener('click', async () => {
      await api('PUT', '/api/referential', tpl);
      S.referential = await api('GET', '/api/referential');
      _savedRef = { ...S.referential };
      S.config = await api('GET', '/api/config');
      buildSelects();
      renderReferential();
      preview.style.display = 'none';
      sel.value = '';
    });
    preview.querySelector('#btn-cancel-template').addEventListener('click', () => {
      preview.style.display = 'none';
      sel.value = '';
    });
  }
}

export function updateSavedRef() {
  if (S.referential) _savedRef = { ...S.referential };
}
