<script lang="ts">
  /**
   * Tresorerie d'une entite sur la periode de ses releves : le verdict en
   * phrases, les chiffres, douze mois d'entrees et de sorties, puis ses parts,
   * son impot sur les societes et ses operations.
   *
   * Porte de static/modules/tabs/tresorerie.js (_bloc, _verdict, _graphe,
   * _cabler), balisage a l'identique.
   */
  import { tick } from 'svelte';
  import { fmt } from '/static/modules/utils.js';
  import PartsEntite from './PartsEntite.svelte';
  import FiscalEntite from './FiscalEntite.svelte';
  import OperationsEntite from './OperationsEntite.svelte';
  import RelevesEntite from './RelevesEntite.svelte';
  import { MOIS_COURTS, moisLib, virgule, type Bloc } from './donnees-tresorerie';

  let { b, idx, natures, onRecharger }: {
    b: Bloc; idx: number; natures: Record<string, string>; onRecharger: () => Promise<void>;
  } = $props();

  const pct = (v: number | null) => v == null ? '—' : `${(v * 100).toFixed(1).replace('.', ',')} %`;
  const signe = (v: number) => `${v >= 0 ? '+' : '−'}${fmt(Math.abs(v))}`;

  const i = $derived(b.indicateurs);
  const c = $derived(b.credit);
  const t = $derived(b.totaux);
  const periode = $derived(b.periode!);
  const nbReleves = $derived(new Set(b.operations.map(o => o.source)).size);
  // Les frais d'entree des parts : partis des l'achat, ils ne se voient qu'a
  // la revente. Le capital rembourse doit d'abord les rattraper.
  const annees = $derived(c?.capital ? b.frais_latents / c.capital * (12 / periode.mois) : null);
  const ecart = $derived(c ? c.capital + (i.cash_flow_net || 0) : 0);

  // ── Douze colonnes : les entrees au-dessus de zero, les sorties en dessous.
  const W = 640, H = 170;
  const haut = (m: Bloc['mensuel'][number]) => m.revenu + m.revenu_exceptionnel;
  const bas = (m: Bloc['mensuel'][number]) => -(m.echeance + m.frais);
  const n = $derived(b.mensuel.length);
  const zero = H / 2;
  const k = $derived((zero - 6) / Math.max(1, ...b.mensuel.map(m => Math.max(haut(m), bas(m), m.apport))));
  const col = $derived(W / n);
  const larg = $derived(Math.min(26, col * .55));

  // ── Bulle : detail du mois au survol, au focus ou au toucher.
  let actif = $state<number | null>(null);
  let gauche = $state(0);
  let cadre = $state<HTMLElement>();
  let bulle = $state<HTMLElement>();
  async function montrer(g: Element | null) {
    if (!g || !(g instanceof SVGGElement) || !g.dataset.i) return;
    actif = +g.dataset.i;
    await tick();
    const r = g.getBoundingClientRect(), cc = cadre!.getBoundingClientRect();
    const w = bulle!.offsetWidth || 200;
    gauche = Math.max(0, Math.min(r.left - cc.left + r.width / 2 - w / 2, cc.width - w));
  }
  const cacher = () => { actif = null; };
  const m = $derived(actif == null ? null : b.mensuel[actif]);
</script>

