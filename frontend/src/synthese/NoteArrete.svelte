<script lang="ts">
  // La note d'un arrete (« achat RP », « krach mars 2025 »), au-dessus des
  // chiffres. Son editeur reste celui de l'application (promptDialog).
  let { hote, note = null, onModifier }: { hote: HTMLElement; note?: string | null; onModifier: () => void } = $props();
  $effect(() => { hote.style.display = note ? '' : 'none'; });
</script>

{#if note}
  <div class="snapshot-note">
    <span class="snapshot-note-icon">Note</span>
    <span class="snapshot-note-text">{note}</span>
    <button type="button" class="btn-link" id="btn-edit-snapshot-note" aria-label="Modifier la note de l’arrêté"
            onclick={onModifier}>Modifier</button>
  </div>
{/if}
