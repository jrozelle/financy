<script lang="ts" module>
  // Cours de l'ETF de comparaison, gardes pour la periode affichee : changer
  // de compte dans la liste ne doit pas les redemander. Remplie au RETOUR de
  // la requete : une reponse lente ne s'inscrit pas sous une autre periode.
  const benchs = new Map<string, Bench | null>();
  interface Bench { name?: string; devise?: string; points?: { date: string; price: number }[] }
</script>

<script lang="ts">
  /**
   * Onglet Performance : le rendement de chaque compte (ou enveloppe), TRI en
   * tete — ce que l'argent a rapporte selon la date des versements — et TWR
   * en second plan, comparable a un indice. La courbe met les placements
   * exposes aux marches face a un ETF World, versements neutralises.
   *
   * Porte de static/modules/tabs/performance.js, balisage a l'identique.
   */
  import { api } from '/static/modules/api.js';
  import { dessinerCourbe } from '/static/modules/courbe.js';
  import { fmt, esc, fmtDate, fmtPct } from '/static/modules/utils.js';
  import type { Groupe, Perf } from './types';

  let { owner = null, masque = false, visite = 0 }: {
    owner?: string | null; masque?: boolean; visite?: number;
  } = $props();

  // ── Donnees : rechargees a chaque visite, a chaque changement de titulaire
  // ou de maille ; le compte isole se perd alors, le reste de l'etat non.
  let d = $state<Perf | null>(null);
  let charge = $state(false);
  let groupe = $state<'account' | 'envelope'>('account');
  let focus = $state<string | null>(null);
  let jeton = 0;
  $effect(() => {
    void visite;
    const qs = new URLSearchParams({ group: groupe });
    if (owner) qs.set('owner', owner);
    const j = ++jeton;
    api<Perf>('GET', `/api/performance?${qs}`).then(r => { if (j === jeton) { d = r; focus = null; charge = true; } })
      .catch(() => {});
  });

  // ── Tri : celui de l'API (valeur decroissante) par defaut ; decroissant au
  // premier clic sur un chiffre, croissant sur un texte.
  let tri = $state<{ col: 'name' | 'rend' | 'value'; dir: 'asc' | 'desc' }>({ col: 'value', dir: 'desc' });
  const SENS0 = { name: 'asc', rend: 'desc', value: 'desc' } as const;
  const trier = (col: 'name' | 'rend' | 'value') => {
    tri = tri.col === col ? { col, dir: tri.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: SENS0[col] };
  };
  const CLES = {
    name: (g: Groupe) => `${g.envelope || g.label || ''} ${g.account_label || ''}`.trim(),
    rend: (g: Groupe) => rend(g)?.v,
    value: (g: Groupe) => g.value,
  };

  /** Nombre brut, non masque a dessein : compteurs, sans montant. */
  const n = (v: number | null | undefined, dec = 0) => v == null ? '—'
    : new Intl.NumberFormat('fr-FR', { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(v);
  /** Rendement en fraction (0,079) ecrit en pourcent signe (+7,90 %). */
  const pct = (v: number | null | undefined, dec = 2) => v == null ? '—' : fmtPct(v * 100, dec, true);
  const sign = (v: number | null | undefined) => v == null ? '' : (v >= 0 ? 'positive' : 'negative');
  function duree(days: number | null | undefined) {
    if (days == null) return '—';
    if (days < 62) return `${days} j`;
    const m = Math.round(days / 30.44);
    return m < 24 ? `${m} mois` : `${n(days / 365.25, 1)} ans`;
  }
  /** Le TRI, annuel au-dela de six mois d'historique ; en deca, le rendement
   *  de la periode, dit comme tel. */
  function rend(g: Groupe | null | undefined) {
    if (g?.tri != null) return { v: g.tri, sub: 'par an' };
    if (g?.tri_periode != null) return { v: g.tri_periode, sub: `sur ${duree(g.tri_jours)}` };
    return null;
  }
  /** Le TWR ne s'affiche a cote du TRI que s'il en differe. */
  function twrDiffere(g: Groupe) {
    const r = rend(g);
    if (!r || g.twr == null) return false;
    const t = g.tri != null ? (g.annualisable ? g.twr_annualise : null) : g.twr;
    return t != null && Math.abs(t - r.v) >= 0.0005;
  }
  const twr = (g: Groupe) => pct(g.annualisable ? g.twr_annualise : g.twr);

  // Comptes courants, objets, capitaux negatifs et comptes clos sont ecartes
  // de la liste ; le decompte et le detail sont dans le panneau « hors calcul ».
  const CACHES = new Set(['non_measurable', 'negative', 'closed']);
  const LIBELLES: Record<string, string> = { insufficient: 'historique insuffisant', negative: 'capital négatif',
    non_measurable: 'aucun rendement à mesurer', closed: 'compte clos' };
  const visibles = $derived((d?.groups || []).filter(g => !CACHES.has(g.status)));
  const lignes = $derived.by(() => {
    const cle = CLES[tri.col], sens = tri.dir === 'asc' ? 1 : -1;
    // Une valeur absente reste en bas dans les deux sens.
    return visibles.slice().sort((a, b) => {
      const x = cle(a), y = cle(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return typeof x === 'string' ? sens * x.localeCompare(y as string, 'fr') : sens * ((x as number) - (y as number));
    });
  });
  const alertes = $derived((d?.groups || []).flatMap(g => (g.price_warnings || []).map(a => [g.label, a] as const)));
  const exclus = $derived((d?.groups || []).filter(g => g.status !== 'ok'));
  const courant = $derived(focus ? visibles.find(g => g.key === focus) || d?.global : d?.global);
  const vide = $derived(!d || d.insufficient || !d.groups?.length);

  let exclusOuverts = $state(false);
  let panneau = $state<HTMLElement>();
  async function basculerExclus() {
    exclusOuverts = !exclusOuverts;
    await Promise.resolve();
    if (exclusOuverts) panneau?.scrollIntoView({ block: 'nearest' });
  }
  let suspectsOuverts = $state(new Set<string>());
  const basculerSuspects = (k: string) => {
    const s = new Set(suspectsOuverts); s.has(k) ? s.delete(k) : s.add(k); suspectsOuverts = s;
  };
  const choisir = (k: string) => { focus = focus === k ? null : k; };

  /** Motif d'une alerte de cours, a la francaise : cours par `fmt` (mode
   *  discret compris), virgule decimale, dates `fmtDate`. HTML echappe. */
  const motif = (reason: string) => {
    const nb = (x: string) => fmt(parseFloat(x), 2);
    return esc(reason || '')
      .replace(/cours du jour retenu \((\d+(?:\.\d+)?)\)/, (_, x) => `cours du jour retenu (${nb(x)})`)
      .replace(/cours (\d+(?:\.\d+)?) contre (\d+(?:\.\d+)?) enregistré/, (_, x, y) => `cours ${nb(x)} contre ${nb(y)} enregistré`)
      .replace(/(\d+)\.(\d+)(\s| )%/g, '$1,$2 %')
      .replace(/\b(\d{4}-\d{2}-\d{2})\b/g, (_, dd) => fmtDate(dd));
  };
  const idDetail = (k: string) => `perf-susp-${esc(k).replace(/[^\w-]/g, '_')}`;

  // ── Courbe face a l'ETF World ─────────────────────────────────────────
  interface Legende { nom: string; fin: string; comp?: { moi: string; etf: string; nomEtf: string; ecart: string;
    periode: string; devise?: string }; horsMarche?: string }
  let hote = $state<HTMLElement>();
  let legende = $state<Legende | null>(null);
  let rendu = 0;
  $effect(() => {
    void masque;
    if (!hote || !d || vide) return;
    tracer(d, focus);
  });
  async function tracer(dd: Perf, f: string | null) {
    // Sans compte choisi, la comparaison porte sur la part exposee aux
    // marches : l'epargne de precaution face a un indice actions faisait
    // passer la prudence pour une contre-performance.
    const g = f ? dd.groups.find(x => x.key === f) : (dd.marche || dd.global);
    const serie = (g?.serie || []).filter(p => p.index != null) as { date: string; index: number }[];
    // dessinerCourbe reecrit l'hote : le message s'y ecrit de meme, hors Svelte.
    if (serie.length < 2) {
      ++rendu;
      hote!.innerHTML = '<p class="courbe-vide">Deux arrêtés valorisés au moins sont nécessaires pour une courbe.</p>';
      legende = null;
      return;
    }
    const debut = serie[0].date, fin = serie[serie.length - 1].date;
    const j = ++rendu, cle = debut + fin;
    if (!benchs.has(cle)) {
      let b: Bench | null = null;
      try { b = await api<Bench>('GET', `/api/benchmark?debut=${debut}&fin=${fin}`, null, { silent: true }); }
      catch { /* pas de comparaison, la courbe seule */ }
      benchs.set(cle, b);
    }
    if (j !== rendu || !hote) return;
    const etf = benchs.get(cle);
    const cours = (etf?.points || []).filter(c => c.price > 0);
    // Le cours d'un arrete : le dernier connu a ce jour. Une seule liste
    // d'abscisses pour les deux series.
    const prixA = (date: string) => { let p: number | null = null; for (const c of cours) { if (c.date <= date) p = c.price; else break; } return p; };
    // Pour le PREMIER point seulement, un cours qui suit l'arrete de quatre
    // jours au plus sert ; la legende nomme alors sa date.
    const JOURS = 864e5, TOLERANCE = 4;
    const premierApres = (date: string) => cours.find(c => c.date > date && (Date.parse(c.date) - Date.parse(date)) / JOURS <= TOLERANCE);
    let communs = serie.filter(p => prixA(p.date) != null);
    let recale: { arrete: string; cours: { date: string; price: number } } | null = null;
    const avant = serie.filter(p => prixA(p.date) == null);
    const proche = avant.length ? premierApres(avant[avant.length - 1].date) : null;
    if (proche) { recale = { arrete: avant[avant.length - 1].date, cours: proche }; communs = [avant[avant.length - 1], ...communs]; }
    const prixDe = (date: string) => (recale && date === recale.arrete ? recale.cours.price : prixA(date)!);
    let bench: { date: string; v: number }[] | null = null;
    let comp: { debut: string; fin: string; moi: number; etf: number } | null = null;
    if (communs.length >= 2) {
      const a = communs[0], p0 = prixDe(a.date);
      bench = communs.map(p => ({ date: p.date, v: a.index * prixDe(p.date) / p0 }));
      const z = communs[communs.length - 1];
      comp = { debut: a.date, fin: z.date, moi: z.index / a.index - 1, etf: prixDe(z.date) / p0 - 1 };
    }
    const nom = f ? g!.label : (dd.marche ? 'Vos placements exposés aux marchés' : 'Vos placements');
    const nomEtf = etf?.name || 'ETF World';
    dessinerCourbe(hote, {
      series: [
        { nom, couleur: 'var(--primary)', points: serie.map(p => ({ date: p.date, v: p.index })), aire: true },
        ...(bench ? [{ nom: nomEtf, couleur: 'var(--text-muted)', points: bench, pointille: true }] : []),
      ],
      formatY: v => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(v),
      formatV: v => pct(v / 100 - 1),
      aide: `${nom}, base 100 au ${fmtDate(debut)} : ${pct(serie[serie.length - 1].index / 100 - 1)} au ${fmtDate(fin)}.`,
    });
    const horsMarche = !f && dd.marche?.exclus
      ? `Hors ${dd.marche.exclus} compte${dd.marche.exclus > 1 ? 's' : ''} sans risque de marché — livrets, comptes, fonds euros — pour ${fmt(dd.marche.exclus_valeur)}.` : undefined;
    if (!comp) { legende = { nom, fin: pct(serie[serie.length - 1].index / 100 - 1) }; return; }
    const ecart = (comp.moi - comp.etf) * 100;
    const pts = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(Math.abs(ecart));
    legende = { nom, fin: '', horsMarche, comp: { moi: pct(comp.moi), etf: pct(comp.etf), nomEtf,
      ecart: Math.abs(ecart) < 0.05 ? 'au niveau de l’ETF' : `${pts} point${Math.abs(ecart) >= 2 ? 's' : ''} ${ecart > 0 ? 'de mieux' : 'de moins'}`,
      periode: `du ${fmtDate(comp.debut)} au ${fmtDate(comp.fin)}${comp.debut !== debut ? ' — les cours de l’ETF commencent là' : ''}${
        recale ? ` (cours de l’ETF du ${fmtDate(recale.cours.date)} pour l’arrêté du ${fmtDate(recale.arrete)})` : ''}`,
      devise: etf?.devise && etf.devise !== 'EUR' ? etf.devise : undefined } };
  }
</script>

<div id="perf-empty" class="empty-state" class:hidden={!charge || !vide}>
  <p>Deux arrêtés au minimum sont nécessaires pour mesurer une performance.</p>
  <p class="text-muted">Ajoutez des arrêtés de positions, et des flux pour distinguer
  les versements du rendement.</p>
</div>
<div id="perf-body" class:hidden={charge && vide}>
  {#if d && !vide}
  {@const g = courant}
  {#key masque}
  <div class="kpi-grid" id="perf-kpi">
    {#if g}
      {@const comptes = g.accounts || (d.groups || []).filter(x => x.status === 'ok').length}
      {@const r = rend(g)}
      {@render tuile('', `Valeur au ${fmtDate(d.date)}`, fmt(g.value),
        focus ? g.label : `${comptes} compte${comptes > 1 ? 's' : ''} mesuré${comptes > 1 ? 's' : ''}`)}
      {@render tuile('kpi-gross', 'Rendement de votre argent', r ? pct(r.v) : '—',
        r ? `${r.sub} · selon la date de vos versements` : 'historique insuffisant', sign(r?.v))}
      <!-- Le TWR ne juge que le placement, versements neutralises : la mesure a
           comparer a un indice, ou d'un contrat a l'autre. Second plan. -->
      {@render tuile('kpi-mobilizable', 'Rendement hors versements (TWR)', twr(g),
        `${g.annualisable ? 'par an' : `sur ${duree(g.days)}`} · comparable à un indice`,
        sign(g.annualisable ? g.twr_annualise : g.twr))}
      {@render tuile('kpi-debt', 'Apports nets', fmt(g.flux_net),
        `du ${fmtDate(d.first_date)} au ${fmtDate(d.date)} — ${g.flux_count} mouvement${g.flux_count > 1 ? 's' : ''}, hors dividendes`)}
    {/if}
  </div>
  <div id="perf-controls">
    <div class="seg" role="group" aria-label="Maille d'agrégation">
      <button type="button" class="seg-btn" class:is-on={groupe === 'account'} data-group="account"
        aria-pressed={groupe === 'account'} aria-describedby="perf-maille-aide" onclick={() => groupe = 'account'}>Par compte</button>
      <button type="button" class="seg-btn" class:is-on={groupe === 'envelope'} data-group="envelope"
        aria-pressed={groupe === 'envelope'} aria-describedby="perf-maille-aide" onclick={() => groupe = 'envelope'}>Par enveloppe</button>
    </div>
    {#if focus}<button type="button" class="btn btn-sm" id="perf-reset" onclick={() => focus = null}>↩ Tout afficher</button>{/if}
    <span class="perf-meta">{d.dates.length} arrêtés · {fmtDate(d.first_date)} → {fmtDate(d.date)}{#if d.excluded?.length || alertes.length}{' · '}<button
      type="button" class="perf-excl-toggle" id="perf-excl" aria-expanded={exclusOuverts} aria-controls="perf-excl-panel"
      onclick={basculerExclus}>{d.excluded.length} hors calcul{alertes.length ? ` · ${alertes.length} cours à vérifier` : ''} {exclusOuverts ? '▴' : '▾'}</button>{/if}</span>
    <!-- Deplie juste sous son bouton ; replie, il existe vide et masque, pour
         que `aria-controls` designe toujours un element. -->
    {#if alertes.length || exclus.length}
      {#if !exclusOuverts}
        <div class="card perf-excl-panel" id="perf-excl-panel" hidden></div>
      {:else}
        {@const nClos = exclus.filter(x => x.status === 'closed').length}
        <div class="card perf-excl-panel" id="perf-excl-panel" style="flex-basis:100%" bind:this={panneau}>
          {#if alertes.length}
            <div class="perf-excluded">
              <div class="perf-excluded-head">Valorisations à vérifier — le cours du jour et la valeur
                enregistrée divergent ; le motif dit laquelle le modèle a retenue</div>
              {#each alertes as [lbl, a], i (i)}
                <div class="perf-excluded-row">
                  <span>{a.name || a.isin}<span class="perf-sub">{lbl}</span></span>
                  <span class="perf-excl-why">{@html motif(a.reason)}</span>
                  <span class="num"></span>
                </div>
              {/each}
            </div>
          {/if}
          {#if exclus.length}
            <div class="perf-excluded">
              <div class="perf-excluded-head">Hors calcul — {exclus.length} compte{exclus.length > 1 ? 's' : ''}
                sans rendement mesurable{nClos ? `, dont ${nClos} clos qui ne figure${nClos > 1 ? 'nt' : ''} plus dans la synthèse` : ''}</div>
              {#each exclus as x (x.key)}
                {@const sous = [x.establishment, x.owner].filter(Boolean).join(' · ')}
                <div class="perf-excluded-row">
                  <span>{x.envelope || x.label}{x.account_label ? ` ${x.account_label}` : ''}{#if sous}<span class="perf-sub">{sous}</span>{/if}</span>
                  <span class="perf-excl-why">{x.reason || LIBELLES[x.status] || x.status}{x.status === 'closed' && x.last_date
                    ? ` · dernière valeur le ${fmtDate(x.last_date)}` : ''}</span>
                  <span class="num">{fmt(x.value)}</span>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    {/if}
    <p class="form-aide perf-maille-aide" id="perf-maille-aide">{groupe === 'account'
      ? 'Un compte : une enveloppe chez un établissement, pour un titulaire. Chaque contrat a son propre rendement.'
      : 'Tous les contrats d’une même enveloppe fusionnés, titulaires et établissements confondus. Un écart avec la vue par compte signale une enveloppe qui agrège des contrats sans rapport.'}</p>
  </div>
  {/key}
  {/if}
  <div class="card">
    <h2>Vos placements face au marché</h2>
    <p class="card-sub">Part exposée aux marchés, base 100 au premier arrêté, versements neutralisés (TWR). Choisissez un compte dans la liste pour le voir seul.</p>
    <div id="perf-courbe" class="courbe-hote" bind:this={hote}></div>
    <div id="perf-legende" class="courbe-legende" aria-live="polite">
      {#if legende}
        {#if !legende.comp}
          <span><i style="background:var(--primary)"></i>{legende.nom} <b>{legende.fin}</b></span>
          <span class="courbe-note">Aucun ETF World dans l'historique des cours sur cette période : la comparaison apparaîtra avec lui.</span>
        {:else}
          <span><i style="background:var(--primary)"></i>{legende.nom} <b>{legende.comp.moi}</b></span>
          <span><i style="background:var(--text-muted)"></i>{legende.comp.nomEtf} <b>{legende.comp.etf}</b></span>
          <span class="courbe-note">{legende.comp.ecart}
            {legende.comp.periode}</span>
          {#if legende.comp.devise}<span class="courbe-note">L’ETF est coté en {legende.comp.devise} : l’écart inclut l’effet du change.</span>{/if}
          {#if legende.horsMarche}<span class="courbe-note">{legende.horsMarche}</span>{/if}
        {/if}
      {/if}
    </div>
  </div>
  <!-- Liste en grille plutot qu'un tableau : sept colonnes de chiffres se
       lisent mal, et la barre donne l'ordre de grandeur avant le nombre. -->
  <div class="card" id="perf-list">
    {#if d && !vide}
    {#key masque}
    {@const span = Math.max(0.02, ...lignes.map(x => Math.abs(rend(x)?.v || 0)))}
    {@const total = lignes.filter(x => x.status === 'ok').length}
    {@const gl = d.global}
    <div class="perf-head">
      {@render th('name', groupe === 'account' ? 'Compte' : 'Enveloppe')}
      <span class="perf-axis"><i>−</i><i>0</i><i>+</i></span>
      {@render th('rend', 'Rendement', 'ta-r')}{@render th('value', 'Valeur', 'ta-r')}
    </div>
    {#each lignes as x (x.key)}
      {@const r = rend(x)}
      {@const w = r == null ? 0 : Math.abs(r.v) / span * 50}
      {@const neg = (r?.v || 0) < 0}
      {@const sub = [x.establishment, x.owner].filter(Boolean).join(' · ') || (x.categories || []).join(', ')}
      {@const insuffisant = x.status === 'insufficient'}
      {@const suspects = x.suspect_periods || []}
      {@const ouvert = suspectsOuverts.has(x.key)}
      {@const drapeaux = insuffisant || x.price_warnings?.length || suspects.length}
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <div class="perf-item" class:is-focus={focus === x.key} data-key={x.key} tabindex="0" role="button" aria-pressed={focus === x.key}
           onclick={() => choisir(x.key)} onkeydown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choisir(x.key); } }}>
        <div class="perf-name">
          <span class="perf-title">{x.envelope || x.label}{#if x.account_label}{' '}<span class="perf-account">{x.account_label}</span>{/if}</span>
          {#if sub}<span class="perf-sub">{sub}</span>{/if}
        </div>
        <div class="perf-bar" aria-hidden="true">
          <span class="perf-bar-fill {neg ? 'neg' : 'pos'}" style="width:{w.toFixed(1)}%;{neg ? 'right' : 'left'}:50%"></span>
        </div>
        <div class="perf-num {sign(r?.v)}">{r ? pct(r.v) : '—'}
          <span class="perf-num-sub">{r ? `${r.sub}${twrDiffere(x) ? ` · TWR ${twr(x)}` : ''}`
            : `${x.dates_count} arrêté${x.dates_count > 1 ? 's' : ''}`}</span>
        </div>
        <!-- Un seul badge de statut par ligne ; une TWR negative est un
             resultat normal, rien ne la signale. -->
        <div class="perf-val">{fmt(x.value)}
          <span class="perf-num-sub">{#if drapeaux}{#if insuffisant}<span class="badge badge-blk">historique insuffisant</span>{/if}{#if x.price_warnings?.length}{' '}<span
            class="badge badge-30">cours à vérifier</span>{/if}{#if suspects.length}{' '}<span class="badge badge-30">écart inexpliqué</span>{/if}{:else if x.flux_count}{x.flux_count} flux{/if}</span>
        </div>
      </div>
      <!-- Le motif et la liste des ecarts s'affichent sous la ligne, pas dans
           une infobulle : ils conditionnent la lecture du rendement. -->
      {#if insuffisant || suspects.length}
        <div class="perf-detail">
          {#if insuffisant}<span>Il faut deux valorisations successives pour mesurer un rendement. Hors du total.</span>{/if}
          {#if suspects.length}
            <button type="button" class="perf-excl-toggle" data-suspects={x.key} aria-expanded={ouvert} aria-controls={idDetail(x.key)}
                    onclick={() => basculerSuspects(x.key)}>{suspects.length} période{suspects.length > 1 ? 's' : ''} à variation inexpliquée {ouvert ? '▴' : '▾'}</button>
            <ul class="perf-detail-list" id={idDetail(x.key)} hidden={!ouvert}>
              {#each suspects as s, i (i)}
                <li>{fmtDate(s.from)} → {fmtDate(s.to)} : {pct(s.change)} inexpliqué ({s.delta >= 0 ? '+' : '−'}{fmt(Math.abs(s.delta))} de variation, {s.flux
                  ? fmt(s.flux) + ' de flux déclaré' : 'aucun flux déclaré'})</li>
              {/each}
            </ul>
          {/if}
        </div>
      {/if}
    {/each}
    {#if gl && !focus && total > 1}
      {@const r = rend(gl)}
      <div class="perf-item is-total">
        <div class="perf-name"><span class="perf-title">Ensemble mesurable</span>
          <span class="perf-sub">{(gl.groups || []).length} {groupe === 'account' ? 'compte' : 'enveloppe'}{(gl.groups || []).length > 1 ? 's' : ''}</span></div>
        <div class="perf-bar"></div>
        <div class="perf-num {sign(r?.v)}">{r ? pct(r.v) : '—'}
          <span class="perf-num-sub">{r ? r.sub : ''}{twrDiffere(gl) ? ` · TWR ${twr(gl)}` : ''}</span></div>
        <div class="perf-val">{fmt(gl.value)}</div>
      </div>
    {/if}
    <p class="perf-note">Les pourcentages sont des rendements <strong>cumulés sur la
    période</strong> ; « par an » signale un équivalent annualisé, affiché à partir de
    {d.min_days_annualise} jours d'historique seulement — extrapoler quelques semaines
    à l'année ne renseigne sur rien. Cliquez une ligne pour l'isoler, un en-tête pour
    trier.</p>
    {/key}
    {/if}
  </div>
</div>

{#snippet tuile(variante: string, k: string, v: string, s: string, cl = '')}
  <div class="kpi-card {variante}">
    <div class="kpi-label">{k}</div>
    <div class="kpi-value {cl}">{v}</div>
    <div class="kpi-sub">{s}</div>
  </div>
{/snippet}

{#snippet th(col: 'name' | 'rend' | 'value', texte: string, cls = '')}
  {@const actif = tri.col === col}
  <!-- `aria-sort` n'existe que sur un en-tete de tableau : ici une liste, le
       bouton dit son etat dans son nom. -->
  <span class="perf-th {cls}" class:is-sorted={actif} data-sort={col} role="button" tabindex="0"
        aria-label="Trier par {texte.toLowerCase()}{actif ? `, trié par ordre ${tri.dir === 'asc' ? 'croissant' : 'décroissant'}` : ''}"
        onclick={() => trier(col)} onkeydown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); trier(col); } }}
    >{texte}<i class="perf-caret" aria-hidden="true">{actif ? (tri.dir === 'asc' ? '▲' : '▼') : ''}</i></span>
{/snippet}
