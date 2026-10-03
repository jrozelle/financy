<script lang="ts">
  /**
   * Les chiffres de tete : un domine (le net), trois le qualifient (brut,
   * dettes, mobilisable). Chacun avec sa variation sur la periode choisie
   * dans l'en-tete, sa tendance, et un sous-titre qui le situe.
   *
   * Sous le net, l'objectif de patrimoine de la vue (famille ou titulaire) : une jauge,
   * et quand il tombe au rythme des derniers mois.
   */
  import { api } from '/static/modules/api.js';
  import { fmt, fmtDate, fmtPct, kpiDelta, sparkline } from '/static/modules/utils.js';

  interface Variation { prev_date?: string; net_delta?: number | null; net_pct?: number | null; [k: string]: unknown }
  interface Props {
    kpi: { net: number; gross: number; debt: number; mob: number };
    owner: string; famille: boolean; date: string | null;
    variation: Variation | null; variationAn: Variation | null; surAn: boolean;
    series: { net: (number | null)[]; gross: (number | null)[]; debt: (number | null)[]; mob: (number | null)[] };
    dates: string[]; objectif: number | null;
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
    const out: { sens: 'pos' | 'neg'; montant: string; pct: string; duree: string; exc: string }[] = [];
    // Une variation brute est juste mais trompeuse quand un heritage y est :
    // la pastille dit la part des flux exceptionnels qu'elle contient.
    const puce = (d: number | null | undefined, pc: number | null | undefined, du: string, depuis: string) => {
      if (d == null && pc == null) return;
      const x = periodes.filter(q => q.debut >= depuis).reduce((t, q) => t + (q.exceptionnel || 0), 0);
      out.push({ sens: (d ?? pc)! >= 0 ? 'pos' : 'neg', duree: du,
                 montant: d != null ? `${d >= 0 ? '+' : '−'}${fmt(Math.abs(d))}` : '',
                 pct: pc != null ? ` ${fmtPct(pc, 1, true)}` : '',
                 exc: Math.abs(x) >= 1 ? `dont ${x >= 0 ? '+' : '−'}${fmt(Math.abs(x))} de flux exceptionnels` : '' });
    };
    const { dates } = p, valeurs = p.series.net;
    const v = p.variation;
    if (v?.prev_date) puce(v.net_delta, v.net_pct, duree(v.prev_date, p.date || dates[dates.length - 1]), v.prev_date);
    const i = dates.findIndex(d => d === (p.date || dates[dates.length - 1]));
    const fin = i >= 0 ? i : dates.length - 1;
    if (fin < 0) return out;
    const cible = new Date(Date.parse(dates[fin]) - 365 * 864e5).toISOString().slice(0, 10);
    let debut = dates.findIndex(d => d >= cible);
    if (debut < 0 || debut >= fin) debut = 0;
    const v0 = valeurs[debut], v1 = valeurs[fin];
    if (fin > debut && v0) puce(null, ((v1 ?? 0) - v0) / Math.abs(v0) * 100,
                               dates[debut] <= cible ? '1 an' : `depuis le ${fmtDate(dates[debut])}`, dates[debut]);
    return out;
  });
  // ── Rythme : la variation du net sur tout l'historique, HORS comptes
  // ajoutes ou retires et HORS flux exceptionnels (la decomposition de
  // « D'ou vient la hausse »). La droite du premier au dernier arrete prenait
  // un heritage recu en quinze jours pour un rythme, et l'arrivee d'un compte
  // dans le suivi pour de l'enrichissement.
  interface Periode { debut: string; fin: string; variation: number; hors_suivi?: number; exceptionnel?: number }
  let rythme = $state<{ parJour: number; mois: number } | null>(null);
  let periodes = $state<Periode[]>([]);
  let jeton = 0;
  $effect(() => {
    void p.date; void p.objectif;
    const j = ++jeton, q = new URLSearchParams({ limit: '40' });
    if (!p.famille && p.owner) q.set('owner', p.owner);
    api<{ periodes?: Periode[] }>('GET', `/api/contribution?${q}`, null, { silent: true })
      .then(d => {
        if (j !== jeton) return;
        periodes = d?.periodes || [];
        let jours = 0, gain = 0;
        for (const x of d?.periodes || []) {
          jours += (Date.parse(x.fin) - Date.parse(x.debut)) / 864e5;
          gain += (x.variation || 0) - (x.hors_suivi || 0) - (x.exceptionnel || 0);
        }
        rythme = jours > 30 ? { parJour: gain / jours, mois: Math.round(jours / 30.44) } : null;
      })
      .catch(() => { if (j === jeton) { rythme = null; periodes = []; } });
  });

  // L'objectif est celui de la vue affichee (famille ou titulaire) : la jauge
  // compare le net de cette vue a son propre objectif.
  const but = $derived.by(() => {
    const cible = p.objectif, net = p.kpi.net;
    if (!cible) return null;
    const pct = cible > 0 ? Math.min((net / cible) * 100, 100) : 0;
    let quand: { prefixe: string; date: string; mois: number } | null = null, atteint = false;
    if (net >= cible) atteint = true;
    else if (rythme && rythme.parJour > 0) {
      const restant = (cible - net) / rythme.parJour;
      if (restant < 3650) {
        const date = new Date(Date.now() + restant * 864e5);
        const cetteAnnee = date.getFullYear() === new Date().getFullYear();
        quand = { prefixe: cetteAnnee ? 'Atteint le' : 'Atteint en', mois: rythme.mois,
                  date: date.toLocaleDateString('fr-FR', cetteAnnee ? { day: 'numeric', month: 'short' } : { month: 'short', year: 'numeric' }) };
      }
    }
    return { cible, pct, quand, atteint, reste: Math.max(cible - net, 0) };
  });

  const spark = (serie: (number | null)[], couleur = 'var(--primary)') => sparkline(serie, { couleur, dates: p.dates });
</script>

<div class="kpi-card clickable kpi-hero">
  <div class="kpi-label" id="kpi-net-label">{p.famille ? 'Patrimoine net famille' : `Patrimoine net — ${p.owner}`}</div>
  <div class="kpi-value" id="kpi-net">{fmt(p.kpi.net)}{#if pastilles.length}<div class="hero-puces">{#each pastilles as x, i (i)}<span
    class="puce puce--{x.sens}">{x.montant}{x.pct}<small>{x.duree}{#if x.exc}{' · '}{x.exc}{/if}</small></span>{/each}</div>{/if}</div>
  <div id="kpi-hero-goal" class={but ? 'hero-goal' : ''}>{#if but}
    <div class="g-track"><span class="g-fill" style:width="{but.pct.toFixed(1)}%"></span></div>
    <div class="g-foot">
      <span>Objectif <b>{fmt(but.cible)}</b></span>
      <span>{#if but.atteint}<b>Objectif atteint</b>{:else if but.quand}{but.quand.prefixe} <b>{but.quand.date}</b> au rythme des {but.quand.mois} derniers mois{:else}Reste <b>{fmt(but.reste)}</b>{/if}</span>
    </div>{/if}</div>
  <div id="kpi-hero-spark">{#if !p.objectif}{@html spark(p.series.net)}{/if}</div>
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
