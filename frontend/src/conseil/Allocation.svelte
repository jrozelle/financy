<script lang="ts">
  /**
   * Allocation cible du profil face a l'allocation actuelle, sur le seul
   * patrimoine financier ; ce qui est hors calcul est decompte dessous.
   *
   * Porte de static/modules/tabs/advisor.js (_loadAllocation,
   * _renderAllocationChart), balisage a l'identique.
   */
  import { onDestroy } from 'svelte';
  import { api } from '/static/modules/api.js';
  import { fmt, fmtPct, getColors, gridColor } from '/static/modules/utils.js';
  import type { Allocation } from './types';

  let { proprietaire = null, avecProfil = false, version = 0, masque = false }: {
    proprietaire?: string | null; avecProfil?: boolean; version?: number; masque?: boolean;
  } = $props();

  let donnees = $state<Allocation | null>(null);
  let jeton = 0;
  $effect(() => {
    void version;
    const j = ++jeton;
    if (!avecProfil || !proprietaire) { donnees = null; return; }
    api<Allocation>('GET', `/api/advisor/profiles/${encodeURIComponent(proprietaire)}/allocation`, null, { silent: true })
      .then(d => { if (j === jeton) donnees = d; }).catch(() => {});
  });
  const avecEcarts = $derived(!!donnees && !!donnees.gap.length && !!donnees.total_eur);

  let toile = $state<HTMLCanvasElement>();
  let graphe: { destroy(): void } | null = null;
  $effect(() => {
    void masque;
    graphe?.destroy(); graphe = null;
    if (!toile || !donnees || !avecEcarts) return;
    const couleurs = getColors();
    graphe = new Chart(toile, {
      type: 'bar',
      data: {
        labels: donnees.gap.map(g => g.category),
        datasets: [
          { label: 'Cible', data: donnees.gap.map(g => +(g.target_pct * 100).toFixed(1)), backgroundColor: couleurs[0] + 'cc', borderColor: couleurs[0], borderWidth: 1 },
          { label: 'Actuelle', data: donnees.gap.map(g => +(g.actual_pct * 100).toFixed(1)), backgroundColor: couleurs[2] + 'cc', borderColor: couleurs[2], borderWidth: 1 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: { label: (ctx: { dataset: { label: string }; parsed: { y: number } }) => `${ctx.dataset.label} : ${fmtPct(ctx.parsed.y)}` } },
        },
        scales: {
          y: { ticks: { callback: (v: number) => fmtPct(v, 0), font: { size: 11 } }, grid: { color: gridColor() }, beginAtZero: true },
          x: { ticks: { font: { size: 11 } }, grid: { display: false } },
        },
      },
    });
  });
  onDestroy(() => graphe?.destroy());
</script>

<div class="card" id="adv-allocation">
  <h2>Allocation cible vs actuelle</h2>
  <div id="advisor-adjustments" class="advisor-adjustments">
    {#if !avecProfil}
      <div class="empty-state" style="padding:1rem 0">
        <p class="text-muted" style="font-size:12.5px;margin-bottom:.75rem">
          Enregistrez un profil (horizon + tolérance au risque) pour calculer
          l'allocation cible et générer des propositions d'arbitrage.
        </p>
        <a href="#adv-profile" class="btn btn-secondary btn-sm advisor-sidebar-link" data-anchor="adv-profile">
          Remplir le profil &uarr;
        </a>
      </div>
    {:else if donnees}
      {#if donnees.adjustments?.length}
        {#each donnees.adjustments as a, i (i)}<div class="advisor-adjustment-item">{a}</div>{/each}
      {:else}
        <div class="text-muted" style="font-size:12.5px">Profil standard : aucun ajustement contextuel appliqué.</div>
      {/if}
    {/if}
  </div>
  <div id="advisor-allocation-wrap">
    <!-- Sans donnees, pas de cadre de graphe vide de 280 px. -->
    <div id="advisor-allocation-graphe" style="position:relative;height:280px;margin-bottom:1rem" style:display={avecProfil ? null : 'none'}>
      <canvas id="advisor-allocation-chart" bind:this={toile}></canvas>
    </div>
    <!-- svelte-ignore a11y_no_noninteractive_tabindex : zone defilante, atteignable au clavier -->
    <div class="table-scroll" tabindex="0" role="region" aria-label="Tableau défilant">
      <table class="data-table">
        <thead>
          <tr>
            <th>Classe d'actif</th>
            <th class="num">Cible</th>
            <th class="num">Actuelle</th>
            <th class="num">Écart %</th>
            <th class="num">Écart €</th>
            <th class="num">Dont bloqué</th>
          </tr>
        </thead>
        <tbody id="advisor-gap-tbody">
          {#key masque}
          {#if avecProfil && donnees && !avecEcarts}
            <tr><td colspan="6" style="text-align:center;padding:1rem;color:var(--text-muted);font-style:italic">Pas de positions sur ce propriétaire. Saisissez des positions pour comparer.</td></tr>
          {:else if avecProfil && donnees}
            {#each donnees.gap as g (g.category)}
              {@const cls = g.delta_eur > 0 ? 'pos' : g.delta_eur < 0 ? 'neg' : ''}
              <tr>
                <td><strong>{g.category}</strong></td>
                <td class="num">{fmtPct(g.target_pct * 100)}</td>
                <td class="num">{fmtPct(g.actual_pct * 100)}</td>
                <td class="num {cls}">{fmtPct(g.delta_pct * 100, 1, true)}</td>
                <td class="num {cls}">{g.delta_eur > 0 ? '+' : ''}{fmt(g.delta_eur)}</td>
                <td class="num">{g.bloque_eur ? fmt(g.bloque_eur) : '—'}</td>
              </tr>
            {/each}
          {/if}
          {/key}
        </tbody>
      </table>
    </div>
    <!-- Ce qui est hors du calcul ne disparait pas : il est decompte ici. -->
    <!-- Le montant se raccorde a celui de la synthese : meme patrimoine
         financier (services/categories.py), moins la tresorerie des societes. -->
    <p class="advisor-perimetre" id="advisor-perimetre">{#key masque}{#if avecProfil && donnees && avecEcarts}{@const treso = (donnees.exclus || []).find(e => e.category === 'Trésorerie de société')?.montant || 0}{@const exclus = (donnees.exclus || []).filter(e => e.category !== 'Trésorerie de société').map(e => `${e.category} ${fmt(e.montant)}`).join(', ')}Calcul sur le patrimoine financier arbitrable : {fmt(donnees.total_eur)}{donnees.bloque_eur
      ? `, dont ${fmt(donnees.bloque_eur)} bloqués (contrat nanti, PER, produit structuré) : ils comptent dans l'exposition, mais les propositions n'y touchent pas` : ''}.{treso && donnees.financier_eur
      ? ` C'est le patrimoine financier de la synthèse (${fmt(donnees.financier_eur)}), moins ${fmt(treso)} de trésorerie de société.` : ''}{exclus
      ? ` Hors du patrimoine financier, donc du calcul : ${exclus}.` : ''}{/if}{/key}</p>
  </div>
</div>
