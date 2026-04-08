import { S } from './state.js';

export const fmt = (n, dec = 0) => {
  if (n == null) return '—';
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  }).format(n) + '\u202f€';
};

export const fmtDate = d => {
  if (!d) return '—';
  const [y, m, day] = d.split('-');
  return `${day}/${m}/${y}`;
};

export const liqBadge = liq => {
  const map = {
    'J0\u2013J1':  'badge-j01',
    'J2\u2013J7':  'badge-j27',
    'J8\u2013J30': 'badge-j830',
    '30J+':        'badge-30',
    'Bloqu\u00e9': 'badge-blk',
  };
  return `<span class="badge ${map[liq] || 'badge-blk'}">${liq || '—'}</span>`;
};

export const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

export const fmtDelta = (n, dec = 0) => {
  if (n == null || n === 0) return '';
  const sign = n > 0 ? '+' : '';
  return sign + new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  }).format(n) + '\u202f\u20ac';
};

export function kpiDelta(variation, deltaKey, pctKey = null, { invert = false, label = null } = {}) {
  if (!variation) return '';
  const delta = variation[deltaKey];
  if (delta == null || delta === 0) return '';
  const positive = invert ? delta < 0 : delta > 0;
  const cls = positive ? 'kpi-delta-pos' : 'kpi-delta-neg';
  const arrow = delta > 0 ? '\u25b2' : '\u25bc';
  let pctStr = '';
  if (pctKey && variation[pctKey] != null) {
    const pct = variation[pctKey];
    pctStr = ` (${pct > 0 ? '+' : ''}${pct.toFixed(1)}\u202f%)`;
  }
  const labelStr = label ? `<span class="kpi-delta-label">${label}</span> ` : '';
  return `<div class="${cls}">${labelStr}${arrow} ${fmtDelta(delta)}${pctStr}</div>`;
}

export const today = () => new Date().toISOString().slice(0, 10);

export function sortArr(arr, key, dir) {
  if (!key) return arr;
  return [...arr].sort((a, b) => {
    const va = a[key] ?? '';
    const vb = b[key] ?? '';
    if (typeof va === 'number' && typeof vb === 'number') return dir * (va - vb);
    return dir * String(va).localeCompare(String(vb), 'fr', { sensitivity: 'base' });
  });
}

export function wireSortableTable(theadId, stateKey, rerenderFn) {
  const thead = document.getElementById(theadId);
  if (!thead) return;
  thead.querySelectorAll('th[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      const st  = S.sort[stateKey];
      if (st.key === key) {
        st.dir = -st.dir;
      } else {
        st.key = key;
        st.dir = 1;
      }
      rerenderFn();
    });
  });
}

export function updateSortIndicators(theadId, stateKey) {
  const thead = document.getElementById(theadId);
  if (!thead) return;
  const { key, dir } = S.sort[stateKey];
  thead.querySelectorAll('th[data-sort]').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.sort === key) th.classList.add(dir === 1 ? 'sort-asc' : 'sort-desc');
  });
}

// ─── Chart color cache (invalidated on theme change) ─────────────────────
let _colorCache = null;
let _cachedTheme = null;

function _readTheme() {
  return document.documentElement.dataset.theme || 'light';
}

function _ensureCache() {
  const theme = _readTheme();
  if (_colorCache && _cachedTheme === theme) return;
  const s = getComputedStyle(document.documentElement);
  _colorCache = {
    palette: Array.from({ length: 11 }, (_, i) => s.getPropertyValue(`--chart-${i + 1}`).trim()),
    border:  s.getPropertyValue('--chart-border').trim() || '#fff',
    family: {
      line: s.getPropertyValue('--chart-family').trim() || '#111827',
      bg:   s.getPropertyValue('--chart-family-bg').trim() || 'rgba(17,24,39,.06)',
    },
  };
  _cachedTheme = theme;
}

export function getColors() { _ensureCache(); return _colorCache.palette; }

export function chartBorderColor() { _ensureCache(); return _colorCache.border; }

export function chartFamilyColors() { _ensureCache(); return _colorCache.family; }