<section class="treso" data-treso={idx} aria-label="Trésorerie de {b.entite}">
  <div class="treso-tete">
    <h3>{b.entite}</h3>
    <span class="text-muted">{moisLib(periode.debut)} – {moisLib(periode.fin)}, d'après {nbReleves} relevé{nbReleves > 1 ? 's' : ''}</span>
  </div>
  <!-- Une idee par ligne : en paragraphe, cinq chiffres se lisaient d'un bloc. -->
  <ul class="treso-verdict">
    {#if i.couverture != null}<li>Les loyers paient <b>{pct(i.couverture)}</b> de l'échéance du crédit.</li>{/if}
    {#if i.effort_mensuel > 0}<li>Le reste, et les frais, demandent <b>{fmt(i.effort_mensuel)} par mois</b> aux associés.</li>{/if}
    {#if b.frais_latents > 0}<li>Au prix de retrait, les parts valent {fmt(b.parts?.valeur_retrait)} pour {fmt(b.parts?.montant_souscrit)}
      payés : <b>{fmt(b.frais_latents)} de frais d'entrée</b> déjà partis{annees
        ? `, soit ${annees.toFixed(1).replace('.', ',')} ans du capital remboursé aujourd'hui` : ''}.</li>{/if}
    {#if c && c.capital}
      <li>Sur la période, le crédit a coûté {fmt(c.interets + c.assurance)} d'intérêts et d'assurance,
        et remboursé <b>{fmt(c.capital)} de capital</b> : c'est de ce capital que la SCI s'enrichit.</li>
      {#if ecart >= 0}
        <li>Le capital remboursé dépasse l'effort de {fmt(ecart)} : le levier enrichit déjà, avant toute revalorisation des parts.</li>
      {:else}
        <li>L'effort dépasse le capital remboursé de {fmt(-ecart)} — la part des intérêts que les loyers ne couvrent pas.
          Le montage s'enrichit dès que les parts se revalorisent de plus de
          <b>{(-ecart / (b.parts?.valeur_retrait || b.valeur || 1) * 100).toFixed(2).replace('.', ',')} % par an</b>, avant impôt.</li>
      {/if}
    {/if}
  </ul>
  <div class="treso-kpis">
    {@render kpi('Revenus', fmt(t.revenu), t.revenu_exceptionnel ? `+ ${fmt(t.revenu_exceptionnel)} exceptionnels` : 'distributions récurrentes')}
    {@render kpi('Échéances', fmt(-t.echeance), c ? `dont ${fmt(c.capital)} de capital` : '')}
    {@render kpi('Apports des associés', fmt(i.apports), i.capital_par_euro_apporte != null
      ? `${virgule(i.capital_par_euro_apporte)} € de capital remboursé par euro` : '')}
    {@render kpi('Rendement distribué', pct(i.rendement), c?.taux ? `crédit à ${virgule(c.taux)} %` : '')}
    {@render kpi('Trésorerie', fmt(b.tresorerie), 'tous comptes')}
  </div>
  <div class="courbe-cadre treso-graphe" bind:this={cadre}>
    <div class="courbe-bulle" hidden={!m} bind:this={bulle} style:left="{gauche}px">
      {#if m}
        <span class="courbe-bulle-d">{moisLib(m.mois)}</span>
        {@render ligne('var(--success)', 'Revenus', m.revenu)}
        {#if m.revenu_exceptionnel}{@render ligne('var(--success)', 'Exceptionnels', m.revenu_exceptionnel)}{/if}
        {@render ligne('var(--danger)', 'Échéance', m.echeance)}
        {#if m.frais}{@render ligne('var(--danger)', 'Frais', m.frais)}{/if}
        <span class="courbe-bulle-l contrib-bulle-total">Solde du mois<b>{signe(m.revenu + m.revenu_exceptionnel + m.echeance + m.frais)}</b></span>
        {@render ligne('var(--text)', 'Apports des associés', m.apport)}
      {/if}
    </div>
    <!-- Etire en largeur, hauteur fixe : les mois vont dessous en HTML, a
         taille de texte constante — dans le SVG, ils grossissaient avec l'ecran. -->
    <svg class="courbe treso-svg" viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="group" aria-label="Flux mensuels"
         onpointerover={e => montrer((e.target as Element).closest('.treso-col'))} onpointerleave={cacher}
         onfocusin={e => montrer((e.target as Element).closest('.treso-col'))} onfocusout={cacher}>
      <line class="courbe-grille" x1="0" x2={W} y1={zero} y2={zero} vector-effect="non-scaling-stroke"/>
      {#each b.mensuel as mm, j (mm.mois)}
        {@const x = j * col + (col - larg) / 2}
        {@const hr = mm.revenu * k}
        {@const he = mm.revenu_exceptionnel * k}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
        <g class="treso-col" class:is-actif={actif === j} data-i={j} tabindex="0" role="button"
           aria-label="{moisLib(mm.mois)} : revenus {fmt(haut(mm))}, sorties {fmt(bas(mm))}, apports {fmt(mm.apport)}">
          <rect class="treso-zone" x={j * col} y="0" width={col} height={H}/>
          <rect x={x} y={zero - hr} width={larg} height={hr} fill="var(--success)" rx="2"/>
          {#if he}<rect x={x} y={zero - hr - he} width={larg} height={he} fill="var(--success)" fill-opacity=".45" rx="2"/>{/if}
          <rect x={x} y={zero} width={larg} height={bas(mm) * k} fill="var(--danger)" fill-opacity=".85" rx="2"/>
          {#if mm.apport}<line class="treso-apport" x1={x - 3} x2={x + larg + 3} y1={zero - mm.apport * k} y2={zero - mm.apport * k}
            vector-effect="non-scaling-stroke"/>{/if}
        </g>
      {/each}
    </svg>
    <div class="treso-mois" style="grid-template-columns:repeat({n},1fr)">{#each b.mensuel as mm (mm.mois)}<span>{MOIS_COURTS[+mm.mois.slice(5, 7) - 1]}</span>{/each}</div>
  </div>
  <div class="courbe-legende">
    <span><i class="treso-pastille" style="background:var(--success)"></i>Revenus</span>
    <span><i class="treso-pastille" style="background:var(--danger)"></i>Échéance et frais</span>
    <span><i class="treso-pastille treso-pastille--apport"></i>Apports des associés</span>
  </div>
  <PartsEntite {b} {idx} {onRecharger} />
  <FiscalEntite {b} {idx} {onRecharger} />
  <OperationsEntite {b} {idx} {natures} {onRecharger} />
  <RelevesEntite {b} {onRecharger} />
</section>

{#snippet kpi(lib: string, val: string, sous: string)}
  <div class="treso-kpi"><span class="treso-kpi-l">{lib}</span>
    <span class="treso-kpi-v">{val}</span>{#if sous}<span class="treso-kpi-s">{sous}</span>{/if}</div>
{/snippet}

{#snippet ligne(couleur: string, nom: string, v: number)}
  <span class="courbe-bulle-l"><i style:background={couleur}></i>{nom}<b>{signe(v)}</b></span>
{/snippet}
