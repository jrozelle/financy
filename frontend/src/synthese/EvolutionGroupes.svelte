<script lang="ts">
  /**
   * « Evolution par categorie » (ou par enveloppe) : une ligne par groupe —
   * nom, tendance, valeur, variation. Sept aires empilees ne se lisaient pas ;
   * ici chaque ligne a son echelle, et les chiffres se lisent sans survol.
   * Une ligne ouvre la composition du groupe au dernier arrete.
   *
   * Porte de static/modules/tabs/synthese.js (renderSyntheseHistory).
   */
  import { api } from '/static/modules/api.js';
  import { fmt, fmtDate, fmtPct, sparkline } from '/static/modules/utils.js';
  import { drilldownPositions } from '/static/modules/drilldown.js';
  import { ecran } from '../commun/ecran.svelte';

  interface Point { date: string; by_group?: Record<string, number> }
  interface Pos { owner: string; category: string; envelope: string | null }

  let { hote, owner = null, arretes = 0, masque = false }: {
    hote: HTMLElement; owner?: string | null; arretes?: number; masque?: boolean;
  } = $props();

  let groupe = $state<'category' | 'envelope'>('category');
  let historique = $state<Point[]>([]);
  let cleVue = '';
  let jeton = 0;

  // Moins de deux arretes : rien a suivre.
  $effect(() => {
    if (arretes < 2) { historique = []; return; }
    const url = `/api/historique?group_by=${groupe}${owner ? `&owner=${encodeURIComponent(owner)}` : ''}`;
    if (url === cleVue) return;
    cleVue = url;
    const j = ++jeton;
    api<Point[]>('GET', url).then(h => { if (j === jeton) historique = h; }).catch(() => {});
  });
  const visible = $derived(arretes >= 2 && historique.length >= 2);
  $effect(() => { hote.style.display = visible ? '' : 'none'; });

  const lignes = $derived.by(() => {
    const groupes = [...new Set(historique.flatMap(h => Object.keys(h.by_group || {})))];
    return groupes.map(g => {
      const serie = historique.map(h => h.by_group?.[g] || 0);
      const debut = serie[0], fin = serie[serie.length - 1];
      return { g, serie, debut, fin, delta: fin - debut };
    }).filter(l => l.serie.some(v => Math.abs(v) >= 1))
      .sort((a, b) => Math.abs(b.fin) - Math.abs(a.fin));
  });
  const totalFin = $derived(lignes.reduce((t, l) => t + Math.max(0, l.fin), 0));
  const dates = $derived(historique.map(h => h.date));
  const d0 = $derived(historique[0]?.date), d1 = $derived(historique[historique.length - 1]?.date);

  // Au telephone, les trois premiers groupes ; le reste sur demande.
  const VISIBLES = 3;
  let tout = $state(false);
  const affichees = $derived(ecran.telephone && !tout && lignes.length > VISIBLES + 1 ? lignes.slice(0, VISIBLES) : lignes);

  function ouvrir(g: string) {
    const o = owner, par = groupe, date = d1;
    api<Pos[]>('GET', `/api/positions?date=${date}`).then(positions => {
      let f = o ? positions.filter(p => p.owner === o) : positions;
      f = par === 'category' ? f.filter(p => p.category === g) : f.filter(p => (p.envelope || 'Autre') === g);
      drilldownPositions(f, `${g} — ${fmtDate(date)}`, `Évolution par ${par === 'category' ? 'catégorie' : 'enveloppe'}`, { showOwner: !o });
    });
  }
</script>

<div style="display:flex;align-items:center;gap:var(--esp-16);flex-wrap:wrap;margin-bottom:var(--esp-14)">
  <h2 style="margin:0">Évolution par</h2>
  <select id="synthese-history-group" class="filter-select" style="width:auto" aria-label="Regrouper l'évolution par"
          bind:value={groupe}>
    <option value="category">Catégorie</option>
    <option value="envelope">Enveloppe</option>
  </select>
</div>
<p class="card-sub" id="evolution-groupes-sous">{visible ? `Du ${fmtDate(d0)} au ${fmtDate(d1)} · une ligne ouvre sa composition` : ''}</p>
<div id="evolution-groupes" class="evg-liste">
  {#key masque}
  {#each affichees as l (l.g)}
    {@const pct = l.debut ? (l.delta / Math.abs(l.debut)) * 100 : null}
    {@const part = totalFin > 0 && l.fin > 0 ? fmtPct(l.fin / totalFin * 100, 0) : ''}
    <button type="button" class="evg-ligne" data-groupe={l.g} onclick={() => ouvrir(l.g)}>
      <span class="evg-nom">{l.g}{#if part}<span class="evg-part">{part}</span>{/if}</span>
      <span class="evg-spark">{@html sparkline(l.serie, { couleur: l.delta < 0 ? 'var(--danger)' : 'var(--primary)', dates })}</span>
      <span class="evg-valeur">{fmt(l.fin)}</span>
      <span class="evg-delta {Math.abs(l.delta) < 1 ? 'evg-stable' : l.delta > 0 ? 'pos' : 'neg'}">{#if Math.abs(l.delta) < 1}stable{:else}{l.delta > 0 ? '+' : '−'}{fmt(Math.abs(l.delta))}{#if pct != null && isFinite(pct)}<small>{fmtPct(pct, 1, true)}</small>{/if}{/if}</span>
    </button>
  {/each}
  {/key}
</div>
{#if ecran.telephone && lignes.length > VISIBLES + 1}
  <button type="button" class="btn-link mv-plus" aria-expanded={tout} aria-controls="evolution-groupes"
          onclick={() => tout = !tout}>{tout ? 'Réduire' : `Voir les ${lignes.length - VISIBLES} autres`}</button>
{/if}
