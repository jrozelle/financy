<script lang="ts">
  // Bouton qui ouvre, par-dessus la page, une liste verticale de cases a
  // cocher groupees par section. Se ferme au clic dehors ou sur Echap, et
  // rend alors le focus a son bouton.
  import { tick } from 'svelte';

  export interface Choix { valeur: string; libelle: string; coche: boolean; nb?: number; aide?: string }
  export interface Section { cle: string; titre: string; choix: Choix[] }

  let { libelle, compteur = 0, sections, onBasculer, onEffacer, id }: {
    libelle: string; compteur?: number; sections: Section[]; id: string;
    onBasculer: (section: string, valeur: string) => void;
    onEffacer?: () => void;
  } = $props();

  let ouvert = $state(false);
  let racine = $state<HTMLElement>();
  let bouton = $state<HTMLButtonElement>();
  let liste = $state<HTMLElement>();

  async function ouvrir() {
    ouvert = true;
    await tick();
    liste?.querySelector<HTMLInputElement>('input')?.focus();
  }
  function fermer(rendreFocus = true) {
    if (!ouvert) return;
    ouvert = false;
    if (rendreFocus) bouton?.focus();
  }
  function dehors(e: MouseEvent) {
    if (ouvert && racine && !racine.contains(e.target as Node)) fermer(false);
  }
  function clavier(e: KeyboardEvent) {
    if (ouvert && e.key === 'Escape') { e.stopPropagation(); fermer(); }
  }
</script>

<svelte:window onclick={dehors} onkeydown={clavier} />

<div class="lac" bind:this={racine}>
  <button type="button" class="arbo-bouton lac-bouton" class:actif={compteur > 0} bind:this={bouton}
          aria-expanded={ouvert} aria-controls={id} onclick={() => (ouvert ? fermer() : ouvrir())}>
    {libelle}{#if compteur}<span class="lac-n">{compteur}</span>{/if}
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 9l6 6 6-6"/></svg>
  </button>
  {#if ouvert}
    <div class="lac-pop" {id} role="dialog" aria-label={libelle}>
      <div class="lac-liste" bind:this={liste}>
        {#each sections as s (s.cle)}
          <fieldset class="lac-section">
            <legend>{s.titre}</legend>
            {#each s.choix as c (c.valeur)}
              <label class="lac-choix" class:avec-aide={c.aide}>
                <input type="checkbox" checked={c.coche} onchange={() => onBasculer(s.cle, c.valeur)}>
                <span class="lac-texte"><span class="lac-libelle">{c.libelle}</span>
                  {#if c.aide}<span class="lac-aide">{c.aide}</span>{/if}</span>
                {#if c.nb != null}<span class="lac-nb">{c.nb}</span>{/if}
              </label>
            {/each}
          </fieldset>
        {/each}
      </div>
      {#if onEffacer}
        <div class="lac-pied">
          <button type="button" class="btn-link" disabled={!compteur} onclick={onEffacer}>Effacer</button>
          <button type="button" class="btn btn-secondary btn-sm" onclick={() => fermer()}>Fermer</button>
        </div>
      {/if}
    </div>
  {/if}
</div>
