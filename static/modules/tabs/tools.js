import { fmtDate, esc } from '../utils.js';
import { api } from '../api.js';
import { toast } from '../dialogs.js';
import { refreshDates } from '../main.js';
import { isMasked } from '../mask.js';

// La frise et la simulation sont un ecran Svelte (frontend/src/outils/,
// compile dans /dist/outils.js). Restent ici l'arrete automatique et le
// rafraichissement des cours, que le menu d'Actifs appelle aussi.

let _visite = 0;

export async function loadTimeline() {
  _visite++;
  await renderOutils();
}

/** Redessine sans recharger (mode discret). */
export async function renderOutils() {
  const cible = document.getElementById('outils-app');
  if (!cible) return;
  const { afficher } = await import('/dist/outils.js');
  afficher(cible, { masque: isMasked(), visite: _visite });
}

// ─── Auto-snapshot ───────────────────────────────────────────────────────────

export async function triggerAutoSnapshot() {
  try {
    const result = await api('POST', '/api/auto-snapshot');
    if (result.skipped) {
      toast('Un arrêté existe déjà à cette date', 'error');
    } else {
      toast(`Arrêté créé : ${result.copied} positions copiées du ${fmtDate(result.from_date)}`);
      await refreshDates();
    }
  } catch (err) { toast('Erreur à la création de l’arrêté : ' + err.message, 'error'); }
}

// ─── Refresh des cours de marche ────────────────────────────────────────────

export async function loadSchedulerStatus() {
  const el = document.getElementById('scheduler-status');
  if (!el) return;
  try {
    const s = await api('GET', '/api/scheduler/status', null, { silent: true });
    if (!s.configured) {
      el.innerHTML = 'Refresh automatique <strong>désactivé</strong> (SCHEDULER_ENABLED=false).';
      return;
    }
    if (!s.running) {
      el.innerHTML = 'Scheduler configuré mais non démarré — vérifier les logs.';
      return;
    }
    const next = s.next_run ? new Date(s.next_run).toLocaleString('fr-FR') : '—';
    el.innerHTML = `Refresh automatique <strong>actif</strong> — prochain passage : ${esc(next)} (${esc(s.timezone || '')})`;
  } catch {
    el.innerHTML = '';
  }
}

export async function triggerPricesRefresh(onlyStale = false) {
  const btnAll   = document.getElementById('btn-refresh-prices');
  const btnStale = document.getElementById('btn-refresh-prices-stale');
  const resultEl = document.getElementById('prices-refresh-result');
  if (btnAll)   btnAll.disabled = true;
  if (btnStale) btnStale.disabled = true;
  if (resultEl) resultEl.innerHTML = '<span class="text-muted">Rafraichissement en cours…</span>';

  try {
    const url = onlyStale ? '/api/prices/refresh?only_stale=1' : '/api/prices/refresh';
    const stats = await api('POST', url);
    const parts = [
      `${stats.refreshed} cours mis a jour`,
      stats.resolved_tickers ? `${stats.resolved_tickers} tickers résolus` : null,
      stats.errors ? `<span style="color:var(--danger)">${stats.errors} erreur(s)</span>` : null,
      stats.skipped ? `${stats.skipped} ignoré(s)` : null,
    ].filter(Boolean);
    let divergentHtml = '';
    if (stats.divergent && stats.divergent.length) {
      const items = stats.divergent.map(d =>
        `<li>${esc(d.isin)} (${esc(d.ticker)}) : ${d.old_price.toFixed(2)} → ${d.new_price.toFixed(2)} — <strong>ignore, verifiez le ticker</strong></li>`
      ).join('');
      divergentHtml = `<div style="color:var(--warning);margin-top:var(--esp-8);font-size:var(--fs-xs)">Cours divergents (>50%) ignores :<ul style="margin:var(--esp-4) 0">${items}</ul></div>`;
    }
    if (resultEl) {
      resultEl.innerHTML = `Provider <strong>${esc(stats.provider)}</strong> — ${parts.join(' · ')}${divergentHtml}`;
    }
    toast(stats.divergent?.length ? 'Cours rafraichis (divergences detectees)' : 'Cours rafraichis', stats.divergent?.length ? 'warning' : 'success');
  } catch (err) {
    if (resultEl) resultEl.innerHTML = `<span style="color:var(--danger)">Erreur : ${esc(err.message)}</span>`;
  } finally {
    if (btnAll)   btnAll.disabled = false;
    if (btnStale) btnStale.disabled = false;
  }
}
