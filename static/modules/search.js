import { S } from './state.js';
import { api } from './api.js';
import { fmt, fmtDate, esc, fluxSigned, fmtSigned } from './utils.js';

let _debounce = null;

/* La recherche lisait `S.positions` et `S.flux`, qui ne se remplissent qu'a
   la visite des onglets Positions et Flux : lancee depuis la synthese, elle
   ne trouvait rien. Elle va desormais chercher ce qui lui manque, une fois. */
let _positions = null;
let _chargement = null;

/** Oublie ce que la recherche a memorise : a appeler quand l'arrete ou le
 *  titulaire change, sans quoi elle cherchait dans l'arrete precedent. */
export function resetSearchCache() {
  _positions = null;
  _chargement = null;
}

function _assurerDonnees() {
  if (_chargement) return _chargement;
  _chargement = (async () => {
    if (!S.flux?.length) {
      try { S.flux = await api('GET', '/api/flux', null, { silent: true }); }
      catch {
        // Un echec ne doit pas etre memorise : la frappe suivante reessaie.
        _chargement = null;
      }
    }
  })();
  return _chargement;
}

/** Positions de l'arrete consulte : celles de l'onglet si elles sont de cet
 *  arrete, sinon celles que la synthese a deja recuperees. */
function _positionsCourantes() {
  const date = S.syntheseDate;
  const duJour = liste => liste?.length && (!date || !liste[0].date || liste[0].date === date);
  if (duJour(S.positions)) return S.positions;
  if (_positions) return _positions;
  const cache = S.synthese?._positions_cache;
  if (cache && (!date || S.synthese?.date === date)) return (_positions = Object.values(cache).flat());
  return S.positions || [];
}

export function wireGlobalSearch(switchTabFn) {
  const input = document.getElementById('global-search-input');
  const panel = document.getElementById('search-results');
  if (!input || !panel) return;
  // Motif « combobox » : le focus reste dans le champ, les fleches deplacent
  // l'option active, annoncee par aria-activedescendant.
  panel.setAttribute('role', 'listbox');
  panel.setAttribute('aria-label', 'Résultats de recherche');
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-controls', 'search-results');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-expanded', 'false');

  input.addEventListener('input', () => {
    clearTimeout(_debounce);
    _debounce = setTimeout(async () => {
      await _assurerDonnees();
      renderResults(input.value.trim(), panel, switchTabFn);
    }, 150);
  });

  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') { input.value = ''; _vider(panel); input.blur(); return; }
    const items = [...panel.querySelectorAll('.search-item')];
    if (!items.length) return;
    const active = panel.querySelector('.search-item.is-active');
    const idx = Math.max(0, items.indexOf(active));
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _setActive(items, (idx + 1) % items.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _setActive(items, (idx - 1 + items.length) % items.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      (active || items[0])?.click();
    }
  });

  document.addEventListener('click', e => {
    if (!e.target.closest('#global-search')) _vider(panel);
  });
}

function _vider(panel) {
  panel.innerHTML = '';
  const input = document.getElementById('global-search-input');
  input?.setAttribute('aria-expanded', 'false');
  input?.removeAttribute('aria-activedescendant');
}

function _setActive(items, newIdx) {
  items.forEach((it, i) => {
    it.classList.toggle('is-active', i === newIdx);
    it.setAttribute('aria-selected', String(i === newIdx));
  });
  const actif = items[newIdx];
  if (actif) {
    actif.scrollIntoView({ block: 'nearest' });
    document.getElementById('global-search-input')?.setAttribute('aria-activedescendant', actif.id);
  }
}

// Bouton d'edition qui porte l'identifiant de chaque resultat, dans son onglet.
const CIBLES = {
  positions: id => `#positions-tree-wrap [data-action="edit-pos"][data-id="${id}"]`,
  flux:      id => `#tab-flux [data-action="edit-flux"][data-id="${id}"]`,
  entites:   id => `#tab-entites [data-action="edit-ent"][data-id="${id}"]`,
};

/** Apres le changement d'onglet, amene la ligne choisie a l'ecran et y place
 *  le focus. Une ligne absente (filtree, repliee) laisse l'onglet tel quel. */
function _allerA(tab, id) {
  const sel = CIBLES[tab]?.(CSS.escape(String(id)));
  const btn = sel && document.querySelector(sel);
  if (!btn) return;
  const ligne = btn.closest('tr, li') || btn;
  ligne.scrollIntoView({ block: 'center' });
  btn.focus({ preventScroll: true });
}

function matchScore(text, query) {
  if (!text) return 0;
  const lower = String(text).toLowerCase();
  if (lower === query) return 3;
  if (lower.startsWith(query)) return 2;
  if (lower.includes(query)) return 1;
  return 0;
}