export function doughnutConfig(labels, data) {
  const colors = getColors();
  return {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: colors.slice(0, labels.length),
        borderWidth: 2,
        borderColor: chartBorderColor(),
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'right', labels: { font: { size: 11 }, padding: 10, boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: ctx => {
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const pct = ((ctx.parsed / total) * 100).toFixed(1);
              return ` ${new Intl.NumberFormat('fr-FR').format(Math.round(ctx.parsed))}\u202f€  (${pct}%)`;
            },
          },
        },
      },
    },
  };
}

export const liqText = l => l ? `Liq. ${l}` : '';

/**
 * Destroy a Chart.js instance safely and return null (for re-assignment).
 * Usage: myChart = destroyChart(myChart);
 */
export function destroyChart(chart) {
  if (chart) chart.destroy();
  return null;
}

// ─── Tree utilities ────────────────────────────────────────────────────────

export function treeToggleRow(row, expand) {
  const children = row.nextElementSibling;
  if (!children || !children.classList.contains('tree-children')) return;
  children.style.display = expand ? '' : 'none';
  const tog = row.querySelector(':scope > .tree-toggle');
  if (tog) tog.textContent = expand ? '▾' : '▸';
  children.querySelectorAll('.tree-children').forEach(el => {
    el.style.display = expand ? '' : 'none';
  });
  children.querySelectorAll('.tree-toggle').forEach(t => {
    t.textContent = expand ? '▾' : '▸';
  });
}

export function treeExpandCollapse(containerId, expand, levelClass = null) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!levelClass) {
    container.querySelectorAll('.tree-owner, .tree-etabl, .tree-env')
      .forEach(row => treeToggleRow(row, expand));
    return;
  }

  if (expand) {
    const parents = {
      'tree-env':   ['tree-owner', 'tree-etabl'],
      'tree-etabl': ['tree-owner'],
      'tree-owner': [],
    };
    for (const parentClass of (parents[levelClass] || [])) {
      container.querySelectorAll('.' + parentClass).forEach(row => {
        const children = row.nextElementSibling;
        if (!children || !children.classList.contains('tree-children')) return;
        children.style.display = '';
        const tog = row.querySelector(':scope > .tree-toggle');
        if (tog) tog.textContent = '▾';
      });
    }
    container.querySelectorAll('.' + levelClass).forEach(row => {
      const children = row.nextElementSibling;
      if (!children || !children.classList.contains('tree-children')) return;
      children.style.display = '';
      const tog = row.querySelector(':scope > .tree-toggle');
      if (tog) tog.textContent = '▾';
    });
  } else {
    container.querySelectorAll('.' + levelClass).forEach(row => treeToggleRow(row, false));
  }
}

export function treeFilter(containerId, query) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const q = query.trim().toLowerCase();

  if (!q) {
    container.querySelectorAll('.tree-owner-section, .tree-children, .tree-row').forEach(el => {
      el.style.display = '';
    });
    container.querySelectorAll('.tree-toggle').forEach(t => t.textContent = '▾');
    return;
  }

  container.querySelectorAll('.tree-owner-section').forEach(s => s.style.display = 'none');
  container.querySelectorAll('.tree-children').forEach(c => c.style.display = 'none');
  container.querySelectorAll('.tree-row').forEach(r => r.style.display = 'none');

  container.querySelectorAll('.tree-pos-leaf, .tree-cat').forEach(leaf => {
    const text = leaf.textContent.toLowerCase();
    if (!text.includes(q)) return;

    leaf.style.display = '';
    let el = leaf.parentElement;
    while (el && el !== container) {
      if (el.classList.contains('tree-children') || el.classList.contains('tree-owner-section')) {
        el.style.display = '';
      }
      if (el.classList.contains('tree-children')) {
        const row = el.previousElementSibling;
        if (row && row.classList.contains('tree-row')) {
          row.style.display = '';
          const tog = row.querySelector('.tree-toggle');
          if (tog) tog.textContent = '▾';
        }
      }
      el = el.parentElement;
    }
  });
}

export function wireTreeAccordion(container, skipActionsCheck = false) {
  container.querySelectorAll('.tree-owner, .tree-etabl, .tree-env').forEach(row => {
    row.addEventListener('click', ev => {
      if (!skipActionsCheck && ev.target.closest('.tree-actions')) return;
      const children = row.nextElementSibling;
      if (!children || !children.classList.contains('tree-children')) return;
      const expand = children.style.display === 'none';
      treeToggleRow(row, expand);
    });
  });
}
