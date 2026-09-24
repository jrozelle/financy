<script lang="ts">
  /**
   * Onglet Outils : la frise des arretes, flux et notes avec la courbe du
   * patrimoine net, une simulation d'epargne, l'arrete automatique et le
   * rafraichissement des cours.
   *
   * Les deux dernieres actions restent dans static/modules/tabs/tools.js
   * (le menu d'Actifs rafraichit aussi les cours) : leurs zones de resultat
   * sont des elements fixes que ce module remplit.
   *
   * Porte de static/modules/tabs/tools.js, balisage a l'identique.
   */
  import { onDestroy } from 'svelte';
  import { api } from '/static/modules/api.js';
  import { fmt, fmtDate, getColors, gridColor, parseLocaleNumber, fmtAxis, tsJour, echelleTemps, titreDate } from '/static/modules/utils.js';
  import { toast } from '/static/modules/dialogs.js';
  import { drilldownPositions } from '/static/modules/drilldown.js';
  import { triggerAutoSnapshot, triggerPricesRefresh } from '/static/modules/tabs/tools.js';

  let { masque = false, visite = 0 }: { masque?: boolean; visite?: number } = $props();

  // ── Frise ───────────────────────────────────────────────────────────────
  interface Evenement { date: string; type: string; label: string; value: number | null }
  let evenements = $state<Evenement[] | null>(null);
  $effect(() => {
    void visite;
    api<Evenement[]>('GET', '/api/timeline').then(e => { evenements = e; }).catch(() => {});
  });
  const arretes = $derived((evenements || []).filter(e => e.type === 'snapshot' && e.value != null)
    .sort((a, b) => a.date.localeCompare(b.date)));
  // La nature de l'evenement s'ecrit en toutes lettres : la couleur du point
  // seule ne se lit ni sans couleur ni au lecteur d'ecran.
  const nature = (t: string) => t === 'snapshot' ? 'Arrêté' : t === 'note' ? 'Note' : 'Flux';

  let toileFrise = $state<HTMLCanvasElement>();
  let grapheFrise: { destroy(): void } | null = null;
  $effect(() => {
    void masque;
    grapheFrise?.destroy(); grapheFrise = null;
    const snaps = arretes;
    if (!toileFrise || snaps.length < 2) return;
    const couleurs = getColors();
    // Echelle de temps : des arretes irreguliers restent a leur vraie date.
    grapheFrise = new Chart(toileFrise, {
      type: 'line',
      data: { datasets: [{ label: 'Patrimoine net', data: snaps.map(s => ({ x: tsJour(s.date), y: s.value })),
        borderColor: couleurs[0], backgroundColor: couleurs[0] + '18', fill: true, cubicInterpolationMode: 'monotone',
        pointRadius: 4, borderWidth: 2 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        onClick: (_: unknown, el: { index: number }[]) => {
          const s = el.length ? snaps[el[0].index] : null;
          if (!s) return;
          api<unknown[]>('GET', `/api/positions?date=${s.date}`).then(positions => {
            drilldownPositions(positions, `Famille — ${fmtDate(s.date)}`, 'Composition du patrimoine', { showOwner: true });
          });
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { title: titreDate, label: (ctx: { parsed: { y: number } }) => ` ${fmt(ctx.parsed.y)}`,
                                  afterBody: () => 'Cliquer pour voir la composition' } },
        },
        scales: { y: { ticks: { callback: fmtAxis, font: { size: 11 } }, grid: { color: gridColor() } },
                  x: echelleTemps(snaps.map(s => s.date)) },
      },
    });
  });

  // ── Simulation ──────────────────────────────────────────────────────────
  let f = $state({ initial: '10000', mensuel: '500', taux: '5', annees: '10' });
  interface Resultat { final_balance: number; total_invested: number; gains: number;
                       points: { month: number; balance: number; invested: number }[] }
  let resultat = $state<Resultat | null>(null);
  async function simuler(e: SubmitEvent) {
    e.preventDefault();
    const data = {
      initial: parseLocaleNumber(f.initial, 0), monthly: parseLocaleNumber(f.mensuel, 0),
      annual_rate: parseLocaleNumber(f.taux, 5), years: parseInt(String(parseLocaleNumber(f.annees, 10)), 10),
    };
    try { resultat = await api<Resultat>('POST', '/api/simulate', data); }
    catch (err) { toast('Erreur simulation : ' + (err as Error).message, 'error'); }
  }
  /** « 3 ans », « 1 an 6 mois », « 9 mois » : un numero de mois de simulation. */
  function duree(mois: number) {
    const m = Math.round(mois), a = Math.floor(m / 12), r = m % 12;
    return [a ? `${a} an${a > 1 ? 's' : ''}` : '', r ? `${r} mois` : ''].filter(Boolean).join(' ') || '0 mois';
  }
  let toileSimul = $state<HTMLCanvasElement>();
  let grapheSimul: { destroy(): void } | null = null;
  $effect(() => {
    void masque;
    grapheSimul?.destroy(); grapheSimul = null;
    if (!toileSimul || !resultat) return;
    // Une quarantaine de points au plus, sur un axe lineaire en mois : le
    // dernier point, garde meme hors du pas, tombe a sa vraie place.
    const pts = resultat.points;
    const pas = Math.max(1, Math.floor(pts.length / 40));
    const garde = pts.filter((_, i) => i === 0 || i === pts.length - 1 || i % pas === 0);
    const couleurs = getColors();
    const moisMax = garde.length ? garde[garde.length - 1].month : 0;
    grapheSimul = new Chart(toileSimul, {
      type: 'line',
      data: { datasets: [
        { label: 'Capital', data: garde.map(p => ({ x: p.month, y: p.balance })), borderColor: couleurs[0],
          backgroundColor: couleurs[0] + '18', fill: true, cubicInterpolationMode: 'monotone', pointRadius: 2, borderWidth: 2 },
        { label: 'Investi', data: garde.map(p => ({ x: p.month, y: p.invested })), borderColor: couleurs[2], borderDash: [5, 3],
          cubicInterpolationMode: 'monotone', pointRadius: 0, borderWidth: 1.5, fill: false },
      ] },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },   // series alignees sur les memes mois
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: { title: (items: { parsed: { x: number } }[]) => items.length ? duree(items[0].parsed.x) : '',
                                  label: (ctx: { dataset: { label: string }; parsed: { y: number } }) => ` ${ctx.dataset.label} : ${fmt(ctx.parsed.y)}` } },
        },
        scales: {
          y: { ticks: { callback: fmtAxis, font: { size: 11 } }, grid: { color: gridColor() } },
          x: { type: 'linear', min: 0, max: moisMax,
               ticks: { font: { size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 8,
                        // Graduation a l'annee quand l'horizon le permet.
                        stepSize: moisMax > 24 ? 12 * Math.max(1, Math.round(moisMax / 12 / 8)) : 3,
                        callback: (v: number) => duree(v) },
               grid: { display: false } },
        },
      },
    });
  });
  onDestroy(() => { grapheFrise?.destroy(); grapheSimul?.destroy(); });
