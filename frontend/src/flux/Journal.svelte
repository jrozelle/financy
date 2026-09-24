<script lang="ts">
  /**
   * Journal des flux externes : versements, retraits, coupons, frais.
   *
   * Filtres par type, categorie et annee (memorises en base) ; le titulaire
   * est celui de l'en-tete. Affichage par pages de cent — trois cents fiches
   * faisaient une page de 20 000 px sur mobile — mais filtres, tri et totaux
   * portent sur l'ensemble, et le decompte le dit. La fiche d'un flux (saisie,
   * suppression) reste dans static/modules/tabs/flux.js.
   *
   * Porte de static/modules/tabs/flux.js (renderFlux), balisage a l'identique.
   */
  import { fmtDate, sortArr, fluxSigned as signe, fmtSigned } from '/static/modules/utils.js';
  import { lirePref, ecrirePref } from '/static/modules/preferences.js';
  import EnTeteTri from '../commun/EnTeteTri.svelte';
  import type { Snippet } from 'svelte';
  import type { Flux } from './types';

  let { flux = [], owner = null, masque = false, onEditer, onSupprimer, entete }: {
    flux?: Flux[]; owner?: string | null; masque?: boolean;
    onEditer: (id: number) => void; onSupprimer: (id: number) => void;
    /** Titre et import, en tete de la barre d'outils, au-dessus des filtres. */
    entete?: Snippet;
  } = $props();

  // ── Filtres ────────────────────────────────────────────────────────────
  const CLE = 'financy_filters_flux';
  const lire = () => { try { return JSON.parse(lirePref(CLE) || '') || {}; } catch { return {}; } };
  let filtre = $state<{ type: string; category: string; year: string }>({ type: '', category: '', year: '', ...lire() });
  const memoriser = () => ecrirePref(CLE, JSON.stringify(filtre));
  function effacer() { filtre = { type: '', category: '', year: '' }; ecrirePref(CLE, null); }

  const uniques = (vals: (string | null | undefined)[]) => [...new Set(vals.filter(Boolean) as string[])].sort();
  const types = $derived(uniques(flux.map(f => f.type)));
  const categories = $derived(uniques(flux.map(f => f.category)));
  const annees = $derived(uniques(flux.map(f => f.date?.slice(0, 4))).reverse());
  // Une colonne vide sur toutes les lignes n'apprend rien : la categorie ne
  // s'affiche, avec son filtre, que si un flux au moins en porte une.
  const avecCat = $derived(flux.some(f => f.category));
  // Une valeur memorisee absente des donnees ne filtre pas.
  const actif = (v: string, liste: string[]) => (v && liste.includes(v) ? v : '');

  let tri = $state<{ cle: string | null; sens: number }>({ cle: null, sens: 1 });
  const basculer = (cle: string) => { tri = tri.cle === cle ? { cle, sens: -tri.sens } : { cle, sens: 1 }; };

  const tous = $derived.by(() => {
    const t = actif(filtre.type, types), c = avecCat ? actif(filtre.category, categories) : '', a = actif(filtre.year, annees);
    return sortArr(flux.filter(f =>
      (!owner || f.owner === owner) && (!t || f.type === t) && (!c || f.category === c) && (!a || f.date?.startsWith(a))),
      tri.cle, tri.sens);
  });

  // ── Pages ──────────────────────────────────────────────────────────────
  const PAGE = 100;
  let limite = $state(PAGE);
  $effect(() => { void tous; limite = PAGE; });
  const visibles = $derived(tous.slice(0, limite));
  const reste = $derived(tous.length - visibles.length);
  let corps = $state<HTMLElement>();
  let bouton = $state<HTMLElement>();
  async function suivants() {
    const deja = limite;
    limite += PAGE;
    await Promise.resolve();
    // Le focus va a la premiere ligne ajoutee ; le bouton disparait une fois tout affiche.
    (bouton || corps?.querySelectorAll('tr.fx-ligne')[deja]?.querySelector('button'))?.focus();
  }

  // ── Totaux, sur tout le filtre ─────────────────────────────────────────
  const totaux = $derived.by(() => {
    const parType: Record<string, number> = {}, parTitulaire: Record<string, number> = {};
    let total = 0;
    for (const f of tous) {
      const v = signe(f);
      total += v;
      parType[f.type || 'Autre'] = (parType[f.type || 'Autre'] || 0) + v;
      parTitulaire[f.owner] = (parTitulaire[f.owner] || 0) + v;
    }
    return { total, parType: Object.entries(parType), parTitulaire: Object.entries(parTitulaire) };
  });
  // En 11 px gras, l'espace fine des milliers ne se voyait plus : le pied
  // prend une espace insecable ordinaire.
  const pied = (v: number) => fmtSigned(v).replace(/ /g, ' ');
  const sansEtab = $derived(tous.filter(f => !f.establishment).length);

  /** Marqueurs fonctionnels des notes, en badges ; la note n'est pas
   *  modifiee : « [provisoire] » est lu par l'import des releves. */
  const MARQUES: Record<string, [string, string]> = { import: ['importé', 'badge-blk'], provisoire: ['provisoire', 'badge-j830'] };
  function notes(n: string | null) {
    if (!n) return { badges: [] as [string, string][], texte: '' };
    const badges: [string, string][] = [];
    const texte = n.replace(/\[(import|provisoire)\]/gi, (_, m: string) => { badges.push(MARQUES[m.toLowerCase()]); return ' '; })
      .replace(/\s+/g, ' ').trim();
    return { badges, texte };
  }
  const stylePied = 'font-size:var(--fs-2xs);color:var(--text-muted);white-space:normal;max-width:none';
  const EDITER = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
  const SUPPR = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/></svg>';
