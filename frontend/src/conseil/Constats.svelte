<script lang="ts">
  /**
   * Constats : ce que montrent les chiffres de l'arrete, sans hypothese de
   * profil. Ils suivent le titulaire de la barre du haut, famille comprise.
   *
   * Porte de static/modules/tabs/advisor.js (_loadConstats).
   */
  import { api } from '/static/modules/api.js';
  import { montants } from './montants';
  import type { Constat } from './types';

  let { owner = null, date = null, masque = false, visite = 0 }: {
    owner?: string | null; date?: string | null; masque?: boolean; visite?: number;
  } = $props();

  let constats = $state<Constat[] | null>(null);
  let sous = $state('Ce que montrent vos chiffres, sans hypothèse de profil.');
  let jeton = 0;
  $effect(() => {
    void visite;
    const q = new URLSearchParams();
    if (owner) q.set('owner', owner);
    if (date) q.set('date', date);
    const j = ++jeton, qui = owner;
    api<{ constats?: Constat[] }>('GET', `/api/advisor/constats?${q}`, null, { silent: true })
      .then(d => { if (j !== jeton) return; constats = d.constats || []; sous = `${qui || 'Famille'} · ce que montrent vos chiffres, sans hypothèse de profil`; })
      .catch(() => { if (j === jeton) constats = null; });
  });
  const LIB: Record<string, string> = { alerte: 'À vérifier', action: 'À faire', info: 'À savoir' };
</script>

<div class="card" id="adv-constats">
  <div class="card-head">
    <div>
      <h2>Constats</h2>
      <p class="card-sub" id="adv-constats-sous">{sous}</p>
    </div>
  </div>
  <ul class="constats" id="adv-constats-liste" aria-live="polite">
    {#key masque}
    {#if constats && !constats.length}
      <li class="constats-vide">Rien à signaler sur cet arrêté.</li>
    {:else if constats}
      {#each constats as k, i (i)}
        <li class="constat constat--{k.niveau}">
          <span class="constat-niveau">{LIB[k.niveau] || k.niveau}</span>
          <span class="constat-titre">{@html montants(k.titre)}</span>
          {#if k.onglet}<button type="button" class="constat-voir" data-tab-switch={k.onglet}>Voir</button>{:else}<span></span>{/if}
          <p class="constat-detail">{@html montants(k.detail)}</p>
        </li>
      {/each}
    {/if}
    {/key}
  </ul>
</div>