</script>

<div class="page-header"><h1>Outils</h1></div>

<div class="card">
  <h2>Timeline patrimoniale</h2>
  <p class="text-muted" style="font-size:12.5px;margin-bottom:.875rem">
    Frise chronologique des arrêtés, flux et événements.
  </p>
  <div id="timeline-body">
    {#if evenements && !evenements.length}
      <p class="text-muted" style="padding:1rem">Aucun événement.</p>
    {:else if evenements}
      {#if arretes.length >= 2}<div style="position:relative;height:220px;margin-bottom:1.25rem"><canvas id="timeline-chart" bind:this={toileFrise}></canvas></div>{/if}
      <div class="timeline-wrapper"><div class="timeline">
        {#key masque}
        {#each evenements as ev, i (i)}
          <div class="timeline-event timeline-{ev.type}">
            <div class="timeline-dot" aria-hidden="true"></div>
            <div class="timeline-info">
              <div class="timeline-date">{fmtDate(ev.date)} · {nature(ev.type)}</div>
              <div class="timeline-label">{ev.label}{ev.value != null ? ` — ${fmt(ev.value)}` : ''}</div>
            </div>
          </div>
        {/each}
        {/key}
      </div></div>
    {/if}
  </div>
</div>

<div class="card">
  <h2>Projection / Simulation</h2>
  <p class="text-muted" style="font-size:12.5px;margin-bottom:.875rem">
    Simulez l'évolution d'un capital avec un versement mensuel régulier.
  </p>
  <form id="simulation-form" onsubmit={simuler}>
    <div class="form-grid" style="margin-bottom:1rem">
      <div class="form-group">
        <label for="sim-initial">Capital initial (€)</label>
        <input type="text" inputmode="decimal" id="sim-initial" min="0" step="100" bind:value={f.initial}>
      </div>
      <div class="form-group">
        <label for="sim-monthly">Versement mensuel (€)</label>
        <input type="text" inputmode="decimal" id="sim-monthly" min="0" step="50" bind:value={f.mensuel}>
      </div>
      <div class="form-group">
        <label for="sim-rate">Rendement annuel (%)</label>
        <input type="text" inputmode="decimal" id="sim-rate" min="-20" max="50" step="0.5" bind:value={f.taux}>
      </div>
      <div class="form-group">
        <label for="sim-years">Durée (années)</label>
        <input type="text" inputmode="numeric" id="sim-years" min="1" max="50" bind:value={f.annees}>
      </div>
    </div>
    <button type="submit" class="btn btn-primary">Simuler</button>
  </form>
  <div id="simulation-result" style="margin-top:1.25rem">
    {#if resultat}
      {#key masque}
      <div class="kpi-grid" style="grid-template-columns:repeat(3,1fr);margin-bottom:1rem">
        <div class="kpi-card"><div class="kpi-label">Capital final</div><div class="kpi-value">{fmt(resultat.final_balance)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Total investi</div><div class="kpi-value">{fmt(resultat.total_invested)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Plus-values</div><div class="kpi-value" style="color:{resultat.gains >= 0 ? 'var(--success)' : 'var(--danger)'}">{fmt(resultat.gains)}</div></div>
      </div>
      {/key}
      <div style="position:relative;height:250px"><canvas id="simulation-chart" bind:this={toileSimul}></canvas></div>
    {/if}
  </div>
</div>

<div class="card">
  <h2>Arrêté automatique</h2>
  <p class="text-muted" style="font-size:12.5px;margin-bottom:.875rem">
    Duplique le dernier arrêté à la date du jour. Utile pour garder un historique régulier sans modifier manuellement les positions.
  </p>
  <button class="btn btn-secondary" id="btn-auto-snapshot" onclick={() => triggerAutoSnapshot()}>Créer un arrêté aujourd'hui</button>
</div>

<div class="card">
  <h2>Cours de marché</h2>
  <p class="text-muted" style="font-size:12.5px;margin-bottom:.875rem">
    Rafraîchit automatiquement les derniers cours des ISIN cotés (actions, ETF, OPCVM). Les fonds euros et actifs non cotés sont ignorés.
  </p>
  <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">
    <button class="btn btn-primary" id="btn-refresh-prices" onclick={() => triggerPricesRefresh(false)}>Rafraîchir les cours</button>
    <button class="btn btn-secondary" id="btn-refresh-prices-stale" onclick={() => triggerPricesRefresh(true)}>Rafraîchir uniquement les périmés (&gt;20h)</button>
  </div>
  <!-- Remplis par tools.js (triggerPricesRefresh, loadSchedulerStatus) : Svelte n'y touche pas. -->
  <div id="prices-refresh-result" style="margin-top:1rem;font-size:12.5px"></div>
  <div id="scheduler-status" style="margin-top:.75rem;font-size:12px;color:var(--text-muted)"></div>
</div>