</script>

<div class="page-toolbar">
{@render entete?.()}
<div class="filters-bar" id="flux-filters">
  <select id="flux-filter-type" class="filter-select" aria-label="Type de flux" bind:value={filtre.type} onchange={memoriser}>
    <option value="">Tous les types</option>{#each types as t (t)}<option value={t}>{t}</option>{/each}</select>
  <select id="flux-filter-category" class="filter-select" aria-label="Catégorie" hidden={!avecCat} bind:value={filtre.category} onchange={memoriser}>
    <option value="">Toutes les catégories</option>{#each categories as c (c)}<option value={c}>{c}</option>{/each}</select>
  <select id="flux-filter-year" class="filter-select" aria-label="Année" bind:value={filtre.year} onchange={memoriser}>
    <option value="">Toutes les années</option>{#each annees as a (a)}<option value={a}>{a}</option>{/each}</select>
  <button class="btn btn-secondary btn-sm" id="btn-clear-flux-filters" onclick={effacer}>Effacer filtres</button>
</div>
</div>
<!-- L'explication du badge « a preciser » se lit une fois, avec son decompte. -->
<p id="flux-note-etab" class="import-alerte" hidden={!tous.length || !sansEtab}>{tous.length && sansEtab
  ? `${sansEtab} flux sans établissement (« à préciser ») : chacun est réparti au prorata entre les comptes de son enveloppe, ce qui fausse le rendement de chaque compte. Éditez-les pour indiquer l'établissement.` : ''}</p>
<div class="card card-table">
  <table class="data-table">
    <thead id="flux-thead">
      <tr>
        <EnTeteTri cle="date" {tri} surTri={basculer}>Date</EnTeteTri>
        <EnTeteTri cle="owner" {tri} surTri={basculer}>Titulaire</EnTeteTri>
        <EnTeteTri cle="envelope" {tri} surTri={basculer}>Enveloppe</EnTeteTri>
        <EnTeteTri cle="establishment" {tri} surTri={basculer}>Établissement</EnTeteTri>
        {#if avecCat}<EnTeteTri cle="category" {tri} surTri={basculer}>Catégorie</EnTeteTri>{/if}
        <EnTeteTri cle="type" {tri} surTri={basculer}>Type</EnTeteTri>
        <EnTeteTri cle="amount" num {tri} surTri={basculer}>Montant</EnTeteTri>
        <th>Notes</th>
        <th></th>
      </tr>
    </thead>
    <tbody id="flux-tbody" bind:this={corps}>
      {#key masque}
      {#if !tous.length}
        <tr class="empty-row"><td colspan={avecCat ? 9 : 8}>{flux.length ? 'Aucun flux pour ce filtre.' : 'Aucun flux enregistré.'}</td></tr>
      {:else}
        {#each visibles as f (f.id)}
          {@const n = notes(f.notes)}
          <tr class="fx-ligne">
            <td class="fx-date">{fmtDate(f.date)}</td>
            <td class="fx-qui">{f.owner}</td>
            <td class="fx-env">{f.envelope || '—'}</td>
            <td class="fx-etab">{#if f.establishment}{f.establishment}{:else}<span class="badge badge-blk">à préciser</span>{/if}</td>
            {#if avecCat}<td class="fx-cat">{f.category || '—'}</td>{/if}
            <td class="fx-type">{f.type || '—'}</td>
            <td class="num fx-montant {signe(f) >= 0 ? 'pos' : 'neg'}">{fmtSigned(signe(f))}</td>
            <td class="fx-contexte">{[f.owner, f.envelope, f.establishment, f.type].filter(Boolean).join(' · ')}{#if !f.establishment}{' '}<span
              class="badge badge-blk">à préciser</span>{/if}</td>
            <td class="fx-notes">{#if !n.badges.length && !n.texte}—{:else}{#each n.badges as [lib, cls], i (i)}{i ? ' ' : ''}<span
              class="badge {cls} fx-marque">{lib}</span>{/each}{n.texte ? `${n.badges.length ? ' ' : ''}${n.texte}` : ''}{/if}</td>
            <td class="fx-actions">
              <button type="button" class="btn-icon edit fx-btn" data-id={f.id} data-action="edit-flux" onclick={() => onEditer(f.id)}>{@html EDITER}Éditer</button>
              <button type="button" class="btn-icon del fx-btn" data-id={f.id} data-action="del-flux" onclick={() => onSupprimer(f.id)}>{@html SUPPR}Supprimer</button>
            </td>
          </tr>
        {/each}
      {/if}
      {/key}
    </tbody>
    <tfoot id="flux-tfoot">
      {#key masque}
      {#if tous.length}
        <tr>
          <td colspan={avecCat ? 6 : 5} style={stylePied}>
            {#each totaux.parType as [t, v], i (t)}{i ? ' \u00a0·\u00a0 ' : ''}{t} : <strong class={v >= 0 ? 'pos' : 'neg'}>{pied(v)}</strong>{/each}
            &nbsp;·&nbsp; solde net des {tous.length} flux du filtre : versements et coupons, moins retraits et frais
          </td>
          <td class="num {totaux.total >= 0 ? 'pos' : 'neg'}" style="font-weight:700">{fmtSigned(totaux.total)}</td>
          <td colspan="2"></td>
        </tr>
        {#if totaux.parTitulaire.length > 1}
          <tr>
            <td colspan={avecCat ? 6 : 5} style={stylePied}>
              {#each totaux.parTitulaire as [o, v], i (o)}{i ? ' \u00a0·\u00a0 ' : ''}{o} : <strong class={v >= 0 ? 'pos' : 'neg'}>{pied(v)}</strong>{/each}
            </td>
            <td colspan="3"></td>
          </tr>
        {/if}
      {/if}
      {/key}
    </tfoot>
  </table>
  <div id="flux-plus" class="flux-plus" aria-live="polite" hidden={tous.length <= PAGE}>
    {#if tous.length > PAGE}
      <span>{visibles.length} flux affichés sur {tous.length}{reste > 0 ? ` ; les totaux portent sur les ${tous.length}` : ''}.</span>
      {#if reste > 0}<button type="button" class="btn btn-secondary btn-sm" id="flux-plus-btn" bind:this={bouton}
        onclick={suivants}>Afficher les {Math.min(PAGE, reste)} suivants</button>{/if}
    {/if}
  </div>
</div>
