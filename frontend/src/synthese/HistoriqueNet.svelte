<script lang="ts">
  /**
   * « Evolution du patrimoine net » : la courbe du titulaire choisi, et sous
   * elle ce qui explique la variation — l'epargne nouvelle, le capital
   * rembourse, l'effet des marches. Comparer ce patrimoine a un indice serait
   * trompeur : il grossit aussi de ce qu'on y verse (voir Performance).
   *
   * Porte de static/modules/tabs/synthese.js (renderHistChart), balisage a
   * l'identique.
   */
  import { api } from '/static/modules/api.js';
  import { fmt, fmtDate, fmtPct } from '/static/modules/utils.js';
  import { dessinerCourbe } from '/static/modules/courbe.js';
  import { drilldownPositions } from '/static/modules/drilldown.js';

  interface Point { date: string; family_net: number; by_owner?: Record<string, number> }
  interface Decompo { periodes?: { debut: string; fin: string }[]; total_epargne: number; total_capital?: number;
                      total_performance: number; total_hors_suivi?: number }

  let { historique = [], owner = null, masque = false }: {
    historique?: Point[]; owner?: string | null; masque?: boolean;
  } = $props();

  const qui = $derived(owner || 'Famille');
  const points = $derived(historique.map(h => ({ date: h.date, v: owner ? (h.by_owner?.[owner] || 0) : h.family_net })));
  const debut = $derived(points[0]);
  const fin = $derived(points[points.length - 1]);

  let hoteCourbe = $state<HTMLElement>();
  $effect(() => {
    void masque;
    if (!hoteCourbe || !points.length) return;
    const o = owner, q = qui;
    dessinerCourbe(hoteCourbe, {
      series: [{ nom: `Patrimoine net — ${q}`, couleur: 'var(--primary)', points, aire: true }],
      formatV: v => fmt(v),
      aide: `Patrimoine net ${q} : ${fmt(debut.v)} le ${fmtDate(debut.date)}, ${fmt(fin.v)} le ${fmtDate(fin.date)}.`,
      onPoint: date => { api<{ owner: string }[]>('GET', `/api/positions?date=${date}`).then(positions => {
        const lignes = o ? positions.filter(p => p.owner === o) : positions;
        drilldownPositions(lignes, `${q} — ${fmtDate(date)}`, 'Composition à cette date', { showOwner: !o });
      }); },
    });
  });

  // La decomposition de la variation, sur la meme periode que la courbe :
  // au-dela de 40 arretes, le serveur tronque et les chiffres ne
  // s'additionneraient plus — la legende se contente alors de la variation.
  let decompo = $state<Decompo | null>(null);
  let cleVue = '';
  let jeton = 0;
  $effect(() => {
    if (!debut || !fin) return;
    const q = new URLSearchParams({ limit: '40' });
    if (owner) q.set('owner', owner);
    const cle = `${q}|${debut.date}|${fin.date}`;
    if (cle === cleVue) return;
    cleVue = cle;
    const j = ++jeton;
    decompo = null;
    api<Decompo>('GET', `/api/contribution?${q}`, null, { silent: true }).then(d => {
      if (j !== jeton) return;
      const du = d.periodes?.[0]?.debut, au = d.periodes?.[d.periodes.length - 1]?.fin;
      decompo = d.periodes?.length && du === debut.date && au === fin.date ? d : null;
    }).catch(() => { /* la courbe reste lisible sans elle */ });
  });

  const signe = (v: number) => `${v >= 0 ? '+' : '−'}${fmt(Math.abs(v))}`;
  const variation = $derived(fin && debut ? fin.v - debut.v : 0);
  const pct = $derived(debut?.v ? variation / Math.abs(debut.v) * 100 : null);
</script>

<h2>Évolution du patrimoine net</h2>
<p class="card-sub" id="evolution-sous">{points.length
  ? `${points.length} arrêtés · du ${fmtDate(debut.date)} au ${fmtDate(fin.date)}` : 'Tous les arrêtés enregistrés'}</p>
<div id="evolution-courbe" class="courbe-hote" bind:this={hoteCourbe}></div>
<div id="evolution-legende" class="courbe-legende" aria-live="polite">
  {#key masque}
  {#if points.length}
    <span>Variation <b>{signe(variation)}</b>{#if pct != null} <b>{fmtPct(pct, 1, true)}</b>{/if}</span>
    {#if decompo}
      <span><i style:background="var(--chart-4)"></i>Épargne nouvelle <b>{signe(decompo.total_epargne)}</b></span>
      {#if Math.abs(decompo.total_capital || 0) >= 1}<span><i style:background="var(--chart-2)"></i>Capital remboursé <b>{signe(decompo.total_capital || 0)}</b></span>{/if}
      <span><i style:background="var(--chart-1)"></i>Marchés <b>{signe(decompo.total_performance)}</b></span>
      {#if Math.abs(decompo.total_hors_suivi || 0) >= 1}<span><i style:background="var(--text-muted)"></i>Comptes ajoutés ou retirés <b>{signe(decompo.total_hors_suivi || 0)}</b></span>{/if}
    {/if}
    <span class="courbe-note">Chaque arrêté ouvre sa composition</span>
  {/if}
  {/key}
</div>
