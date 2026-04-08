import { S } from './state.js';
import { fmt, fmtDate, esc } from './utils.js';

let _debounce = null;

export function wireGlobalSearch(switchTabFn) {
  const input = document.getElementById('global-search-input');
  const panel = document.getElementById('search-results');
  if (!input || !panel) return;

  input.addEventListener('input', () => {
    clearTimeout(_debounce);
    _debounce = setTimeout(() => renderResults(input.value.trim(), panel, switchTabFn), 150);
  });

  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') { input.value = ''; panel.innerHTML = ''; input.blur(); }
  });

  document.addEventListener('click', e => {
    if (!e.target.closest('#global-search')) panel.innerHTML = '';
  });
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
  return (S.positions || [])
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

  if (!positions.length && !flux.length && !entities.length) {
    panel.innerHTML = '<div class="search-no-results">Aucun résultat</div>';
    return;
  }

  let html = '';

  if (positions.length) {
    html += '<div class="search-group-title">Positions</div>';
    html += positions.map(p => `
      <div class="search-item" data-tab="positions" data-id="${p.id}">
        <div class="search-item-label">
          ${highlight(p.establishment || p.envelope || p.category, q)}
          <span style="color:var(--text-muted);font-size:11px;margin-left:.25rem">${esc(p.owner)} · ${esc(p.envelope)}</span>
        </div>
        <div class="search-item-amount">${fmt(p.net_attributed || p.value)}</div>
      </div>
    `).join('');
  }

  if (flux.length) {
    html += '<div class="search-group-title">Flux</div>';
    html += flux.map(f => `
      <div class="search-item" data-tab="flux" data-id="${f.id}">
        <div class="search-item-label">
          ${highlight(f.notes || f.envelope || f.type, q)}
          <span style="color:var(--text-muted);font-size:11px;margin-left:.25rem">${esc(f.owner)} · ${fmtDate(f.date)}</span>
        </div>
        <div class="search-item-amount">${fmt(f.amount)}</div>
      </div>
    `).join('');
  }

  if (entities.length) {
    html += '<div class="search-group-title">Entités</div>';
    html += entities.map(e => `
      <div class="search-item" data-tab="entites" data-id="${e.id}">
        <div class="search-item-label">
          ${highlight(e.name, q)}
          <span style="color:var(--text-muted);font-size:11px;margin-left:.25rem">${esc(e.type || '')}</span>
        </div>
        <div class="search-item-amount">${fmt(e.gross_assets - (e.debt || 0))}</div>
      </div>
    `).join('');
  }

  panel.innerHTML = html;

  panel.querySelectorAll('.search-item').forEach(item => {
    item.addEventListener('click', () => {
      const tab = item.dataset.tab;
      switchTabFn(tab);
      panel.innerHTML = '';
      document.getElementById('global-search-input').value = '';
    });
  });
}
