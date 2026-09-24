<script lang="ts">
  /**
   * Onglet Actifs : les lignes de titres consolidees (toutes enveloppes), leur
   * repartition par classe et par enveloppe, la fraicheur de chaque cours.
   * Un clic sur une part d'anneau filtre le tableau ; un second l'efface.
   * Tri et filtre sont memorises en base (financy_filters_actifs).
   *
   * Le rapprochement avec le journal des operations (#reconcile-panel) reste
   * dans static/modules/tabs/reconcile.js, qui remplit l'element tel quel.
   *
   * Porte de static/modules/tabs/actifs.js, balisage a l'identique.
   */
  import { onDestroy } from 'svelte';
  import { fmt, fmtDate, fmtPct, fmtQty, sortArr, getColors, chartBorderColor } from '/static/modules/utils.js';
  import { lirePref, ecrirePref } from '/static/modules/preferences.js';
  import { openIsinPopover } from '/static/modules/isin-popover.js';
  import EnTeteTri from '../commun/EnTeteTri.svelte';
  import type { Consolide, LigneActif, Repartition } from './types';

  let { donnees = null, masque = false }: { donnees?: Consolide | null; masque?: boolean } = $props();

  // ── Tri et filtre, memorises ───────────────────────────────────────────
  const CLE = 'financy_filters_actifs';
  const lu = (() => { try { return JSON.parse(lirePref(CLE) || '') || {}; } catch { return {}; } })();
  let tri = $state({ cle: (lu.sortCol || 'market_value') as string | null,
                     sens: typeof lu.sortDesc === 'boolean' ? (lu.sortDesc ? -1 : 1) : -1 });
  let filtre = $state<{ type: string | null; value: string | null }>(
    lu.filter?.type && lu.filter?.value ? { type: lu.filter.type, value: lu.filter.value } : { type: null, value: null });
  const memoriser = () => ecrirePref(CLE, JSON.stringify({ sortCol: tri.cle, sortDesc: tri.sens === -1, filter: filtre }));
  const basculer = (cle: string) => { tri = tri.cle === cle ? { cle, sens: -tri.sens } : { cle, sens: 1 }; memoriser(); };
  function filtrer(type: string, valeur: string | null) {
    filtre = valeur == null || (filtre.type === type && filtre.value === valeur) ? { type: null, value: null } : { type, value: valeur };
    memoriser();
  }

  // ── Colonnes : choisies dans Reglages (static/modules/column-picker.js),
  // qui previent par l'evenement « columns:changed » sur l'en-tete — avant
  // d'enregistrer le choix : on le relit au tour suivant.
  const COLONNES = [
    { cle: 'name', lib: 'Nom' }, { cle: 'asset_class', lib: 'Classe' }, { cle: 'establishments', lib: 'Établissement' },
    { cle: 'quantity', lib: 'Qté', num: true }, { cle: 'avg_cost', lib: 'PRU', num: true },
    { cle: 'last_price', lib: 'Cours', num: true }, { cle: 'market_value', lib: 'Valeur', num: true },
    { cle: 'pnl', lib: '+/-', num: true }, { cle: 'weight_pct', lib: 'Poids', num: true },
  ];
  const lireColonnes = (): Record<string, boolean> => { try { return JSON.parse(lirePref('financy_columns_actifs') || '{}'); } catch { return {}; } };
  let colonnes = $state(lireColonnes());
  const cachee = (cle: string) => colonnes[cle] === false;
  let entete = $state<HTMLElement>();
  $effect(() => {
    const el = entete;
    if (!el) return;
    const relire = () => queueMicrotask(() => { colonnes = lireColonnes(); });
    el.addEventListener('columns:changed', relire);
    return () => el.removeEventListener('columns:changed', relire);
  });

  const t = $derived(donnees?.totals);
  const lignes = $derived.by(() => {
    let l = donnees?.lines || [];
    if (filtre.type === 'asset_class') l = l.filter(x => x.asset_class === filtre.value);
    else if (filtre.type === 'envelope') l = l.filter(x => (x.envelopes || []).includes(filtre.value!));
    return sortArr([...l], tri.cle, tri.sens);
  });

  /** Quantite avec autant de decimales qu'elle en porte (huit au plus) : un
   *  bitcoin detenu a 0,0625 s'affichait « 0 ». Moins de decimales permises a
   *  mesure que la quantite grandit : le bruit du calcul ne doit pas s'ecrire. */
  function quantite(q: number | null) {
    if (q == null) return '—';
    const a = Math.abs(q);
    const max = a >= 1000 ? 2 : a >= 1 ? 4 : 8;
    let dec = 0;
    while (dec < max && Math.abs(Math.round(q * 10 ** dec) / 10 ** dec - q) > 1e-9 * Math.max(1, a)) dec++;
    return fmtQty(q, dec);
  }
  /** Dernier cours, dans la devise du titre : hors euro, le code de la
   *  devise suit le nombre, masque comme lui. */
  function cours(l: LigneActif) {
    if (l.last_price == null) return '—';
    const devise = (l.currency || 'EUR').toUpperCase();
    return devise === 'EUR' ? fmt(l.last_price, 2) : `${fmtQty(l.last_price, 2)} ${devise}`;
  }
  /** Un pseudo-ISIN (FONDS_EUROS_..., CUSTOM_...) est un code interne : il se
   *  lit « fonds euros » ou « non coté », le code reste dans le nom accessible. */
  const pseudo = (isin: string) => {
    const u = (isin || '').toUpperCase();
    return u.startsWith('FONDS_EUROS_') ? 'fonds euros' : u.startsWith('CUSTOM_') ? 'non coté' : null;
  };
  function fraicheur(l: LigneActif): { cls: string; lib: string; date?: string } {
    if (!l.is_priceable) return { cls: 'h-badge-muted', lib: 'non coté' };
    if (!l.ticker && !l.last_price_date) return { cls: 'h-badge-expired', lib: 'sans ticker' };
    if (!l.last_price_date) return { cls: 'h-badge-expired', lib: 'jamais rafraîchi' };
    const h = (Date.now() - new Date(l.last_price_date + 'T23:59:59').getTime()) / 3600000;
    if (isNaN(h)) return { cls: 'h-badge-expired', lib: 'inconnu' };
    const [cls, lib] = h < 1 ? ['h-badge-fresh', '<1h'] : h < 12 ? ['h-badge-fresh', `${Math.floor(h)}h`]
      : h < 24 ? ['h-badge-fresh', '<1j'] : h < 48 ? ['h-badge-stale', '1j']
      : h < 168 ? ['h-badge-stale', `${Math.floor(h / 24)}j`] : ['h-badge-expired', `${Math.floor(h / 24)}j`];
    // La date du cours s'affiche sous l'age : c'est elle qu'on vient chercher.
    return { cls, lib, date: l.last_price_date };
  }

  // ── Anneaux ─────────────────────────────────────────────────────────────
  let toileClasse = $state<HTMLCanvasElement>();
  let toileEnveloppe = $state<HTMLCanvasElement>();
  let graphes: { destroy(): void }[] = [];
  function anneau(toile: HTMLCanvasElement, rep: Repartition[], type: string, couleurs: string[]) {
    const libelles = rep.map(b => b.label);
    return new Chart(toile, {
      type: 'doughnut',
      data: { labels: libelles, datasets: [{ data: rep.map(b => b.market_value),
        backgroundColor: rep.map((_, i) => couleurs[i % couleurs.length] + 'cc'), borderColor: chartBorderColor(), borderWidth: 1.5 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        // Clic hors d'une part : le filtre s'efface.
        onClick: (_: unknown, el: { index: number }[]) => filtrer(type, el.length ? libelles[el[0].index] : null),
        plugins: {
          legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } },
                    onClick: (_: unknown, item: { index: number }) => filtrer(type, libelles[item.index]) },
          tooltip: { callbacks: { label: (ctx: { label: string; parsed: number; dataIndex: number }) =>
            ` ${ctx.label} : ${fmt(ctx.parsed)} (${fmtPct(rep[ctx.dataIndex]?.weight_pct)})` } },
        },
      },
    });
  }
  $effect(() => {
    void masque;
    const b = donnees?.breakdowns;
    graphes.forEach(g => g.destroy());
    graphes = [];
    if (!b) return;
    if (toileClasse && b.asset_class?.length) graphes.push(anneau(toileClasse, b.asset_class, 'asset_class', getColors()));
    if (toileEnveloppe && b.envelope?.length) graphes.push(anneau(toileEnveloppe, b.envelope, 'envelope', getColors().slice().reverse()));
  });
  onDestroy(() => graphes.forEach(g => g.destroy()));
