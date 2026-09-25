<script lang="ts">
  /**
   * Projection du patrimoine net, en trois moteurs de certitude inegale :
   * - le desendettement : le capital que les echeanciers rembourseront, connu
   *   a l'euro pres (prets amortissables seulement : un in fine se rembourse
   *   d'un bloc, sur des actifs deja comptes) ;
   * - l'epargne NOUVELLE : l'argent qui entre dans le patrimoine ;
   * - le rendement du financier : une hypothese, affichee comme telle.
   * Le DCA n'est pas de l'epargne : il fait travailler l'excedent de
   * liquidites, sans changer le net.
   *
   * Porte de static/modules/tabs/projection.js, balisage a l'identique.
   */
  import { api } from '/static/modules/api.js';
  import { natureDe } from '/static/modules/categories.js';
  import { dessinerCourbe } from '/static/modules/courbe.js';
  import { fmt, fmtPct, parseLocaleNumber } from '/static/modules/utils.js';
  import { lirePref, ecrirePref } from '/static/modules/preferences.js';
  import { ecran } from '../commun/ecran.svelte';

  interface Position { category: string; envelope: string | null; net_attributed?: number }
  interface Mesure { nouvelle: { par_mois: number; periodes?: unknown[] }; dca: { mensuel: number; excedent: number } }
  interface Crd { dates: string[]; total: number[]; total_amortissable?: number[]; prets?: { in_fine?: boolean }[] }

  let { hote, positions = [], famille = true, net = 0, objectif = null, masque = false }: {
    hote: HTMLElement; positions?: Position[]; famille?: boolean; net?: number;
    objectif?: number | null; masque?: boolean;
  } = $props();

  // v2 : l'epargne a change de sens (nouvelle, et non plus versements).
  const CLE = 'financy_projection_v2';
  type Reglages = { epargne?: number; aInvestir?: number; dca?: number; rendement?: number; horizon?: number };
  const lireReglages = (): Reglages => { try { return JSON.parse(lirePref(CLE) || '') || {}; } catch { return {}; } };

  let mesure = $state<Mesure | null>(null);
  let crd = $state<Crd | null>(null);
  // La projection vise la famille, comme l'objectif : les credits d'une
  // entite ne se partagent pas proprement entre titulaires.
  const visible = $derived(famille && positions.length > 0);
  $effect(() => { hote.style.display = visible ? '' : 'none'; });

  let chargement = false;
  $effect(() => {
    if (!visible || mesure || chargement) return;
    chargement = true;
    Promise.all([
      api<Mesure>('GET', '/api/projection/epargne', null, { silent: true }).catch(() => null),
      api<Crd>('GET', '/api/prets/projection', null, { silent: true }).catch(() => null),
    ]).then(([e, c]) => {
      crd = c || { dates: [], total: [] };
      mesure = e || { nouvelle: { par_mois: 0, periodes: [] }, dca: { mensuel: 0, excedent: 0 } };
      remplir(lireReglages());
    });
  });

  // ── Reglages : champs texte (saisie libre, format francais) ────────────
  const DEFAUTS = {
    epargne: () => Math.round(mesure?.nouvelle.par_mois || 0),
    aInvestir: () => Math.round(mesure?.dca.excedent || 0),
    dca: () => Math.round(mesure?.dca.mensuel || 0),
    rendement: () => 3,
    horizon: () => 10,
  };
  // Montants : en mode discretion, leur valeur en clair trahirait l'epargne.
  const MONTANTS = ['epargne', 'aInvestir', 'dca'] as const;
  let champs = $state({ epargne: '', aInvestir: '', dca: '', rendement: '', horizon: '10' });

  function remplir(r: Reglages = {}) {
    const c = { ...champs };
    (Object.keys(DEFAUTS) as (keyof typeof DEFAUTS)[]).forEach(k => {
      if ((MONTANTS as readonly string[]).includes(k) && masque) { c[k] = ''; return; }
      c[k] = String(r[k] ?? DEFAUTS[k]());
    });
    champs = c;
  }
  // Les champs se vident ou se remplissent avec le mode discretion.
  let masqueVu: boolean | null = null;
  $effect(() => {
    const m = masque;
    if (mesure && masqueVu !== null && m !== masqueVu) remplir(lireReglages());
    masqueVu = m;
  });

  /** Le champ s'il est rempli, sinon (montant masque) la valeur memorisee ou mesuree. */
  function valeur(k: keyof typeof DEFAUTS): number {
    if ((MONTANTS as readonly string[]).includes(k) && masque && champs[k].trim() === '') {
      return lireReglages()[k] ?? DEFAUTS[k]();
    }
    return parseLocaleNumber(champs[k], 0);
  }
  function maj() {
    const r: Reglages = {};
    (Object.keys(DEFAUTS) as (keyof typeof DEFAUTS)[]).forEach(k => { r[k] = valeur(k); });
    ecrirePref(CLE, JSON.stringify(r));
  }
  function reinitialiser() { ecrirePref(CLE, JSON.stringify({})); remplir(); }

  /** Restant du des prets AMORTISSABLES a une date, interpole. */
  function crdA(t: number) {
    if (!crd?.dates?.length) return 0;
    const serie = crd.total_amortissable || crd.total;
    const ts = crd.dates.map(d => Date.parse(d));
    if (t <= ts[0]) return serie[0];
    for (let i = 1; i < ts.length; i++) {
      if (t <= ts[i]) {
        const k = (t - ts[i - 1]) / (ts[i] - ts[i - 1]);
        return serie[i - 1] + k * (serie[i] - serie[i - 1]);
      }
    }
    return serie[serie.length - 1];
  }

  // ── Simulation mois par mois ───────────────────────────────────────────
  const calcul = $derived.by(() => {
    if (!mesure || !visible) return null;
    void masque;
    const epargne = valeur('epargne');
    let aInvestir = Math.max(0, valeur('aInvestir'));
    const dca = Math.max(0, valeur('dca'));
    const taux = valeur('rendement') / 100;
    const annees = +champs.horizon || 10;
    const financier = positions.filter(p => natureDe(p.category, p.envelope) === 'fin')
      .reduce((s, p) => s + (p.net_attributed || 0), 0);
    const t0 = Date.now();
    const crd0 = crdA(t0);
    const rm = (1 + taux) ** (1 / 12) - 1;
    const points: { date: string; v: number }[] = [], sansRendement: { date: string; v: number }[] = [];
    let F = financier, epargneCum = 0, dcaCum = 0;
    let finDca: Date | null = null, atteint: string | null = null;
    let fin = { desendettement: 0, epargneCum: 0, rendement: 0, v: net, date: '' };
    for (let m = 0; m <= annees * 12; m++) {
      if (m > 0) {
        const deplace = Math.min(dca, aInvestir);
        aInvestir -= deplace; dcaCum += deplace;
        F = F * (1 + rm) + epargne + deplace;
        epargneCum += epargne;
      }
      const t = new Date(t0); t.setMonth(t.getMonth() + m);
      const desendettement = crd0 - crdA(+t);
      const rendement = F - financier - epargneCum - dcaCum;
      if (!finDca && dcaCum > 0 && aInvestir <= 0) finDca = t;
      const v = net + desendettement + epargneCum + rendement;
      const date = t.toISOString().slice(0, 10);
      if (m % 3 === 0 || m === annees * 12) {
        points.push({ date, v });
        sansRendement.push({ date, v: net + desendettement + epargneCum });
      }
      if (objectif && !atteint && v >= objectif && net < objectif) atteint = date;
      if (m === annees * 12) fin = { desendettement, epargneCum, rendement, v, date };
    }
    return { epargne, taux, annees, financier, dcaCum, finDca, atteint, fin, points, sansRendement };
  });

  let hoteCourbe = $state<HTMLElement>();
  $effect(() => {
    const c = calcul;
    if (!c || !hoteCourbe) return;
    dessinerCourbe(hoteCourbe, {
      series: [
        { nom: 'Net projeté', couleur: 'var(--chart-1)', points: c.points, aire: true },
        { nom: 'Sans rendement', couleur: 'var(--text-muted)', points: c.sansRendement, pointille: true },
      ],
      formatV: v => fmt(v),
      aide: `Projection du patrimoine net sur ${c.annees} ans`,
    });
  });

  // Au telephone, la carte faisait pres de deux ecrans : repliee sur la
  // phrase qui resume la projection, reglages et courbe a la demande.
  let ouverte = $state(false);
  const repliee = $derived(ecran.telephone && !ouverte);

  const mois = (d: Date | string) => new Date(d).toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' });
  const signe = (v: number) => `${v >= 0 ? '+' : '−'}${fmt(Math.abs(v))}`;
  const aide = $derived(mesure ? `Épargne nouvelle mesurée : ${fmt(mesure.nouvelle.par_mois)} par mois sur six mois — la hausse `
    + `des liquidités plus ce qui en est parti vers les placements (${(mesure.nouvelle.periodes || []).length} périodes entre arrêtés). `
    + `Le DCA, lui, investit l'épargne de précaution au-delà de sa cible — charges × mois du profil — (${fmt(mesure.dca.excedent)}) `
    + `au rythme de vos versements (${fmt(mesure.dca.mensuel)} par mois) : il ne crée pas de patrimoine, il le fait travailler.` : '');
