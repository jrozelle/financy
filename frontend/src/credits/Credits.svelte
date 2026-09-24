<script lang="ts">
  /**
   * Credits : les prets et leurs tableaux d'amortissement.
   *
   * Un echeancier dit la dette a toute date : l'onglet en tire la projection
   * du capital restant du jusqu'au dernier remboursement, la mensualite et
   * les interets qui restent a payer, et compare la dette saisie de chaque
   * entite a ce que l'echeancier prevoit — sans jamais la corriger en silence.
   *
   * Premier ecran en Svelte : il reprend le balisage et les classes de
   * l'ancien module (static/modules/tabs/prets.js), si bien que style.css
   * s'applique tel quel.
   */
  import { tick } from 'svelte';
  import { api } from '/static/modules/api.js';
  import { S } from '/static/modules/state.js';
  import { fmt, fmtDate, fmtPct, fmtAxis, parseLocaleNumber, today, sortArr } from '/static/modules/utils.js';
  import { toast, confirmDialog } from '/static/modules/dialogs.js';
  import { dessinerCourbe, type Serie } from '/static/modules/courbe.js';
  import PretCarte from './PretCarte.svelte';
  import EnTeteTri from './EnTeteTri.svelte';
  import type { ApercuImport, Calendrier, Pret, Projection, Resume, AutreDette } from './types';

  const COULEURS = ['var(--nature-immo)', 'var(--nature-liq)', 'var(--nature-biens)', 'var(--nature-fin)'];

  let prets = $state<Pret[]>([]);
  let autres = $state<AutreDette[]>([]);
  let projection = $state<Projection | null>(null);
  let echeancier = $state<Record<string, number> | null>(null);
  let calendrier = $state<Calendrier>({ prochaines: [], annees: [] });
  let titulaire = $state<string | null>(null);
  let entites = $state<{ name: string; debt?: number | null }[]>([]);
  let charge = $state(false);

  const couleur = (id: number) => COULEURS[Math.max(0, prets.findIndex(p => p.id === id)) % COULEURS.length];

  /** Recharge tout, vu par le titulaire courant : ses seuls credits, a sa
   *  part de dette. En famille, les credits se lisent entiers. */
  export async function recharger() {
    const qui = S.syntheseOwner && S.syntheseOwner !== 'Famille' ? S.syntheseOwner : '';
    const q = qui ? `?titulaire=${encodeURIComponent(qui)}` : '';
    try {
      const [res, pj, dettes, cal] = await Promise.all([
        api<Resume>('GET', `/api/prets${q}`, null, { silent: true }),
        api<Projection>('GET', `/api/prets/projection${q}`, null, { silent: true }),
        qui ? Promise.resolve(null) : api<Record<string, number>>('GET', `/api/prets/dettes?date=${today()}`, null, { silent: true }),
        api<Calendrier>('GET', `/api/prets/calendrier${q}`, null, { silent: true }),
      ]);
      titulaire = qui || null;
      entites = [...(S.entities || [])];
      prets = res.prets || [];
      autres = res.autres_dettes || [];
      projection = pj;
      echeancier = dettes;
      calendrier = cal || { prochaines: [], annees: [] };
    } catch { /* message deja affiche par api() */ }
    charge = true;
  }

  // ── Chiffres de tete ───────────────────────────────────────────────────
  const kpi = $derived(prets.length ? {
    crd: prets.reduce((t, p) => t + p.crd, 0),
    mois: prets.reduce((t, p) => t + (p.echeance_du_mois || 0), 0),
    interets: prets.reduce((t, p) => t + p.interets_restants, 0),
    fin: prets.map(p => p.fin).sort().pop() ?? null,
  } : null);
  const totalAutres = $derived(autres.reduce((t, x) => t + x.montant, 0));

  // ── Courbe du restant du ───────────────────────────────────────────────
  let hoteCourbe = $state<HTMLElement>();
  $effect(() => {
    const pj = projection;
    if (!hoteCourbe) return;
    if (!pj?.dates?.length || !prets.length) { hoteCourbe.innerHTML = ''; return; }
    const pts = (vals: number[]) => pj.dates.map((d, i) => ({ date: d, v: vals[i] }));
    const series: Serie[] = [{ nom: 'Total restant dû', couleur: 'var(--primary)', points: pts(pj.total), aire: true }];
    if (pj.prets.length > 1) {
      pj.prets.forEach(p => series.push({ nom: p.libelle, couleur: couleur(p.id), points: pts(p.points), pointille: true }));
    }
    dessinerCourbe(hoteCourbe, {
      series, formatY: fmtAxis, formatV: (v: number) => fmt(v),
      aide: `Capital restant dû : ${fmt(pj.total[0])} aujourd'hui, soldé le ${fmtDate(pj.dates[pj.dates.length - 1])}.`,
    });
  });
  const jalons = $derived(projection ? [...projection.prets].sort((a, b) => a.fin.localeCompare(b.fin)) : []);

  // ── Dette saisie contre echeancier ─────────────────────────────────────
  // Une echeance d'ecart est normale (saisie avant ou apres le prelevement du
  // mois) ; au-dela, on le dit. En vue d'un titulaire, pas de controle : la
  // dette d'une entite se compare en montants entiers, pas a une part.
  const ecarts = $derived(Object.entries(echeancier || {}).flatMap(([nom, prevu]) => {
    const ent = entites.find(e => e.name === nom);
    if (!ent) return [];
    const mensu = prets.filter(p => p.entity === nom).reduce((t, p) => t + (p.mensualite || 0), 0);
    const saisie = ent.debt || 0;
    const ecart = saisie - prevu;
    return [{ nom, saisie, prevu, ecart, ok: Math.abs(ecart) <= Math.max(mensu, 1) }];
  }));

  // ── Actions sur un credit ──────────────────────────────────────────────
  async function rattacher(id: number, entite: string | null) {
    try { await api('PATCH', `/api/prets/${id}`, { entity: entite }); toast('Prêt rattaché', 'success'); await recharger(); }
    catch { /* affiche par api() */ }
  }
  async function changerIra(id: number, mode: 'legale' | 'aucune') {
    try { await api('PATCH', `/api/prets/${id}`, { ira: mode }); await recharger(); } catch { /* idem */ }
  }
  async function supprimer(id: number) {
    if (!await confirmDialog('Supprimer ce prêt ?', 'Son échéancier disparaît ; la dette des arrêtés déjà saisis ne change pas.')) return;
    try { await api('DELETE', `/api/prets/${id}`); await recharger(); } catch { /* idem */ }
  }

  // ── Formulaire « Definir un credit » ───────────────────────────────────
  let formulaireOuvert = $state(false);
  let champLibelle = $state<HTMLInputElement>();
  let boutonDefinir = $state<HTMLButtonElement>();
  let ouvreur: HTMLElement | null = null;
  const vide = { libelle: '', preteur: '', montant: '', taux: '', mois: '', premiere: '',
                 assurance: '', differe: '', type_differe: 'partiel', entite: '' };
  let f = $state({ ...vide });

  /** Depuis le bouton « Ajouter » de l'en-tete ou celui de la carte : on
   *  retient qui l'a ouvert, pour lui rendre le focus. */
  export async function ouvrirFormulaire() {
    if (!formulaireOuvert) ouvreur = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    entites = [...(S.entities || [])];
    formulaireOuvert = true;
    await tick();
    champLibelle?.focus();
  }
  function rendreFocus() {
    const cible = ouvreur?.isConnected ? ouvreur : boutonDefinir;
    ouvreur = null;
    cible?.focus();
  }
  function fermerFormulaire() {
    if (!formulaireOuvert) return;
    formulaireOuvert = false;
    rendreFocus();
  }
  async function enregistrerCredit(e: SubmitEvent) {
    e.preventDefault();
    const n = (s: string) => parseLocaleNumber(s.trim());
    try {
      await api('POST', '/api/prets', {
        libelle: f.libelle.trim(), preteur: f.preteur.trim() || null,
        montant: n(f.montant), taux: n(f.taux), mois: n(f.mois), premiere: f.premiere,
        assurance: f.assurance.trim() ? n(f.assurance) : 0,
        differe: f.differe.trim() ? n(f.differe) : 0,
        type_differe: f.type_differe, entity: f.entite || null,
      });
      toast('Crédit enregistré', 'success');
      f = { ...vide };
      fermerFormulaire();
      await recharger();
    } catch { /* affiche par api() */ }
  }

  // ── Import d'un tableau d'amortissement (apercu, puis enregistrement) ──
  let apercu = $state<ApercuImport | null>(null);
  let fichier: File | null = null;
  let apercuLibelle = $state('');
  let apercuEntite = $state('');
  let champApercu = $state<HTMLInputElement>();

  async function envoyer(fic: File, etape: 'preview' | 'commit', champs: Record<string, string> = {}) {
    const fd = new FormData();
    fd.append('file', fic);
    Object.entries(champs).forEach(([k, v]) => { if (v) fd.append(k, v); });
    const meta = document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]');
    const r = await fetch(`/api/prets/import?step=${etape}`, { method: 'POST', body: fd,
      headers: meta ? { 'X-CSRF-Token': meta.content } : {} });
    const d = await r.json().catch(() => null);
    if (!r.ok) throw new Error(d?.error || `Import refusé (${r.status})`);
    return d;
  }
  async function choisirFichier(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const fic = input.files?.[0];
    input.value = '';
    if (!fic) return;
    ouvreur = null;
    try {
      const { pret } = await envoyer(fic, 'preview') as { pret: ApercuImport };
      fichier = fic;
      entites = [...(S.entities || [])];
      apercu = pret;
      apercuLibelle = pret.libelle;
      apercuEntite = pret.entite_proposee || '';
      await tick();
      champApercu?.focus();
    } catch (err) { toast((err as Error).message, 'error'); }
  }
  function fermerApercu() {
    const avait = apercu !== null;
    apercu = null; fichier = null;
    if (avait) rendreFocus();
  }
  async function enregistrerImport() {
    if (!fichier) return;
    try {
      await envoyer(fichier, 'commit', { libelle: apercuLibelle.trim(), entity: apercuEntite });
      toast('Prêt enregistré', 'success');
      fermerApercu();
      await recharger();
    } catch (err) { toast((err as Error).message, 'error'); }
  }

  // Echap referme le formulaire ou l'apercu ouvert, pas quand une modale ou
  // une confirmation est au premier plan : Echap lui revient.
  function echap(e: KeyboardEvent) {
    if (e.key !== 'Escape') return;
    if (document.getElementById('tab-credits')?.classList.contains('hidden')) return;
    if (document.querySelector('.confirm-overlay, .modal:not(.hidden), .isin-popover:not(.hidden)')) return;
    if (formulaireOuvert) fermerFormulaire();
    else if (apercu) fermerApercu();
  }

  // ── Echeanciers : tris ─────────────────────────────────────────────────
  let triProchaines = $state<{ cle: string | null; sens: number }>({ cle: null, sens: 1 });
  let triAnnees = $state<{ cle: string | null; sens: number }>({ cle: null, sens: 1 });
  const basculer = (t: { cle: string | null; sens: number }, cle: string) =>
    t.cle === cle ? { cle, sens: -t.sens } : { cle, sens: 1 };

  const prochaines = $derived(sortArr(calendrier.prochaines.map(e => ({
    ...e, _charges: e.interets + e.assurance, _total: Math.max(e.capital, 0) + e.interets + e.assurance,
  })), triProchaines.cle, triProchaines.sens));
  const annees = $derived(sortArr(calendrier.annees.map(a => ({ ...a, _charges: a.interets + a.assurance })),
    triAnnees.cle, triAnnees.sens));
