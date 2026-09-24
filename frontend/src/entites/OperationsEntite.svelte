<script lang="ts" module>
  // Le tri survit au redessin (mode discret, rechargement) et vaut pour
  // toutes les entites, comme S.sort.operations avant lui.
  let triCommun = { cle: 'date' as string | null, sens: -1 };
</script>

<script lang="ts">
  /**
   * Les operations des releves : triables, et reclassables quand le libelle
   * a trompe le classement automatique.
   *
   * Porte de static/modules/tabs/tresorerie.js (_cabler), balisage a
   * l'identique.
   */
  import { api } from '/static/modules/api.js';
  import { fmt, fmtDate, sortArr } from '/static/modules/utils.js';
  import { toast } from '/static/modules/dialogs.js';
  import EnTeteTri from '../commun/EnTeteTri.svelte';
  import type { Bloc } from './donnees-tresorerie';

  let { b, idx, natures, onRecharger }: {
    b: Bloc; idx: number; natures: Record<string, string>; onRecharger: () => Promise<void>;
  } = $props();

  let tri = $state<{ cle: string | null; sens: number }>(triCommun);
  const basculer = (cle: string) => { tri = triCommun = tri.cle === cle ? { cle, sens: -tri.sens } : { cle, sens: 1 }; };
  const lignes = $derived(sortArr(b.operations, tri.cle, tri.sens));
  const signe = (v: number) => `${v >= 0 ? '+' : '−'}${fmt(Math.abs(v))}`;

  async function reclasser(id: number, nature: string) {
    try {
      await api('PATCH', `/api/entites/operations/${id}`, { nature });
      toast('Opération reclassée', 'success');
      await onRecharger();
    } catch { /* toast deja affiche */ }
  }
</script>

<details class="treso-ops">
  <summary>Les {b.operations.length} opérations</summary>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex : zone defilante, atteignable au clavier -->
  <div class="table-scroll" tabindex="0" role="region" aria-label="Opérations de {b.entite}">
    <table class="data-table">
      <thead id="treso-thead-{idx}"><tr>
        <EnTeteTri cle="date" {tri} surTri={basculer}>Date</EnTeteTri><EnTeteTri cle="libelle" {tri} surTri={basculer}>Libellé</EnTeteTri>
        <EnTeteTri cle="nature" {tri} surTri={basculer}>Nature</EnTeteTri><EnTeteTri cle="montant" num {tri} surTri={basculer}>Montant</EnTeteTri>
        <EnTeteTri cle="banque" {tri} surTri={basculer}>Compte</EnTeteTri>
      </tr></thead>
      <tbody>
        {#each lignes as o (o.id)}
          <tr>
            <td>{fmtDate(o.date)}</td>
            <td class="treso-lib">{o.libelle}</td>
            <td><select class="filter-select" data-op={o.id} aria-label="Nature de l'opération" value={o.nature}
                        onchange={e => reclasser(o.id, e.currentTarget.value)}>
              {#each Object.entries(natures) as [k, v] (k)}<option value={k}>{v}</option>{/each}
            </select></td>
            <td class="num {o.montant >= 0 ? 'pos' : 'neg'}">{signe(o.montant)}</td>
            <td class="text-muted">{o.banque || ''}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</details>
