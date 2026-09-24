<script lang="ts">
  /**
   * Onglet Flux : l'import de documents, puis le journal. La fiche d'un flux
   * (saisie, edition, suppression) reste dans static/modules/tabs/flux.js,
   * qui charge les donnees et les passe ici.
   */
  import Import from './Import.svelte';
  import Journal from './Journal.svelte';
  import type { Flux } from './types';

  let { flux = [], owner = null, masque = false, titulaires = [], titulaireDefaut = '',
        onEditer, onSupprimer, onEnregistre }: {
    flux?: Flux[]; owner?: string | null; masque?: boolean; titulaires?: string[]; titulaireDefaut?: string;
    onEditer: (id: number) => void; onSupprimer: (id: number) => void; onEnregistre: () => void;
  } = $props();
</script>

<Journal {flux} {owner} {masque} {onEditer} {onSupprimer}>
  {#snippet entete()}
    <div class="page-header">
      <h1>Flux externes</h1>
    </div>
    <Import {titulaires} {titulaireDefaut} {onEnregistre} />
  {/snippet}
</Journal>