</script>

<svelte:window onkeydown={echap} />

<div class="page-header"><h1>Crédits</h1></div>
<div class="credits-kpi" id="credits-kpi">
  {#if kpi}
    <div class="kpi-grid credits-grille">
      <div class="kpi-card"><div class="kpi-label">Restant dû</div><div class="kpi-value">{fmt(kpi.crd)}</div>
        <div class="kpi-sub">{prets.length} crédit{prets.length > 1 ? 's' : ''}</div></div>
      <div class="kpi-card"><div class="kpi-label">Échéances du mois</div><div class="kpi-value">{fmt(kpi.mois)}</div>
        <div class="kpi-sub">assurance comprise</div></div>
      <div class="kpi-card"><div class="kpi-label">Intérêts restants</div><div class="kpi-value">{fmt(kpi.interets)}</div>
        <div class="kpi-sub">et assurance, jusqu’au bout</div></div>
      <div class="kpi-card"><div class="kpi-label">Libre de dettes le</div><div class="kpi-value">{fmtDate(kpi.fin)}</div></div>
    </div>
  {/if}
</div>
{#if autres.length}
  <!-- Les dettes qu'aucun credit n'explique : dites ici, sans quoi la dette
       de la synthese depasse le restant du des credits sans raison visible. -->
  <p class="credits-autres">Hors crédits, {fmt(totalAutres)} de dettes sans échéancier, comptées dans la synthèse :
    {#each autres as x, i}{i ? ', ' : ''}{x.libelle} ({fmt(x.montant)}{x.notes ? ` — ${x.notes}` : ''}){/each}.</p>
{/if}

<div class="card" id="prets-carte">
  <div class="prets-tete">
    <div>
      <h2>Vos crédits</h2>
      <p class="card-sub" id="prets-sous">Chaque crédit porte la dette de l'entité à laquelle il est rattaché.</p>
    </div>
    <div class="prets-actions">
      <button type="button" class="btn btn-secondary btn-sm" id="prets-definir" bind:this={boutonDefinir}
              onclick={ouvrirFormulaire}>Définir un crédit</button>
      <label class="btn btn-secondary btn-sm prets-import-btn">
        Importer un tableau d'amortissement
        <input type="file" id="prets-fichier" accept="application/pdf" hidden onchange={choisirFichier}>
      </label>
    </div>
  </div>

  <form id="prets-formulaire" class="prets-apercu" hidden={!formulaireOuvert} onsubmit={enregistrerCredit}>
    <p><b>Nouveau crédit</b> — l'échéancier se calcule à mensualité constante. Pour un prêt à paliers ou lissé,
      importez plutôt le tableau de la banque.</p>
    <div class="prets-apercu-champs">
      <label for="pf-libelle">Libellé <input type="text" id="pf-libelle" class="ref-input" required maxlength="120"
        placeholder="Prêt auto" bind:value={f.libelle} bind:this={champLibelle}></label>
      <label for="pf-preteur">Prêteur <input type="text" id="pf-preteur" class="ref-input" maxlength="120"
        placeholder="Banque" bind:value={f.preteur}></label>
      <label for="pf-montant">Montant emprunté (€) <input type="text" inputmode="decimal" id="pf-montant" class="ref-input"
        required bind:value={f.montant}></label>
      <label for="pf-taux">Taux annuel (%) <input type="text" inputmode="decimal" id="pf-taux" class="ref-input" required
        placeholder="3,5" bind:value={f.taux}></label>
      <label for="pf-mois">Durée (mois) <input type="text" inputmode="numeric" id="pf-mois" class="ref-input" required
        placeholder="240" bind:value={f.mois}></label>
      <label for="pf-premiere">Première échéance <input type="date" id="pf-premiere" class="ref-input" required
        bind:value={f.premiere}></label>
      <label for="pf-assurance">Assurance / mois (€) <input type="text" inputmode="decimal" id="pf-assurance" class="ref-input"
        placeholder="0" bind:value={f.assurance}></label>
      <label for="pf-differe">Différé (mois) <input type="text" inputmode="numeric" id="pf-differe" class="ref-input"
        placeholder="0" bind:value={f.differe}></label>
      <label for="pf-type-differe">Type de différé <select id="pf-type-differe" class="filter-select" bind:value={f.type_differe}>
        <option value="partiel">Partiel : intérêts payés</option>
        <option value="total">Total : intérêts ajoutés au capital</option></select></label>
      <label for="pf-entite">Dette de l'entité <select id="pf-entite" class="filter-select" bind:value={f.entite}>
        <option value="">Aucune entité</option>
        {#each entites as e (e.name)}<option value={e.name}>{e.name}</option>{/each}</select></label>
      <button type="submit" class="btn btn-primary btn-sm">Enregistrer le crédit</button>
      <button type="button" class="btn btn-secondary btn-sm" id="pf-annuler" onclick={fermerFormulaire}>Annuler</button>
    </div>
  </form>

  {#if apercu}
    <div id="prets-apercu" class="prets-apercu">
      <p><b>{apercu.libelle}</b> · {apercu.preteur}{apercu.emprunteur ? ` · emprunteur ${apercu.emprunteur}` : ''}</p>
      <p class="text-muted">{fmt(apercu.montant)} empruntés{apercu.taux ? ` à ${fmtPct(apercu.taux, 2)}` : ''} ·
        {apercu.echeances} échéances, du {fmtDate(apercu.debut)} au {fmtDate(apercu.fin)}</p>
      <p class="prets-controle">{(apercu.controles || []).join(' · ')}</p>
      {#if apercu.deja}<p class="import-alerte">Ce prêt est déjà enregistré (« {apercu.deja.libelle} »).</p>{/if}
      <div class="prets-apercu-champs">
        <label>Libellé <input type="text" id="prets-libelle" class="ref-input" bind:value={apercuLibelle}
          bind:this={champApercu}></label>
        <label>Dette de l'entité <select id="prets-entite" class="filter-select" bind:value={apercuEntite}>
          <option value="">Aucune entité</option>
          {#each entites as e (e.name)}<option value={e.name}>{e.name}</option>{/each}</select></label>
        <button type="button" class="btn btn-primary btn-sm" id="prets-enregistrer" disabled={!!apercu.deja}
                onclick={enregistrerImport}>Enregistrer le prêt</button>
        <button type="button" class="btn btn-secondary btn-sm" id="prets-annuler" onclick={fermerApercu}>Annuler</button>
      </div>
    </div>
  {/if}

  <div id="prets-courbe" class="courbe-hote" bind:this={hoteCourbe}></div>
  <div id="prets-legende" class="courbe-legende">
    {#if prets.length}
      {#each jalons as p (p.id)}<span><i style:background={couleur(p.id)}></i>{p.libelle} soldé le <b>{fmtDate(p.fin)}</b></span>{/each}
    {/if}
  </div>

  <div id="prets-liste">
    {#if prets.length}
      <div class="prets-liste">
        {#each prets as p (p.id)}
          <PretCarte pret={p} couleur={couleur(p.id)} entites={entites.map(e => e.name)} {titulaire}
                     onEntite={rattacher} onIra={changerIra} onSupprimer={supprimer} />
        {/each}
      </div>
    {:else if charge && titulaire}
      <p class="text-muted prets-vide">Aucun crédit ne concerne {titulaire} : aucune des entités dont {titulaire}
        détient des parts n'est financée à crédit.</p>
    {:else if charge}
      <p class="text-muted prets-vide">Aucun prêt. Importez le tableau d'amortissement de votre banque (PDF Caisse d'Épargne
        ou Arkéa) : la dette de l'entité se projettera d'elle-même.</p>
    {/if}
  </div>

  <div id="prets-ecarts">
    {#if ecarts.length}
      <ul class="prets-ecarts">
        {#each ecarts as e (e.nom)}
          <li class:pret-ecart={!e.ok}><b>{e.nom}</b> : dette saisie {fmt(e.saisie)}, échéancier aujourd'hui {fmt(e.prevu)}
            {#if e.ok}{Math.abs(e.ecart) >= 1 ? ' — une échéance d’écart, normal' : ' — identiques'}
            {:else} — <strong>écart de {fmt(Math.abs(e.ecart))}</strong>, plus d'une mensualité : un prêt manque ou la dette est à revoir{/if}</li>
        {/each}
      </ul>
    {/if}
  </div>
</div>

<div class="credits-bas">
  <div class="card">
    <h2>Prochaines échéances</h2>
    <p class="card-sub">Tous crédits confondus.</p>
    <!-- svelte-ignore a11y_no_noninteractive_tabindex : zone qui defile, atteignable au clavier -->
    <div id="credits-prochaines" class="table-scroll" tabindex="0" role="region" aria-label="Prochaines échéances">
      {#if !prochaines.length}
        {#if charge}<p class="text-muted">Aucune échéance à venir.</p>{/if}
      {:else}
        <table class="data-table credits-table">
          <thead><tr>
            <EnTeteTri cle="date" tri={triProchaines} surTri={c => triProchaines = basculer(triProchaines, c)}>Date</EnTeteTri>
            <EnTeteTri cle="pret" tri={triProchaines} surTri={c => triProchaines = basculer(triProchaines, c)}>Crédit</EnTeteTri>
            <EnTeteTri cle="capital" num tri={triProchaines} surTri={c => triProchaines = basculer(triProchaines, c)}>Capital</EnTeteTri>
            <EnTeteTri cle="_charges" num tri={triProchaines} surTri={c => triProchaines = basculer(triProchaines, c)}>Intérêts</EnTeteTri>
            <EnTeteTri cle="_total" num tri={triProchaines} surTri={c => triProchaines = basculer(triProchaines, c)}>Total</EnTeteTri>
          </tr></thead>
          <tbody>
            {#each prochaines as e (`${e.pret_id}-${e.rang}`)}
              <tr><td>{fmtDate(e.date)}</td>
                <td><i class="pastille" style:background={couleur(e.pret_id)}></i>{e.pret || ''}
                  <span class="cr-detail">{e.capital < 0 ? `différé (+${fmt(-e.capital)})` : `capital ${fmt(e.capital)}`} · intérêts {fmt(e._charges)}</span></td>
                <td class="num">{#if e.capital < 0}<span class="text-muted">différé (+{fmt(-e.capital)})</span>{:else}{fmt(e.capital)}{/if}</td>
                <td class="num">{fmt(e._charges)}</td>
                <td class="num"><b>{fmt(e._total)}</b></td></tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  </div>
  <div class="card">
    <h2>Par année</h2>
    <p class="card-sub">Ce que vous rembourserez, et ce qu'il restera dû au 31 décembre.</p>
    <!-- svelte-ignore a11y_no_noninteractive_tabindex : zone qui defile, atteignable au clavier -->
    <div id="credits-annees" class="table-scroll" tabindex="0" role="region" aria-label="Remboursements par année">
      {#if !annees.length}
        {#if charge}<p class="text-muted">Aucun remboursement à venir.</p>{/if}
      {:else}
        <table class="data-table credits-table">
          <thead><tr>
            <EnTeteTri cle="annee" tri={triAnnees} surTri={c => triAnnees = basculer(triAnnees, c)}>Année</EnTeteTri>
            <EnTeteTri cle="capital" num tri={triAnnees} surTri={c => triAnnees = basculer(triAnnees, c)}>Capital remboursé</EnTeteTri>
            <EnTeteTri cle="_charges" num tri={triAnnees} surTri={c => triAnnees = basculer(triAnnees, c)}>Intérêts et assurance</EnTeteTri>
            <EnTeteTri cle="crd_fin" num tri={triAnnees} surTri={c => triAnnees = basculer(triAnnees, c)}>Restant dû au 31/12</EnTeteTri>
          </tr></thead>
          <tbody>
            {#each annees as a (a.annee)}
              <tr><td>{a.annee}</td>
                <td class="num">{fmt(a.capital)}<span class="cr-detail">intérêts {fmt(a._charges)}</span></td>
                <td class="num">{fmt(a._charges)}</td>
                <td class="num"><b>{fmt(a.crd_fin)}</b></td></tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  </div>
</div>
