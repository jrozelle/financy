<script lang="ts">
  /**
   * « D'ou vient la hausse » : l'epargne nouvelle, le capital rembourse, la
   * performance des marches — et les comptes entres ou sortis du suivi.
   *
   * Une hausse peut venir de l'epargne — qui se pilote — ou du marche — qui se
   * subit. Barres empilees en SVG : quatre a huit barres ne justifient pas une
   * librairie, et le SVG suit les variables de theme.
   *
   * Porte de static/modules/tabs/contribution.js, balisage a l'identique.
   */
  import { api } from '/static/modules/api.js';
  import { fmt, fmtDate, fmtPct } from '/static/modules/utils.js';
  import { isMasked } from '/static/modules/mask.js';

  interface Compte { compte: string; sens: 'entree' | 'sortie' | 'deplace'; date: string; montant: number }
  interface Periode {
    libelle: string; debut: string; fin: string; variation: number; epargne: number; capital: number;
    performance: number; hors_suivi?: number; versements?: number; comptes_hors_suivi?: Compte[];
  }
  interface Reponse {
    periodes?: Periode[]; total_variation: number; total_epargne: number; total_capital: number;
    total_performance: number; total_hors_suivi?: number;
  }

  let { hote, masque = false }: { hote: HTMLElement; masque?: boolean } = $props();

  let donnees = $state<Reponse | null>(null);
  let sousTitre = $state('');
  let jeton = 0;

  /** L'API decompose toujours jusqu'au dernier arrete, quel que soit celui
   *  consulte : le sous-titre le dit. */
  export async function recharger(owner: string | null, consulte: string | null, dernier: string | null) {
    const j = ++jeton;
    const base = 'Épargne nouvelle, capital remboursé et effet des marchés, par trimestre';
    let d: Reponse | null = null;
    try {
      const q = new URLSearchParams({ limit: '6' });
      if (owner && owner !== 'Famille') q.set('owner', owner);
      d = await api<Reponse>('GET', `/api/contribution?${q}`, null, { silent: true });
    } catch { /* carte masquee */ }
    if (j !== jeton) return;
    sousTitre = consulte && dernier && consulte !== dernier
      ? `${base}, jusqu'au dernier arrêté (${fmtDate(dernier)}) et non celui consulté`
      : `${base}, jusqu'au dernier arrêté`;
    donnees = d;
  }

  // Une periode sans mouvement ni apport n'apporte rien : elle occuperait une
  // colonne pour un trait a zero. Moins de deux periodes : rien a comparer.
  const periodes = $derived((donnees?.periodes || [])
    .filter(p => [p.variation, p.epargne, p.capital, p.hors_suivi].some(v => Math.abs(v || 0) > 100)));
  const visible = $derived(periodes.length >= 2);
  $effect(() => { hote.style.display = visible ? '' : 'none'; });

  // ── Dessin, a la largeur reelle de la carte (echelle 1) ────────────────
  let largeurHote = $state(0);
  const H = 150, BAS = 30, MARGE = 26;
  const parts3 = (p: Periode) => [p.epargne, p.capital, p.performance, p.hors_suivi || 0];

  /** « +12 k » au-dessus de mille, la valeur exacte en deca. Ecrit a la main,
   *  ce libelle doit suivre le mode discretion lui-meme. */
  const millier = (v: number, _masque: boolean) => {
    const signe = v >= 0 ? '+' : '−';
    if (isMasked()) return `${signe}•••`;
    const a = Math.abs(v);
    return a >= 1000 ? `${signe}${Math.round(a / 1000)} k` : `${signe}${Math.round(a)}`;
  };

  const dessin = $derived.by(() => {
    // 78 px par periode au minimum : en deca, le libelle de valeur deborde.
    const L = Math.max(Math.round(largeurHote || 0), 78 * periodes.length + 30);
    const haut = Math.max(...periodes.map(p => parts3(p).reduce((t, v) => t + Math.max(0, v), 0)), 0);
    const bas = Math.min(...periodes.map(p => parts3(p).reduce((t, v) => t + Math.min(0, v), 0)), 0);
    const etendue = (haut - bas) || 1;
    const zero = MARGE + (H - MARGE) * (haut / etendue);
    const ech = (v: number) => (Math.abs(v) / etendue) * (H - MARGE);
    const pas = (L - 30) / periodes.length;
    const barre = Math.min(pas * 0.5, 40);
    const colonnes = periodes.map((p, i) => {
      const cx = 15 + pas * (i + 0.5);
      const x = cx - barre / 2;
      let hautCumul = zero, basCumul = zero;
      const segs: { y: number; h: number; couleur: string }[] = [];
      const seg = (valeur: number, couleur: string) => {
        if (!valeur) return;
        const h = ech(valeur);
        const y = valeur > 0 ? (hautCumul -= h) : basCumul;
        if (valeur < 0) basCumul += h;
        segs.push({ y, h: Math.max(h, 1), couleur });
      };
      // Les segments d'abord : ce sont eux qui font monter le sommet.
      seg(p.performance, 'var(--chart-1)'); seg(p.capital, 'var(--chart-2)');
      seg(p.epargne, 'var(--chart-4)'); seg(p.hors_suivi || 0, 'var(--text-muted)');
      const total = parts3(p).reduce((t, v) => t + v, 0);
      return { cx, x, segs, total, yVal: Math.min(hautCumul, zero) - 7, pas };
    });
    return { L, zero, barre, colonnes };
  });

  // ── Bulle de detail : survol, focus clavier ou toucher ─────────────────
  let actif = $state<number | null>(null);
  let bulle = $state<HTMLElement>();
  let cadre = $state<HTMLElement>();
  let gauche = $state(0);
  async function montrer(i: number, zone: Element) {
    actif = i;
    await Promise.resolve();
    if (!cadre) return;
    // Centree sur la colonne, sans deborder de la carte.
    const r = zone.getBoundingClientRect(), c = cadre.getBoundingClientRect();
    const w = bulle?.offsetWidth || 220;
    gauche = Math.max(0, Math.min(r.left - c.left + r.width / 2 - w / 2, c.width - w));
  }
  const signe = (v: number) => `${v >= 0 ? '+' : '−'}${fmt(Math.abs(v))}`;
  const p = $derived(actif != null ? periodes[actif] : null);

  // ── Legende ────────────────────────────────────────────────────────────
  const part = $derived(donnees?.total_variation
    ? (donnees.total_performance / donnees.total_variation) * 100 : null);
  const comptesHors = $derived((donnees?.periodes || []).flatMap(x => x.comptes_hors_suivi || []));
  const hors = $derived(donnees?.total_hors_suivi || 0);
  let horsOuvert = $state(false);
  const SENS = { entree: 'apparu', sortie: 'disparu', deplace: 'changé d’enveloppe' };