</script>

<div class="card-head">
  <div>
    <h2>Projection</h2>
    <p class="card-sub">Trois moteurs : le remboursement des crédits, l'épargne nouvelle, le rendement. Seul le premier est certain.</p>
  </div>
  <!-- Remet les hypotheses aux valeurs mesurees : sans objet tant qu'elles sont repliees. -->
  {#if !repliee}<button type="button" class="btn btn-secondary btn-sm" id="proj-reinit" onclick={reinitialiser}>Valeurs mesurées</button>{/if}
</div>
{#if repliee}
  {#key masque}
  {#if calcul}<p class="proj-total">En {calcul.fin.date.slice(0, 4)} : <b>{fmt(calcul.fin.v)}</b>{objectif ? (calcul.atteint
    ? ` — objectif de ${fmt(objectif)} atteint en ${mois(calcul.atteint)}`
    : net >= objectif ? '' : ` — objectif de ${fmt(objectif)} non atteint à cet horizon`) : ''}</p>{/if}
  {/key}
{:else}
<div class="proj-reglages">
  <label for="proj-epargne">Épargne nouvelle par mois
    <input type="text" inputmode="decimal" id="proj-epargne" class="ref-input" aria-describedby="proj-epargne-aide"
           placeholder={masque ? 'masqué' : ''} bind:value={champs.epargne} oninput={maj}></label>
  <label for="proj-a-investir">Liquidités à investir en DCA
    <input type="text" inputmode="decimal" id="proj-a-investir" class="ref-input"
           placeholder={masque ? 'masqué' : ''} bind:value={champs.aInvestir} oninput={maj}></label>
  <label for="proj-dca">Rythme mensuel du DCA
    <input type="text" inputmode="decimal" id="proj-dca" class="ref-input"
           placeholder={masque ? 'masqué' : ''} bind:value={champs.dca} oninput={maj}></label>
  <label for="proj-rendement">Rendement du financier (% par an)
    <input type="text" inputmode="decimal" id="proj-rendement" class="ref-input" bind:value={champs.rendement} oninput={maj}></label>
  <label for="proj-horizon">Horizon
    <select id="proj-horizon" class="filter-select" bind:value={champs.horizon} onchange={maj}>
      <option value="5">5 ans</option><option value="10">10 ans</option>
      <option value="15">15 ans</option><option value="20">20 ans</option>
    </select></label>
</div>
<p class="form-aide" id="proj-epargne-aide">{aide}</p>
<div id="proj-courbe" class="courbe-hote" bind:this={hoteCourbe}></div>
<div id="proj-detail" aria-live="polite">
  {#key masque}
  {#if calcul}
    {@const c = calcul}
    <p class="proj-total">En {c.fin.date.slice(0, 4)} : <b>{fmt(c.fin.v)}</b>{objectif ? (c.atteint
      ? ` — objectif de ${fmt(objectif)} atteint en ${mois(c.atteint)}`
      : net >= objectif ? '' : ` — objectif de ${fmt(objectif)} non atteint à cet horizon`) : ''}</p>
    <ul class="proj-moteurs">
      <li><span>Aujourd’hui</span><b>{fmt(net)}</b><em>patrimoine net actuel</em></li>
      <li><span>Désendettement</span><b>{signe(c.fin.desendettement)}</b><em>capital remboursé selon les échéanciers des prêts amortissables — certain{
        (crd?.prets || []).some(x => x.in_fine) ? ' ; un prêt in fine, remboursé d’un bloc sur des actifs, n’en fait pas partie' : ''}</em></li>
      <li><span>Épargne nouvelle</span><b>{signe(c.fin.epargneCum)}</b><em>{fmt(c.epargne)} par mois — l'argent qui entre</em></li>
      <li><span>Rendement</span><b>{signe(c.fin.rendement)}</b><em>{fmtPct(c.taux * 100, Number.isInteger(c.taux * 100) ? 0 : 1)} par an sur le financier ({fmt(c.financier)} aujourd'hui){
        c.dcaCum ? `, renforcé de ${fmt(c.dcaCum)} investis en DCA${c.finDca ? ` jusqu'en ${mois(c.finDca)}` : ''}` : ''} — hypothèse</em></li>
    </ul>
    <p class="proj-note">Liquidités, immobilier et biens restent à leur valeur d’aujourd’hui, sans revalorisation ni
      inflation ; montants avant impôt. La courbe en pointillé montre le net sans aucun rendement.</p>
  {/if}
  {/key}
</div>
{/if}
{#if ecran.telephone}
  <button type="button" class="btn-link mv-plus" aria-expanded={ouverte} onclick={() => ouverte = !ouverte}>{ouverte
    ? 'Réduire' : 'Afficher les hypothèses et la courbe'}</button>
{/if}
