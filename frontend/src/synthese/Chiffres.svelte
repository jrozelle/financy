<script lang="ts">
  /**
   * Les chiffres de tete : un domine (le net), trois le qualifient (brut,
   * dettes, mobilisable). Chacun avec sa variation sur la periode choisie
   * dans l'en-tete, sa tendance, et un sous-titre qui le situe.
   *
   * `#kpi-hero-goal` reste vide ici : l'objectif de patrimoine y ecrit
   * (static/modules/tabs/synthese.js), le temps que sa carte soit portee.
   */
  import { fmt, fmtDate, fmtPct, kpiDelta, sparkline } from '/static/modules/utils.js';

  interface Variation { prev_date?: string; net_delta?: number | null; net_pct?: number | null; [k: string]: unknown }
  interface Props {
    kpi: { net: number; gross: number; debt: number; mob: number };
    owner: string; famille: boolean; date: string | null;
    variation: Variation | null; variationAn: Variation | null; surAn: boolean;
    series: { net: (number | null)[]; gross: (number | null)[]; debt: (number | null)[]; mob: (number | null)[] };
    dates: string[]; objectif: boolean;
    immo: number; court: number;
  }
  let p: Props = $props();

  const libelle = (base: string) => p.famille ? base : `${base} — ${p.owner}`;
  // Un seul jeu de deltas, celui de la periode choisie dans l'en-tete.
  const delta = (champ: string, clePct: string | null = null, invert = false) => {
    const source = p.surAn ? p.variationAn : p.variation;
    return source ? kpiDelta(source, champ, clePct, { invert, label: p.surAn ? 'sur 1 an' : null }) : '';
  };

  function duree(d0: string, d1: string) {
    const j = Math.round((Date.parse(d1) - Date.parse(d0)) / 864e5);
    if (j < 45) return `${j} j`;
    if (j < 335) return `${Math.round(j / 30.44)} mois`;
    const a = Math.round(j / 365.25);
    return `${a} an${a > 1 ? 's' : ''}`;
  }

  /** Deux pastilles sous le net : depuis le dernier arrete, et sur un an —
   *  ou depuis le premier arrete tant qu'un an manque. */
  const pastilles = $derived.by(() => {
    const out: { sens: 'pos' | 'neg'; montant: string; pct: string; duree: string }[] = [];
    const puce = (d: number | null | undefined, pc: number | null | undefined, du: string) => {
      if (d == null && pc == null) return;
      out.push({ sens: (d ?? pc)! >= 0 ? 'pos' : 'neg', duree: du,
                 montant: d != null ? `${d >= 0 ? '+' : '−'}${fmt(Math.abs(d))}` : '',
                 pct: pc != null ? ` ${fmtPct(pc, 1, true)}` : '' });
    };
    const { dates } = p, valeurs = p.series.net;
    const v = p.variation;
    if (v?.prev_date) puce(v.net_delta, v.net_pct, duree(v.prev_date, p.date || dates[dates.length - 1]));
    const i = dates.findIndex(d => d === (p.date || dates[dates.length - 1]));
    const fin = i >= 0 ? i : dates.length - 1;
    if (fin < 0) return out;
    const cible = new Date(Date.parse(dates[fin]) - 365 * 864e5).toISOString().slice(0, 10);
    let debut = dates.findIndex(d => d >= cible);
    if (debut < 0 || debut >= fin) debut = 0;
    const v0 = valeurs[debut], v1 = valeurs[fin];
    if (fin > debut && v0) puce(null, ((v1 ?? 0) - v0) / Math.abs(v0) * 100,
                               dates[debut] <= cible ? '1 an' : `depuis le ${fmtDate(dates[debut])}`);
    return out;
  });
  const spark = (serie: (number | null)[], couleur = 'var(--primary)') => sparkline(serie, { couleur, dates: p.dates });
</script>

<div class="kpi-card clickable kpi-hero">
  <div class="kpi-label" id="kpi-net-label">{p.famille ? 'Patrimoine net famille' : `Patrimoine net — ${p.owner}`}</div>
  <div class="kpi-value" id="kpi-net">{fmt(p.kpi.net)}{#if pastilles.length}<div class="hero-puces">{#each pastilles as x, i (i)}<span
    class="puce puce--{x.sens}">{x.montant}{x.pct}<small>{x.duree}</small></span>{/each}</div>{/if}</div>
  <div id="kpi-hero-goal"></div>
  <div id="kpi-hero-spark">{#if !(p.famille && p.objectif)}{@html spark(p.series.net)}{/if}</div>
</div>
<div class="kpi-card clickable kpi-gross">
  <div class="kpi-label" id="kpi-gross-label">{libelle('Actifs bruts')}</div>
  <div class="kpi-value" id="kpi-gross">{fmt(p.kpi.gross)}{@html delta('gross_delta')}{@html spark(p.series.gross)}</div>
  <div class="kpi-sub" id="kpi-gross-sub">{p.immo ? `dont ${fmt(p.immo)} d'immobilier` : ''}</div>
</div>
<div class="kpi-card clickable kpi-debt">
  <div class="kpi-label" id="kpi-debt-label">{libelle('Dettes')}</div>
  <!-- La dette en teinte neutre : ni bonne ni mauvaise en soi. -->
  <div class="kpi-value" id="kpi-debt">{fmt(p.kpi.debt)}{@html delta('debt_delta', null, true)}{@html spark(p.series.debt, 'var(--text-muted)')}</div>
  <div class="kpi-sub" id="kpi-debt-sub">{p.kpi.gross ? `${fmtPct(p.kpi.debt / p.kpi.gross * 100)} du brut` : ''}</div>
</div>
<div class="kpi-card clickable kpi-mobilizable">
  <div class="kpi-label" id="kpi-mob-label">{libelle('Mobilisable')}</div>
  <div class="kpi-value" id="kpi-mobilizable">{fmt(p.kpi.mob)}{@html delta('mob_delta')}{@html spark(p.series.mob)}</div>
  <div class="kpi-sub" id="kpi-mob-sub">{p.kpi.net
    ? `${fmtPct(p.kpi.mob / p.kpi.net * 100, 0)} du net` + (p.court ? ` · ${fmt(p.court)} sous 24 h` : '') : ''}</div>
</div>
