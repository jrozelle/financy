<script lang="ts">
  /**
   * Impot sur les societes : les exercices clos (d'apres les comptes du
   * cabinet) et l'estimation de l'exercice en cours, deficits imputes. Une
   * ligne vide en fin de tableau sert a saisir l'exercice suivant.
   *
   * Porte de static/modules/tabs/tresorerie.js (_fiscal), balisage a
   * l'identique.
   */
  import { api } from '/static/modules/api.js';
  import { fmt, parseLocaleNumber } from '/static/modules/utils.js';
  import { toast } from '/static/modules/dialogs.js';
  import type { Bloc } from './donnees-tresorerie';

  let { b, idx, onRecharger }: { b: Bloc; idx: number; onRecharger: () => Promise<void> } = $props();

  const f = $derived(b.fiscal);
  const p = $derived(f?.projection);
  interface Saisie { fin: string; resultat: string; source: string }
  let lignes = $state<Saisie[]>([]);
  $effect.pre(() => {
    lignes = [...(b.fiscal?.exercices || []), {}].map(e => ({ fin: e.fin || '', resultat: String(e.resultat ?? ''), source: e.source || '' }));
  });

  async function enregistrer() {
    const exercices = lignes.map(l => ({ fin: l.fin.trim(), resultat: l.resultat.trim() === '' ? null : parseLocaleNumber(l.resultat, null),
                                         source: l.source.trim() || null })).filter(e => e.fin);
    try {
      await api('PUT', `/api/entites/${encodeURIComponent(b.entite)}/exercices`, { exercices });
      toast('Exercices enregistrés', 'success');
      onRecharger();
    } catch { /* toast deja affiche */ }
  }
</script>

<details class="treso-parts treso-fisc">
  <summary>Impôt sur les sociétés{f ? ` : ${f.impot > 0 ? fmt(f.impot) + ' estimés' : 'pas d’impôt estimé'} en ${f.annee}` : ''}</summary>
  {#if f && p}
    <p class="treso-fiscal">Exercice {f.annee}, projeté sur l'année : {fmt(p.revenus)} de revenus,
      {fmt(p.interets)} d'intérêts et d'assurance, {fmt(p.frais)} de frais, soit un résultat de
      <b>{p.resultat >= 0 ? '' : '−'}{fmt(Math.abs(p.resultat))}</b>.
      {#if f.impot > 0}Impôt estimé : <b>{fmt(f.impot)}</b>, après {fmt(f.deficit_reportable)} de déficits reportés.{:else}<b>Pas
        d'impôt</b> : {p.resultat < 0 ? 'nouveau déficit' : 'bénéfice absorbé par les déficits antérieurs'},
        {fmt(f.deficit_apres)} de déficits restant à reporter.{/if}
      Estimation en trésorerie, le cabinet travaille en droits constatés.</p>
  {/if}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex : zone defilante, atteignable au clavier -->
  <div class="table-scroll" tabindex="0" role="region" aria-label="Exercices clos de {b.entite}">
    <table class="data-table" data-exercices={idx}>
      <thead><tr><th>Exercice clos le</th><th class="num">Résultat fiscal</th><th>Source</th></tr></thead>
      <tbody>
        {#each lignes as l, j (j)}
          <tr><td><input type="date" class="ref-input" data-k="fin" bind:value={l.fin} aria-label="Clôture de l'exercice"></td>
            <td class="num"><input type="text" inputmode="decimal" class="ref-input treso-prix" data-k="resultat" bind:value={l.resultat} aria-label="Résultat fiscal"></td>
            <td><input type="text" class="ref-input" data-k="source" bind:value={l.source} aria-label="Source"></td></tr>
        {/each}
      </tbody>
    </table>
  </div>
  <p class="treso-note">Un résultat négatif est un déficit, reporté sur les bénéfices suivants.</p>
  <div class="treso-parts-actions">
    <button type="button" class="btn btn-primary btn-sm" data-exercices-enregistrer={idx} onclick={enregistrer}>Enregistrer les exercices</button>
  </div>
</details>