function searchPositions(q) {
  return _positionsCourantes()
    .map(p => {
      const score = Math.max(
        matchScore(p.owner, q),
        matchScore(p.category, q),
        matchScore(p.envelope, q),
        matchScore(p.establishment, q),
        matchScore(p.entity, q),
        matchScore(p.notes, q),
      );
      return score > 0 ? { ...p, _score: score } : null;
    })
    .filter(Boolean)
    .sort((a, b) => b._score - a._score)
    .slice(0, 8);
}

function searchFlux(q) {
  return (S.flux || [])
    .map(f => {
      const score = Math.max(
        matchScore(f.owner, q),
        matchScore(f.envelope, q),
        matchScore(f.type, q),
        matchScore(f.category, q),
        matchScore(f.notes, q),
      );
      return score > 0 ? { ...f, _score: score } : null;
    })
    .filter(Boolean)
    .sort((a, b) => b._score - a._score)
    .slice(0, 8);
}

function searchEntities(q) {
  return (S.entities || [])
    .map(e => {
      const score = Math.max(
        matchScore(e.name, q),
        matchScore(e.type, q),
        matchScore(e.comment, q),
      );
      return score > 0 ? { ...e, _score: score } : null;
    })
    .filter(Boolean)
    .sort((a, b) => b._score - a._score)
    .slice(0, 5);
}

function highlight(text, query) {
  if (!text) return '';
  const idx = String(text).toLowerCase().indexOf(query);
  if (idx === -1) return esc(text);
  const before = text.slice(0, idx);
  const match = text.slice(idx, idx + query.length);
  const after = text.slice(idx + query.length);
  return `${esc(before)}<strong>${esc(match)}</strong>${esc(after)}`;
}

function renderResults(query, panel, switchTabFn) {
  if (!query || query.length < 2) { panel.innerHTML = ''; return; }
  const q = query.toLowerCase();

  const positions = searchPositions(q);
  const flux = searchFlux(q);
  const entities = searchEntities(q);

  const input = document.getElementById('global-search-input');
  if (!positions.length && !flux.length && !entities.length) {
    panel.innerHTML = '<div class="search-no-results" role="status">Aucun résultat</div>';
    input?.setAttribute('aria-expanded', 'false');
    return;
  }
  let n = 0;
  const opt = (tab, id) => `class="search-item" role="option" aria-selected="false" id="search-opt-${n++}" data-tab="${tab}" data-id="${esc(id)}"`;
  const groupe = (id, titre, contenu) => `<div role="group" aria-labelledby="search-g-${id}">
    <div class="search-group-title" id="search-g-${id}">${titre}</div>${contenu}</div>`;

  let html = '';

  if (positions.length) {
    html += groupe('pos', 'Positions', positions.map(p => `
      <div ${opt('positions', p.id)}>
        <div class="search-item-label">
          ${highlight(p.establishment || p.envelope || p.category, q)}
          <span style="color:var(--text-muted);font-size:var(--fs-2xs);margin-left:.25rem">${esc(p.owner)} · ${esc(p.envelope)}</span>
        </div>
        <div class="search-item-amount">${fmt(p.net_attributed || p.value)}</div>
      </div>
    `).join(''));
  }

  if (flux.length) {
    html += groupe('flux', 'Flux', flux.map(f => `
      <div ${opt('flux', f.id)}>
        <div class="search-item-label">
          ${highlight(f.notes || f.envelope || f.type, q)}
          <span style="color:var(--text-muted);font-size:var(--fs-2xs);margin-left:.25rem">${esc(f.owner)} · ${fmtDate(f.date)}</span>
        </div>
        <div class="search-item-amount">${fmtSigned(fluxSigned(f))}</div>
      </div>
    `).join(''));
  }

  if (entities.length) {
    html += groupe('ent', 'Entités', entities.map(e => `
      <div ${opt('entites', e.id)}>
        <div class="search-item-label">
          ${highlight(e.name, q)}
          <span style="color:var(--text-muted);font-size:var(--fs-2xs);margin-left:.25rem">${esc(e.type || '')}</span>
        </div>
        <div class="search-item-amount">${fmt(e.gross_assets - (e.debt || 0))}</div>
      </div>
    `).join(''));
  }

  panel.innerHTML = html;
  input?.setAttribute('aria-expanded', 'true');

  // Auto-select du premier resultat pour que Enter fonctionne tout de suite
  const items = [...panel.querySelectorAll('.search-item')];
  _setActive(items, 0);

  items.forEach((item, i) => {
    item.addEventListener('click', async () => {
      const { tab, id } = item.dataset;
      _vider(panel);
      if (input) input.value = '';
      await switchTabFn(tab);
      _allerA(tab, id);
    });
    item.addEventListener('mouseenter', () => _setActive(items, i));
  });
}
