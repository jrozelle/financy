<script lang="ts">
  /**
   * Tableau des entites (SCI, indivision, holding) : valeur, dette, net,
   * detenteurs et historique des valeurs. La fiche d'une entite et le panneau
   * de son historique restent dans static/modules/tabs/entities.js.
   *
   * Vue d'un titulaire : ses seules entites, et sa part sous chaque montant —
   * brut a sa part de propriete, dette a sa part de dette (66 / 34 sur une
   * residence detenue a moitie). L'entite reste montree entiere : la part se
   * lit contre le tout.
   *
   * Porte de static/modules/tabs/entities.js (renderEntities), balisage a
   * l'identique.
   */
  import { fmt, fmtDate, sortArr } from '/static/modules/utils.js';
  import EnTeteTri from '../commun/EnTeteTri.svelte';
  import type { Entite, ArreteEntite, PositionLiee } from './types';

  let { entites = [], arretes = [], positions = [], owner = null, masque = false,
        onEditer, onSupprimer, onHistorique, onAjouterPosition }: {
    entites?: Entite[]; arretes?: ArreteEntite[]; positions?: PositionLiee[]; owner?: string | null; masque?: boolean;
    onEditer: (id: number) => void; onSupprimer: (id: number) => void;
    onHistorique: (nom: string) => void; onAjouterPosition: (nom: string) => void;
  } = $props();

  let tri = $state<{ cle: string | null; sens: number }>({ cle: null, sens: 1 });
  const basculer = (cle: string) => { tri = tri.cle === cle ? { cle, sens: -tri.sens } : { cle, sens: 1 }; };

  const visibles = $derived(owner ? entites.filter(e => positions.some(p => p.entity === e.name && p.owner === owner)) : entites);
  const lignes = $derived(sortArr(visibles, tri.cle, tri.sens).map(e => {
    const liees = positions.filter(p => p.entity === e.name);
    const siennes = owner ? liees.filter(p => p.owner === owner) : [];
    const totalPct = liees.reduce((s, p) => s + (p.ownership_pct || 0), 0);
    return {
      e, liees, totalPct,
      pPart: siennes.reduce((t, p) => t + (p.ownership_pct || 0), 0),
      dPart: siennes.reduce((t, p) => t + (p.debt_pct ?? p.ownership_pct ?? 0), 0),
      nature: [e.type, e.valuation_mode && e.valuation_mode.toLowerCase()].filter(Boolean).join(' · '),
      // Les arretes arrivent du plus recent au plus ancien.
      snaps: arretes.filter(s => s.entity_name === e.name),
    };
  }));
  const pc = (v: number) => Math.round(v * 100);
</script>

<div class="page-header">
  <h1>Entités (SCI / Indivision)</h1>
</div>
<div class="card card-table">
  <table class="data-table">
    <thead id="entities-thead">
      <tr>
        <EnTeteTri cle="name" {tri} surTri={basculer}>Entité</EnTeteTri>
        <EnTeteTri cle="gross_assets" num {tri} surTri={basculer}>Valeur</EnTeteTri>
        <EnTeteTri cle="debt" num {tri} surTri={basculer}>Dette</EnTeteTri>
        <EnTeteTri cle="net_assets" num {tri} surTri={basculer}>Net</EnTeteTri>
        <th>Détenteurs</th>
        <th>Historique</th>
        <th></th>
      </tr>
    </thead>
    <tbody id="entities-tbody">
      {#key masque}
      {#if !entites.length}
        <tr class="empty-row"><td colspan="7">Aucune entité. Ajoutez une SCI ou une indivision.</td></tr>
      {:else if owner && !visibles.length}
        <tr class="empty-row"><td colspan="7">{owner} ne détient de parts dans aucune entité.</td></tr>
      {:else}
        {#each lignes as { e, liees, totalPct, pPart, dPart, nature, snaps } (e.id)}
          <tr>
            <td class="ent-nom"><strong>{e.name}</strong>{#if nature}<div class="ent-note">{nature}</div>{/if}{#if e.comment}<div
              class="ent-note">{e.comment}</div>{/if}</td>
            <td class="num ent-valeur" data-lib="Valeur">{fmt(e.gross_assets)}{#if owner}<div
              class="ent-part">part de {owner} : {fmt(e.gross_assets * pPart)} · {pc(pPart)} %</div>{/if}</td>
            <td class="num ent-dette" class:neg={e.debt > 0} data-lib="Dette">{e.debt > 0 ? fmt(e.debt) : '—'}{#if e.debt > 0 && owner}<div
              class="ent-part">part de {owner} : {fmt(e.debt * dPart)} · {pc(dPart)} %</div>{/if}</td>
            <td class="num ent-net {e.net_assets < 0 ? 'neg' : 'pos'}">{fmt(e.net_assets)}{#if owner}<div
              class="ent-part">part de {owner} : {fmt(e.gross_assets * pPart - (e.debt || 0) * dPart)}</div>{/if}</td>
            <td class="ent-detenteurs">{#each liees as p, i (i)}<span class="badge badge-j27">{p.owner} {pc(p.ownership_pct || 0)} %</span>{/each}{#if !liees.length}<span
              class="ent-note">Aucune position liée</span>{/if}{#if liees.length && totalPct > 1.01}<div
              class="ent-alerte">Total {pc(totalPct)} % : les parts dépassent l'entité</div>{:else if liees.length && totalPct < 0.99}<div
              class="ent-note">{pc(1 - totalPct)} % hors foyer</div>{/if}</td>
            <td class="ent-c-histo">{#if snaps.length}<button class="btn-icon ent-histo" data-id={e.id} data-name={e.name} data-action="snap-hist"
              onclick={() => onHistorique(e.name)}>{snaps.length} valeur{snaps.length > 1 ? 's' : ''}<span>{fmtDate(snaps[0].date)}</span></button>{:else}<span
              class="ent-note">—</span>{/if}</td>
            <td class="ent-actions">
              <button class="btn-icon add" data-action="add-pos-entity" data-name={e.name} onclick={() => onAjouterPosition(e.name)}>+ Position</button>
              <button class="btn-icon edit" data-id={e.id} data-action="edit-ent" onclick={() => onEditer(e.id)}>Éditer</button>
              <button class="btn-icon del" data-id={e.id} data-action="del-ent" aria-label="Supprimer {e.name}" onclick={() => onSupprimer(e.id)}>Supprimer</button>
            </td>
          </tr>
        {/each}
      {/if}
      {/key}
    </tbody>
  </table>
</div>
