<script lang="ts">
  /**
   * « Ce qui a bouge » : par compte, depuis l'arrete precedent. On lit un
   * compte puis son chiffre, libelle a gauche, montant a droite ; l'avant et
   * l'apres se deplient au clic, a l'ecran plutot que dans une infobulle.
   *
   * Porte de static/modules/tabs/synthese.js (renderSnapshotDiff).
   */
  import { api } from '/static/modules/api.js';
  import { fmt, fmtDate, fmtPct } from '/static/modules/utils.js';

  interface Mouvement { label?: string; owner?: string; establishment?: string; status: 'new' | 'closed' | 'changed';
                        delta: number; net_before: number; net_after: number }
  interface Reponse { from_date?: string; to_date?: string; movements?: Mouvement[]; totals?: { delta?: number } }

  let { owner = null, famille = true, date = null, masque = false }: {
    owner?: string | null; famille?: boolean; date?: string | null; masque?: boolean;
  } = $props();

  let donnees = $state<Reponse | null>(null);
  let charge = $state(false);
  let cleVue = '';
  let jeton = 0;
  $effect(() => {
    const params = new URLSearchParams({ date: date || '' });
    if (!famille && owner) params.set('owner', owner);
    const cle = String(params);
    if (cle === cleVue) return;
    cleVue = cle;
    const j = ++jeton;
    api<Reponse>('GET', `/api/snapshot-diff?${params}`, null, { silent: true })
      .then(d => { if (j === jeton) { donnees = d; charge = true; ouverts = new Set(); tout = false; } })
      .catch(() => { if (j === jeton) { donnees = null; charge = false; } });
  });

  const VISIBLES = 6;
  const mouvements = $derived((donnees?.movements || []).filter(m => Math.abs(m.delta) >= 1 || m.status !== 'changed'));
  let ouverts = $state(new Set<number>());
  let tout = $state(false);
  const basculer = (i: number) => { const s = new Set(ouverts); s.has(i) ? s.delete(i) : s.add(i); ouverts = s; };
  const total = $derived(donnees?.totals?.delta || 0);
</script>

<h2>Ce qui a bougé</h2>
<p class="card-sub">Par compte, depuis l'arrêté précédent · une ligne se déplie</p>
<div id="snapshot-diff">
  {#key masque}
  {#if charge && donnees}
    {#if !donnees.from_date}
      <p class="text-muted" style="font-size:var(--fs-sm)">Aucun arrêté précédent à comparer.</p>
    {:else if !mouvements.length}
      <p class="text-muted" style="font-size:var(--fs-sm)">Aucun mouvement depuis le {fmtDate(donnees.from_date)}.</p>
    {:else}
      {@const d = donnees}
      <p class="mv-total">Variation nette
        <b class={total >= 0 ? 'pos' : 'neg'}>{total >= 0 ? '+' : ''}{fmt(total)}</b> depuis le {fmtDate(d.from_date)}</p>
      <div class="mv-liste">
        {#each mouvements as m, i (i)}
          <div class="mv-item" data-mv-reste={i >= VISIBLES ? '' : undefined} hidden={i >= VISIBLES && !tout}>
            <button type="button" class="mv-ligne" aria-expanded={ouverts.has(i)} onclick={() => basculer(i)}>
              <span class="mv-ou">{m.label || '—'}{#if m.status === 'new'} <span class="h-badge h-badge-fresh">nouveau</span>{:else if m.status === 'closed'} <span
                class="h-badge h-badge-expired">clôturé</span>{/if}</span>
              <span class="mv-montant {m.delta >= 0 ? 'pos' : 'neg'}">{m.delta >= 0 ? '+' : '−'}{fmt(Math.abs(m.delta))}</span>
              <span class="mv-qui">{[m.owner, m.establishment].filter(Boolean).join(' · ')}</span>
            </button>
            <p class="mv-detail" hidden={!ouverts.has(i)}>{#if m.status === 'new'}Ouvert depuis le {fmtDate(d.from_date)} : {fmt(m.net_after)} au {fmtDate(d.to_date)}
              {:else if m.status === 'closed'}{fmt(m.net_before)} au {fmtDate(d.from_date)}, absent au {fmtDate(d.to_date)}
              {:else}{fmt(m.net_before)} au {fmtDate(d.from_date)} → {fmt(m.net_after)} au {fmtDate(d.to_date)}{m.net_before
                ? ` (${fmtPct((m.net_after / m.net_before - 1) * 100, 1, true)})` : ''}{/if}</p>
          </div>
        {/each}
      </div>
      {#if mouvements.length > VISIBLES}
        <button type="button" class="btn-link mv-plus" aria-expanded={tout} onclick={() => tout = !tout}>
          {tout ? 'Réduire' : `Voir les ${mouvements.length - VISIBLES} autres comptes`}</button>
      {/if}
    {/if}
  {/if}
  {/key}
</div>