</script>

{#key masque}
{#if visible && donnees}
  <div class="card-head">
    <div>
      <h2>D'où vient la hausse</h2>
      <p class="card-hint">{sousTitre}</p>
    </div>
  </div>
  <div id="contribution-chart" bind:clientWidth={largeurHote}>
    <div class="courbe-cadre" bind:this={cadre}>
      <svg class="contrib-svg" viewBox="0 0 {dessin.L} {H + BAS}" role="img"
           aria-label="Décomposition de la variation par période : épargne, capital remboursé, performance"
           onpointerleave={() => actif = null}>
        <line x1="10" y1={dessin.zero.toFixed(1)} x2={dessin.L - 10} y2={dessin.zero.toFixed(1)} class="contrib-zero"/>
        {#each dessin.colonnes as c, i (i)}
          {#each c.segs as s, k (k)}
            <rect x={c.x.toFixed(1)} y={s.y.toFixed(1)} width={dessin.barre.toFixed(1)} height={s.h.toFixed(1)} fill={s.couleur} rx="2"/>
          {/each}
          <text x={c.cx.toFixed(1)} y={(H + 15).toFixed(1)} text-anchor="middle" class="contrib-axe">{periodes[i].libelle || ''}</text>
          <text x={c.cx.toFixed(1)} y={c.yVal.toFixed(1)} text-anchor="middle" class="contrib-val">{millier(c.total, masque)}</text>
          <!-- Zone de survol : toute la colonne, pas seulement la barre. -->
          <rect class="contrib-zone" class:is-actif={actif === i} data-i={i} x={(c.cx - c.pas / 2).toFixed(1)} y="0"
                width={c.pas.toFixed(1)} height={(H + BAS).toFixed(1)} fill="transparent" tabindex="0" role="button"
                aria-label="{periodes[i].libelle || ''} : détail"
                onpointerover={e => montrer(i, e.currentTarget)} onfocusin={e => montrer(i, e.currentTarget)}
                onfocusout={() => actif = null}/>
        {/each}
      </svg>
      <div class="courbe-bulle" role="status" hidden={!p} bind:this={bulle} style:left="{gauche}px" style:top="0px">
        {#if p}
          {@const hs = p.hors_suivi || 0}
          <span class="courbe-bulle-d">{p.libelle} · du {fmtDate(p.debut)} au {fmtDate(p.fin)}</span>
          <span class="courbe-bulle-l"><i style:background="var(--chart-4)"></i>Épargne nouvelle<b>{signe(p.epargne)}</b></span>
          {#if Math.abs(p.versements || 0) >= 1}<span class="courbe-bulle-a">dont {fmt(p.versements)} versés sur les placements</span>{/if}
          {#if Math.abs(p.capital || 0) >= 1}<span class="courbe-bulle-l"><i style:background="var(--chart-2)"></i>Capital remboursé<b>{signe(p.capital)}</b></span>{/if}
          <span class="courbe-bulle-l"><i style:background="var(--chart-1)"></i>Performance<b>{signe(p.performance)}</b></span>
          {#if Math.abs(hs) >= 1}<span class="courbe-bulle-l"><i style:background="var(--text-muted)"></i>Comptes ajoutés ou retirés<b>{signe(hs)}</b></span>{/if}
          <span class="courbe-bulle-l contrib-bulle-total">Variation du net<b>{signe(p.variation)}</b></span>
        {/if}
      </div>
    </div>
  </div>
  <div class="stack-legend" id="contribution-legend">
    <span><i style:background="var(--chart-4)"></i>Épargne nouvelle
      <b class="num">{fmt(donnees.total_epargne)}</b></span>
    {#if Math.abs(donnees.total_capital || 0) >= 1}<span><i style:background="var(--chart-2)"></i>Capital remboursé
      <b class="num">{fmt(donnees.total_capital)}</b></span>{/if}
    <span><i style:background="var(--chart-1)"></i>Performance
      <b class="num">{fmt(donnees.total_performance)}</b></span>
    {#if Math.abs(hors) >= 1}
      <!-- Comptes entres ou sortis du suivi sans flux pour l'expliquer : leur
           valeur n'est pas de la performance, et designe souvent un flux oublie. -->
      <button type="button" class="contrib-hors" aria-expanded={horsOuvert} aria-controls="contrib-hors-liste"
              onclick={() => horsOuvert = !horsOuvert}>
        <i style:background="var(--text-muted)"></i>Comptes ajoutés ou retirés <b class="num">{fmt(hors)}</b>
        <span class="contrib-hors-voir">{comptesHors.length} compte{comptesHors.length > 1 ? 's' : ''} ▾</span></button>
    {/if}
    {#if part !== null && donnees.total_variation > 0}<span class="contrib-part">{fmtPct(part, 0)} de la hausse vient des marchés</span>{/if}
    {#if comptesHors.length}
      <ul class="contrib-hors-liste" id="contrib-hors-liste" hidden={!horsOuvert}>
        {#each comptesHors as c, i (i)}
          <li><span>{c.compte}</span><span class="contrib-hors-date">{SENS[c.sens] || ''} au {fmtDate(c.date)}</span><b class="num">{fmt(c.montant)}</b></li>
        {/each}
        <li class="contrib-hors-aide">Aucun versement ni retrait enregistré ne l'explique. Si l'argent venait
          d'un autre compte suivi, il manque un flux : ajoutez-le dans Flux, la part rejoindra l'épargne.</li>
      </ul>
    {/if}
  </div>
{/if}
{/key}
