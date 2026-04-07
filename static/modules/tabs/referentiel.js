import { S } from '../state.js';
import { esc } from '../utils.js';
import { api, buildSelects, refreshEntitySelect } from '../api.js';
import { confirmDialog } from '../dialogs.js';
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
    btn.addEventListener('click', () => {
      const owner = S.referential.owners[parseInt(btn.dataset.index)];
      const posCount = S.positions.filter(p => p.owner === owner).length;
      const fluxCount = S.flux.filter(f => f.owner === owner).length;
      if (posCount || fluxCount) {
        const lines = [];
        if (posCount)  lines.push(`${posCount} position(s)`);
        if (fluxCount) lines.push(`${fluxCount} flux`);
        if (!confirm(`"${owner}" est référencé(e) dans ${lines.join(' et ')}.\nCes données ne seront pas supprimées, mais la personne n'apparaîtra plus dans les filtres.\n\nContinuer ?`)) return;
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
        <input class="ref-input ref-cat-mob" data-cat="${esc(cat)}" type="number" min="0" max="100" step="5"
               value="${Math.round((mob[cat] ?? 0.8) * 100)}"
               style="width:65px;text-align:right"> %
      </td>
      <td>
        <button class="btn-icon del" data-section="categories" data-index="${i}">Suppr.</button>
      </td>
    </tr>`).join('') + `
    <tr id="ref-cat-add-row">
      <td><input type="text" id="new-cat-name" class="ref-input" placeholder="Nouvelle catégorie" style="width:100%"></td>
      <td style="text-align:right">
        <input type="number" id="new-cat-mob" class="ref-input" min="0" max="100" step="5" value="80"
               style="width:65px;text-align:right"> %
      </td>
      <td><button class="btn btn-secondary btn-sm" id="btn-add-cat">+ Ajouter</button></td>
    </tr>`;

  el.querySelectorAll('.ref-cat-name').forEach(inp => {
    inp.addEventListener('change', () => {
      const i = parseInt(inp.dataset.index);
      const oldCat = cats[i];
      const newCat = inp.value.trim();
      if (!newCat) return;
      S.referential.categories[i] = newCat;
      if (oldCat !== newCat) {
        S.referential.category_mobilizable[newCat] = S.referential.category_mobilizable[oldCat] ?? 0.8;
        delete S.referential.category_mobilizable[oldCat];
      }
    });
  });
  el.querySelectorAll('.ref-cat-mob').forEach(inp => {
    inp.addEventListener('change', () => {
      S.referential.category_mobilizable[inp.dataset.cat] = parseFloat(inp.value) / 100;
    });
  });
  el.querySelectorAll('.btn-icon.del[data-section="categories"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const i = parseInt(btn.dataset.index);
      const cat = S.referential.categories[i];
      S.referential.categories.splice(i, 1);
      delete S.referential.category_mobilizable[cat];
      renderRefCategories();
    });
  });
  document.getElementById('btn-add-cat')?.addEventListener('click', () => {
    const name = document.getElementById('new-cat-name').value.trim();
    const mob  = parseFloat(document.getElementById('new-cat-mob').value) / 100;
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
      <td><button class="btn-icon del" data-section="envelopes" data-env="${esc(name)}">Suppr.</button></td>
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
    btn.addEventListener('click', () => {
      delete S.referential.envelope_meta[btn.dataset.env];
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
        <input class="ref-input alert-threshold" data-i="${i}" type="number" value="${a.threshold || 0}" style="width:80px">
        <button class="btn-icon del alert-del" data-i="${i}">Suppr.</button>
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
      if (inp.classList.contains('alert-threshold')) alerts[i].threshold = parseFloat(inp.value) || 0;
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

export async function saveReferential() {
  const btn = document.getElementById('btn-save-referential');
  if (btn) { btn.disabled = true; btn.textContent = 'Enregistrement…'; }
  try {
    await api('PUT', '/api/referential', S.referential);
    S.config = await api('GET', '/api/config');
    buildSelects();
    refreshEntitySelect();
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

export async function resetReferential() {
  if (!await confirmDialog(
    'Réinitialiser le référentiel ?',
    'Toutes vos personnalisations (propriétaires, catégories, enveloppes) seront remplacées par les valeurs par défaut.',
    { confirmText: 'Réinitialiser', danger: true }
  )) return;
  await api('PUT', '/api/referential', {
    owners: ['Julien', 'Perrine', 'Adriel', 'Aloïs'],
    categories: ['Cash & dépôts','Monétaire','Obligations','Actions','Immobilier','SCPI','Fond Euro','Produits Structurés','Crypto','Objets de valeur','Autre'],
    category_mobilizable: {'Cash & dépôts':1,'Monétaire':.95,'Obligations':.95,'Actions':.9,'Immobilier':0,'SCPI':0,'Fond Euro':.95,'Produits Structurés':0,'Crypto':.9,'Objets de valeur':0,'Autre':.8},
    envelope_meta: {'Compte courant':{liquidity:'J0–J1',friction:'Aucune'},'Livret A':{liquidity:'J2–J7',friction:'Fiscale'},'LDDS':{liquidity:'J0–J1',friction:'Aucune'},'Livret Bourso+':{liquidity:'J0–J1',friction:'Aucune'},'PEL/CEL':{liquidity:'J8–J30',friction:'Frais'},'PEA':{liquidity:'J2–J7',friction:'Fiscale'},'CTO':{liquidity:'J2–J7',friction:'Fiscale'},'Assurance-vie':{liquidity:'J8–J30',friction:'Mixte'},'PER':{liquidity:'Bloqué',friction:'Fiscale'},'Crypto':{liquidity:'J0–J1',friction:'Décote probable'},'Immobilier':{liquidity:'30J+',friction:'Mixte'},'SCI':{liquidity:'30J+',friction:'Mixte'},'Autre':{liquidity:'30J+',friction:'Mixte'}},
    entity_types: ['SCI','Indivision','Holding','Autre'],
    valuation_modes: ['Valeur de marché',"Prix d'acquisition",'Valeur fiscale','Autre'],
    flux_types: ['Versement','Retrait','Dividende/Intérêt','Frais','Autre'],
  });
  S.referential = await api('GET', '/api/referential');
  S.config = await api('GET', '/api/config');
  buildSelects();
  renderReferential();
}