</script>

<div class="page-header">
  <h1>Actifs</h1>
</div>

{#key masque}
<div class="kpi-grid" style="grid-template-columns:repeat(4,1fr);margin-bottom:1rem">
  <div class="kpi-card"><div class="kpi-label">Valorisation totale</div><div class="kpi-value" id="actifs-kpi-value">{t ? fmt(t.market_value || 0) : '—'}</div></div>
  <div class="kpi-card"><div class="kpi-label">Prix de revient</div><div class="kpi-value" id="actifs-kpi-cost">{t?.cost_basis ? fmt(t.cost_basis) : '—'}</div></div>
  <div class="kpi-card"><div class="kpi-label">+/- latent</div><div class="kpi-value" id="actifs-kpi-pnl"
    style:color={t?.pnl != null ? (t.pnl >= 0 ? 'var(--success)' : 'var(--danger)') : null}>{t?.pnl != null
    ? `${t.pnl >= 0 ? '+' : ''}${fmt(t.pnl)}${t.pnl_pct != null ? ` (${fmtPct(t.pnl_pct, 2)})` : ''}` : '—'}</div></div>
  <div class="kpi-card"><div class="kpi-label">Lignes</div><div class="kpi-value" id="actifs-kpi-count">{t ? t.lines_count || 0 : '—'}</div></div>
</div>
{/key}

<!-- Rapprochement des quantites avec le journal des operations. Vide tant
     que le controle n'a rien a dire ; rempli par reconcile.js. -->
<div id="reconcile-panel"></div>

<div class="charts-row" style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
  <div class="card">
    <h2>Par classe d'actif</h2>
    <div style="position:relative;height:240px"><canvas id="actifs-chart-class" bind:this={toileClasse}></canvas></div>
  </div>
  <div class="card">
    <h2>Par enveloppe</h2>
    <div style="position:relative;height:240px"><canvas id="actifs-chart-envelope" bind:this={toileEnveloppe}></canvas></div>
  </div>
</div>

<div class="card card-table">
  <table class="data-table">
    <thead id="actifs-thead" bind:this={entete}>
      <tr>
        {#each COLONNES as c (c.cle)}
          <EnTeteTri cle={c.cle} num={c.num} {tri} surTri={basculer} cachee={cachee(c.cle)}>{c.lib}</EnTeteTri>
        {/each}
      </tr>
    </thead>
    <tbody id="actifs-tbody">
      {#key masque}
      {#each lignes as l, i (l.isin + '|' + i)}
        {@const f = fraicheur(l)}
        {@const envs = (l.envelopes || []).join(', ')}
        <tr>
          <td class="act-nom" style:display={cachee('name') ? 'none' : null}><span class="act-nom-lib">{l.name || '—'}</span>
            <span class="act-sous">{@render isin(l.isin)}</span></td>
          <td style:display={cachee('asset_class') ? 'none' : null}>{l.asset_class || '—'}</td>
          <td class="act-etab" style:display={cachee('establishments') ? 'none' : null}>{(l.establishments || []).join(', ') || '—'}{#if envs}<span
            class="act-sous">{envs}</span>{/if}</td>
          <td class="num" style:display={cachee('quantity') ? 'none' : null}>{quantite(l.quantity)}</td>
          <td class="num" style:display={cachee('avg_cost') ? 'none' : null}>{l.avg_cost != null ? fmt(l.avg_cost, 2) : '—'}</td>
          <td class="num act-cours" style:display={cachee('last_price') ? 'none' : null}>{cours(l)}<span class="act-fraicheur">{@render badge(f)}</span></td>
          <td class="num" style:display={cachee('market_value') ? 'none' : null}>{fmt(l.market_value)}</td>
          <td class="num" style:display={cachee('pnl') ? 'none' : null}>{@render pnl(l)}</td>
          <td class="num" style:display={cachee('weight_pct') ? 'none' : null}>{fmtPct(l.weight_pct)}</td>
        </tr>
      {/each}
      {/key}
    </tbody>
  </table>
  <div id="actifs-cards" class="actifs-card-list">
    {#key masque}
    {#each lignes as l, i (l.isin + '|' + i)}
      <article class="actif-card">
        <div class="actif-card-main">
          {@render isin(l.isin)}
          <strong>{l.name || '—'}</strong>
          <span>{(l.establishments || []).join(', ') || '—'} · {(l.envelopes || []).join(', ') || '—'} · {l.asset_class || '—'}</span>
        </div>
        <dl class="actif-card-metrics">
          <div><dt>Valeur</dt><dd>{fmt(l.market_value)}</dd></div>
          <div><dt>PRU</dt><dd>{l.avg_cost != null ? fmt(l.avg_cost, 2) : '—'}</dd></div>
          <div><dt>Qté</dt><dd>{quantite(l.quantity)}</dd></div>
          <div><dt>+/-</dt><dd>{@render pnl(l)}</dd></div>
          <div><dt>Poids</dt><dd>{fmtPct(l.weight_pct)}</dd></div>
          <div><dt>Cours</dt><dd>{cours(l)}</dd></div>
        </dl>
        <div class="actif-card-freshness">{@render badge(fraicheur(l))}</div>
      </article>
    {/each}
    {/key}
  </div>
  <div id="actifs-empty" class="empty-state" style="padding:2rem 1rem;text-align:center" style:display={donnees && !donnees.lines?.length ? null : 'none'}>
    <div style="margin-bottom:.4rem;opacity:.5" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.8"
           stroke-linecap="round" stroke-linejoin="round" focusable="false">
        <path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 6-6"/>
      </svg>
    </div>
    <h3 style="font-size:14px;margin-bottom:.4rem">Aucune ligne d'actif</h3>
    <p class="text-muted" style="font-size:12.5px;margin-bottom:1rem">
      Pour voir vos ETF, actions et fonds euros ici, ajoutez des lignes
      dans une position depuis l'onglet Positions.
    </p>
    <button class="btn btn-primary btn-sm" data-tab-switch="positions">Aller aux positions</button>
  </div>
</div>

{#snippet isin(code: string)}
  {@const p = pseudo(code)}
  <button type="button" class="h-isin-btn" class:h-isin-pseudo={p} data-action="open-popover" data-isin={code}
          aria-label={p ? code : undefined} onclick={() => openIsinPopover(code)}>{p || code}</button>
{/snippet}

{#snippet badge(f: { cls: string; lib: string; date?: string })}
  <span class="h-badge {f.cls}">{f.lib}</span>{#if f.date}<span class="h-badge-date">cours du {fmtDate(f.date)}</span>{/if}
{/snippet}

{#snippet pnl(l: LigneActif)}
  <!-- Une plus-value nulle au centime pres n'est pas une performance mesuree
       (fonds euros sans cours, releve sans prix de revient) : on le dit. -->
  {#if l.pnl == null}<span class="pv-na">—</span>{:else if l.pnl === 0}<span class="pv-na">PRU = valeur</span>{:else}<span
    class={l.pnl >= 0 ? 'pv-hausse' : 'pv-baisse'}>{l.pnl >= 0 ? '+' : '−'}{fmt(Math.abs(l.pnl))}</span>{#if l.pnl_pct != null}<span
    class="pv-pct">{fmtPct(l.pnl_pct, 1, true)}</span>{/if}{/if}
{/snippet}
