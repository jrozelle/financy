<script lang="ts">
  // En-tete de colonne triable : clic, Entree ou Espace ; l'etat du tri est
  // annonce (aria-sort) et dessine par les classes de style.css.
  import type { Snippet } from 'svelte';

  let { cle, tri, num = false, surTri, children }: {
    cle: string; tri: { cle: string | null; sens: number }; num?: boolean;
    surTri: (cle: string) => void; children: Snippet;
  } = $props();

  const actif = $derived(tri.cle === cle);
</script>

<th data-sort={cle} tabindex="0" class:num class:sort-asc={actif && tri.sens === 1}
    class:sort-desc={actif && tri.sens === -1}
    aria-sort={actif ? (tri.sens === 1 ? 'ascending' : 'descending') : 'none'}
    onclick={() => surTri(cle)}
    onkeydown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); surTri(cle); } }}>
  {@render children()}
</th>
