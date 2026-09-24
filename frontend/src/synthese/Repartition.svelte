<script lang="ts">
  /**
   * Repartition : une carte, quatre angles, et le levier rendu visible.
   *
   * Deux references coexistent, et c'est dit a l'ecran :
   * - la LONGUEUR des barres se lit sur le brut, leurs cumuls font 100 % ;
   * - la colonne « % net » se lit sur le net.
   * L'ecart entre les deux EST la dette.
   *
   * Porte de static/modules/tabs/repartition.js, balisage a l'identique.
   */
  import { fmt, fmtPct } from '/static/modules/utils.js';
  import { lirePref, ecrirePref } from '/static/modules/preferences.js';

  type Totaux = Record<string, { gross?: number; net?: number; debt?: number;
    by_owner?: Record<string, unknown>; by_owner_gross?: Record<string, number> }>;
  type Synthese = Record<string, unknown>;

  let { synthese, owner }: { synthese: Synthese | null; owner: string | null } = $props();

  const ANGLES = [
    { cle: 'macro', libelle: 'Poche', source: 'totals_by_macro' },
    { cle: 'category', libelle: 'Catégorie', source: 'totals_by_category' },
    { cle: 'envelope', libelle: 'Enveloppe', source: 'totals_by_envelope' },
    { cle: 'owner', libelle: 'Personne', source: 'totals_by_owner' },
  ] as const;
  type Angle = typeof ANGLES[number]['cle'];

  let angle = $state<Angle>((lirePref('financy_repartition') as Angle) || 'macro');
  const definition = $derived(ANGLES.find(a => a.cle === angle) || ANGLES[0]);
  const famille = $derived(!owner || owner === 'Famille');

  /** Part d'un titulaire dans une ligne : chaque angle porte son detail par
   *  personne sous une forme differente — un nombre pour les categories, un
   *  objet pour les poches et les enveloppes, rien pour l'angle « Personne ».
   *  Seul endroit qui connaisse ces formes ; ailleurs on lit {gross, net, debt}. */
  function partDe(cle: Angle, nom: string, t: Totaux[string]) {
    const total = { gross: t.gross || 0, net: t.net || 0, debt: t.debt || 0 };
    if (famille) return total;
    if (cle === 'owner') return nom === owner ? total : { gross: 0, net: 0, debt: 0 };
    if (cle === 'category') {
      const gross = t.by_owner_gross?.[owner!] || 0;
      const net = (t.by_owner?.[owner!] as number) || 0;
      return { gross, net, debt: gross - net };
    }
    const o = t.by_owner?.[owner!] as { gross?: number; net?: number; debt?: number } | undefined;
    return o ? { gross: o.gross || 0, net: o.net || 0, debt: o.debt || 0 } : { gross: 0, net: 0, debt: 0 };
  }

  const lignes = $derived(Object.entries((synthese?.[definition.source] || {}) as Totaux)
    .map(([nom, t]) => ({ nom, ...partDe(definition.cle, nom, t) }))
    .filter(l => l.gross || l.net)
    .sort((a, b) => b.gross - a.gross));
  const brut = $derived(lignes.reduce((s, l) => s + l.gross, 0));
  const net = $derived(lignes.reduce((s, l) => s + l.net, 0));
  const dette = $derived(lignes.reduce((s, l) => s + l.debt, 0));
  const pct = (v: number, total: number) => total ? (v / total) * 100 : 0;
  const couleur = (i: number) => `var(--chart-${(i % 11) + 1})`;

  function choisir(cle: Angle) {
    angle = cle;
    ecrirePref('financy_repartition', cle);
  }
</script>

<div class="card-head">
  <div>
    <h2>Répartition</h2>
    <p class="card-hint">Longueurs cumulées = 100 % du brut ·
      plein : ce qui vous revient · hachuré : financé par emprunt</p>
  </div>
  <div class="seg" role="group" aria-label="Angle de répartition">
    {#each ANGLES as a (a.cle)}
      <button type="button" class="seg-btn" data-angle={a.cle} aria-pressed={a.cle === angle}
              onclick={() => choisir(a.cle)}>{a.libelle}</button>
    {/each}
  </div>
</div>
{#if lignes.length}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex : zone qui defile, atteignable au clavier -->
  <div class="rep-wrap" tabindex="0" role="region" aria-label="Répartition">
    <table class="rep">
      <thead>
        <tr>
          <th scope="col">{definition.libelle}</th>
          <th scope="col">Brut</th>
          <th scope="col">Net</th>
          <th scope="col">% brut</th>
          <th scope="col">% net</th>
          <th scope="col">Levier</th>
        </tr>
      </thead>
      <tbody>
        {#each lignes as l, i (l.nom)}
          <!-- Les deux segments se mesurent sur le BRUT TOTAL : les longueurs
               de toutes les lignes cumulent exactement 100 %. -->
          {@const levier = l.gross ? (l.debt / l.gross) * 100 : 0}
          <tr>
            <td>
              <span class="rep-n"><i class="dot" style:background={couleur(i)}></i>{l.nom}</span>
              <span class="rep-bar">
                <span class="fill" style:width="{pct(l.net, brut).toFixed(2)}%" style:background={couleur(i)}></span>
                {#if l.debt}<span class="fill lev" style:width="{pct(l.debt, brut).toFixed(2)}%" style:background={couleur(i)}></span>{/if}
              </span>
            </td>
            <td class="num">{fmt(l.gross)}</td>
            <td class="num">{fmt(l.net)}</td>
            <td class="num">{fmtPct(pct(l.gross, brut))}</td>
            <td class="num">{fmtPct(pct(l.net, net))}</td>
            <td>{#if levier > 0.05}<span class="tag tag-lev">{fmtPct(levier, 0)}</span>{:else}<span class="rep-none">—</span>{/if}</td>
          </tr>
        {/each}
      </tbody>
      <tfoot>
        <tr>
          <td>Total</td>
          <td class="num">{fmt(brut)}</td>
          <td class="num">{fmt(net)}</td>
          <td class="num">100 %</td>
          <td class="num">100 %</td>
          <td>{#if dette > 0}<span class="tag tag-lev-tot">{fmtPct((dette / brut) * 100)}</span>{:else}<span class="rep-none">—</span>{/if}</td>
        </tr>
      </tfoot>
    </table>
  </div>
{:else}
  <p class="rep-vide">Aucune position à cet arrêté.</p>
{/if}
