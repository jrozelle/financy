<script lang="ts">
  /**
   * Propositions d'arbitrage : ce qui rapprocherait le patrimoine financier
   * de la cible, en ne puisant que dans l'argent libre, et les leviers
   * fiscaux chiffres. Chacune s'applique, s'ecarte ou revient en attente.
   *
   * Porte de static/modules/tabs/advisor.js (_loadProposals et suivants).
   */
  import { api } from '/static/modules/api.js';
  import { toast } from '/static/modules/dialogs.js';
  import { montants } from './montants';
  import type { Proposition } from './types';

  let { proprietaire = null, version = 0, masque = false }: {
    proprietaire?: string | null; version?: number; masque?: boolean;
  } = $props();

  const GENRES: Record<string, string> = { bucket: 'Poche', fiscal: 'Fiscalité', security: 'Ligne' };
  let statut = $state('pending');
  let liste = $state<Proposition[] | null>(null);
  let rechargement = $state(0);
  let enCours = $state(false);
  let jeton = 0;
  $effect(() => {
    void version; void rechargement;
    if (!proprietaire) return;
    const base = `/api/advisor/profiles/${encodeURIComponent(proprietaire)}/proposals`;
    const j = ++jeton;
    api<Proposition[]>('GET', statut ? `${base}?status=${statut}` : base, null, { silent: true })
      .then(l => { if (j === jeton) liste = l; }).catch(() => {});
  });

  async function generer() {
    if (!proprietaire) return;
    enCours = true;
    try {
      const r = await api<{ count: number }>('POST', `/api/advisor/profiles/${encodeURIComponent(proprietaire)}/proposals/refresh`);
      toast(`${r.count} proposition(s) générée(s)`, 'success');
      statut = 'pending';
      rechargement++;
    } catch { /* toast deja affiche */ } finally { enCours = false; }
  }
  async function changer(id: number, s: string) {
    try {
      await api('PATCH', `/api/advisor/proposals/${id}`, { status: s });
      rechargement++;
    } catch { /* toast deja affiche */ }
  }
</script>

<div class="card" id="adv-proposals">
  <h2>Propositions d'arbitrage</h2>
  <p class="text-muted" style="font-size:var(--fs-sm);margin-bottom:.875rem">
    Ce qui rapprocherait le patrimoine financier de la cible du profil, en ne puisant
    que dans l'argent libre, et les leviers fiscaux chiffrés.
  </p>
  <div style="display:flex;gap:.5rem;align-items:center;margin-bottom:.875rem;flex-wrap:wrap">
    <button type="button" class="btn btn-primary" id="btn-proposals-refresh" class:is-loading={enCours} disabled={enCours}
            onclick={generer}>{enCours ? 'Calcul…' : 'Générer les propositions'}</button>
    <select id="proposals-filter" class="filter-select" style="margin-left:auto" aria-label="Afficher les propositions" bind:value={statut}>
      <option value="">Tous</option>
      <option value="pending">En attente</option>
      <option value="applied">Appliquées</option>
      <option value="dismissed">Écartées</option>
    </select>
  </div>
  <div id="proposals-empty" class="text-muted" style="font-size:var(--fs-sm);font-style:italic" style:display={liste && !liste.length ? null : 'none'}>
    Aucune proposition. Cliquez « Générer » pour les calculer.
  </div>
  <div id="proposals-list" class="proposals-list">
    {#key masque}
    {#each liste || [] as p (p.id)}
      <div class="proposal-item kind-{p.kind} status-{p.status}" data-pid={p.id}>
        <div class="proposal-head">
          <div>
            <span class="proposal-kind">{GENRES[p.kind] || p.kind}</span>
            <strong style="margin-left:.4rem">{@html montants(p.label)}</strong>
          </div>
          <div class="proposal-actions">
            {#if p.status === 'pending'}
              <button type="button" class="btn-icon" data-action="apply" onclick={() => changer(p.id, 'applied')}>Appliquer</button>
              <button type="button" class="btn-icon" data-action="dismiss" onclick={() => changer(p.id, 'dismissed')}>Écarter</button>
            {:else}
              <button type="button" class="btn-icon" data-action="reset" onclick={() => changer(p.id, 'pending')}>Remettre en attente</button>
            {/if}
          </div>
        </div>
        {#if p.rationale}<div class="proposal-rationale">{@html montants(p.rationale)}</div>{/if}
      </div>
    {/each}
    {/key}
  </div>
</div>
