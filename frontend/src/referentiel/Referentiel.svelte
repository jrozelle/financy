<script lang="ts">
  /**
   * Referentiel (fenetre des Reglages) : titulaires, types d'entites, modes
   * de valorisation, types de flux, categories et leur part mobilisable,
   * enveloppes et leur liquidite, alertes de seuil. Les modifications restent
   * en cours jusqu'a l'enregistrement ; un renommage de categorie ou
   * d'enveloppe part avec lui, et le serveur le propage aux positions et aux
   * flux dans la meme transaction.
   *
   * Porte de static/modules/tabs/referentiel.js, balisage a l'identique.
   */
  import { api, buildSelects, refreshEntitySelect } from '/static/modules/api.js';
  import { esc, parseLocaleNumber } from '/static/modules/utils.js';
  import { confirmDialog, toast } from '/static/modules/dialogs.js';
  import { S } from '/static/modules/state.js';
  import { reloadAll } from '/static/modules/main.js';
  import { loadUserAlerts, saveUserAlerts, type Alerte } from '/static/modules/alerts.js';

  interface Ref {
    owners: string[]; categories: string[]; category_mobilizable: Record<string, number>;
    envelope_meta: Record<string, { liquidity: string; friction: string }>;
    entity_types: string[]; valuation_modes: string[]; flux_types: string[];
  }

  let { masque = false, visite = 0 }: { masque?: boolean; visite?: number } = $props();

  let ref = $state<Ref | null>(null);
  let alertes = $state<Alerte[]>([]);
  $effect(() => {
    void visite;
    api<Ref>('GET', '/api/referential').then(r => { ref = r; alertes = loadUserAlerts().map(a => ({ ...a })); }).catch(() => {});
  });
  const liquidites = () => S.config?.liquidity_order || ['J0–J1', 'J2–J7', 'J8–J30', '30J+', 'Bloqué'];
  const categoriesConfig = () => S.config?.categories || [];

  /** Positions et flux qui portent cette valeur, TOUTES dates confondues. */
  async function usage(champ: string, valeur: string) {
    try { return await api<{ positions: number; flux: number }>('GET', `/api/referential/usage?champ=${champ}&valeur=${encodeURIComponent(valeur)}`, null, { silent: true }); }
    catch { return { positions: 0, flux: 0 }; }
  }
  const emplois = (u: { positions: number; flux: number }) =>
    [u.positions ? `${u.positions} position(s)` : '', u.flux ? `${u.flux} flux` : ''].filter(Boolean).join(' et ');

  // Renommages en attente : a → b puis b → c ne font qu'un renommage a → c.
  let renommages: { champ: string; ancien: string; nouveau: string }[] = [];
  function noterRenommage(champ: string, ancien: string, nouveau: string) {
    const deja = renommages.find(r => r.champ === champ && r.nouveau === ancien);
    if (deja) deja.nouveau = nouveau; else renommages.push({ champ, ancien, nouveau });
    renommages = renommages.filter(r => r.ancien !== r.nouveau);
  }

  // ── Titulaires et listes simples ───────────────────────────────────────
  let nouveaux = $state<Record<string, string>>({});
  async function supprimerTitulaire(i: number) {
    const owner = ref!.owners[i];
    const u = await usage('owner', owner);
    if ((u.positions || u.flux) && !await confirmDialog('Supprimer le titulaire ?',
      `<strong>${esc(owner)}</strong> est référencé(e) dans ${emplois(u)}.<br>Ces données ne seront pas supprimées, mais ce titulaire n'apparaîtra plus dans les filtres.`,
      { confirmText: 'Supprimer' })) return;
    ref!.owners.splice(i, 1);
  }
  function ajouter(cle: 'owners' | 'entity_types' | 'valuation_modes' | 'flux_types') {
    const v = (nouveaux[cle] || '').trim();
    if (!v || ref![cle].includes(v)) return;
    ref![cle].push(v);
    nouveaux[cle] = '';
  }

  // ── Categories ─────────────────────────────────────────────────────────
  let nouvelleCat = $state({ nom: '', mob: '80' });
  function renommerCategorie(i: number, champ: HTMLInputElement) {
    const ancien = ref!.categories[i], nouveau = champ.value.trim();
    if (!nouveau || ancien === nouveau) return;
    if (ref!.categories.includes(nouveau)) {
      toast(`« ${nouveau} » existe déjà : deux catégories ne fusionnent pas par renommage`, 'error');
      champ.value = ancien;
      return;
    }
    ref!.categories[i] = nouveau;
    ref!.category_mobilizable[nouveau] = ref!.category_mobilizable[ancien] ?? 0.8;
    delete ref!.category_mobilizable[ancien];
    noterRenommage('category', ancien, nouveau);
  }
  async function supprimerCategorie(i: number) {
    const cat = ref!.categories[i];
    const u = await usage('category', cat);
    if ((u.positions || u.flux) && !await confirmDialog(`Supprimer la catégorie "${cat}" ?`,
      `Elle est utilisée dans ${emplois(u)}.<br>Ces données ne seront pas supprimées, mais la catégorie n'apparaîtra plus dans les filtres.`,
      { confirmText: 'Supprimer quand même' })) return;
    ref!.categories.splice(i, 1);
    delete ref!.category_mobilizable[cat];
  }
  function ajouterCategorie() {
    const nom = nouvelleCat.nom.trim(), mob = parseLocaleNumber(nouvelleCat.mob) / 100;
    if (!nom) return;
    ref!.categories.push(nom);
    ref!.category_mobilizable[nom] = isNaN(mob) ? 0.8 : mob;
    nouvelleCat = { nom: '', mob: '80' };
  }

  // ── Enveloppes ─────────────────────────────────────────────────────────
  let nouvelleEnv = $state({ nom: '', liq: liquidites()[0], friction: '' });
  /** Le renomme garde sa place : l'objet est reconstruit dans l'ordre. */
  function renommerEnveloppe(ancien: string, champ: HTMLInputElement) {
    const nouveau = champ.value.trim();
    if (!nouveau || nouveau === ancien) return;
    if (ref!.envelope_meta[nouveau]) {
      toast(`« ${nouveau} » existe déjà : deux enveloppes ne fusionnent pas par renommage`, 'error');
      champ.value = ancien;
      return;
    }
    noterRenommage('envelope', ancien, nouveau);
    ref!.envelope_meta = Object.fromEntries(Object.entries(ref!.envelope_meta).map(([k, v]) => [k === ancien ? nouveau : k, v]));
  }
  async function supprimerEnveloppe(env: string) {
    const u = await usage('envelope', env);
    if ((u.positions || u.flux) && !await confirmDialog(`Supprimer l'enveloppe "${env}" ?`,
      `Elle est utilisée dans ${emplois(u)}.<br>Ces données ne seront pas supprimées, mais l'enveloppe n'apparaîtra plus dans les filtres.`,
      { confirmText: 'Supprimer quand même' })) return;
    delete ref!.envelope_meta[env];
  }
  function ajouterEnveloppe() {
    const nom = nouvelleEnv.nom.trim();
    if (!nom) return;
    ref!.envelope_meta[nom] = { liquidity: nouvelleEnv.liq, friction: nouvelleEnv.friction.trim() || 'Mixte' };
    nouvelleEnv = { nom: '', liq: liquidites()[0], friction: '' };
  }

  // ── Alertes : enregistrees a chaque changement ─────────────────────────
  const enregistrerAlertes = () => saveUserAlerts($state.snapshot(alertes) as Alerte[]);
  function changerAlerte(i: number, champ: keyof Alerte, valeur: string) {
    if (champ === 'threshold') {
      if (!valeur.trim()) return;       // champ masque laisse vide : seuil inchange
      alertes[i].threshold = parseLocaleNumber(valeur, 0);
    } else (alertes[i] as unknown as Record<string, string>)[champ] = valeur;
    enregistrerAlertes();
  }
  function ajouterAlerte() {
    alertes.push({ label: '', metric: 'cat_pct', category: categoriesConfig()[0] || '', op: '<', threshold: 10 });
    enregistrerAlertes();
  }

  // ── Modeles ─────────────────────────────────────────────────────────────
  let modeles = $state<Record<string, Partial<Ref>> | null>(null);
  $effect(() => {
    api<Record<string, Partial<Ref>>>('GET', '/api/referential/templates').then(t => { modeles = t; }).catch(() => {});
  });
  let modele = $state('');
  let apercu = $state<string | null>(null);
  async function choisirModele() {
    if (!modele) return;
    if (modele === '__saved__') {
      // Le referentiel enregistre : les modifications en cours s'annulent.
      ref = await api<Ref>('GET', '/api/referential');
      apercu = null; modele = '';
      return;
    }
    apercu = modeles?.[modele] ? modele : null;
  }
  async function appliquerModele() {
    await api('PUT', '/api/referential', modeles![apercu!]);
    ref = await api<Ref>('GET', '/api/referential');
    S.config = await api('GET', '/api/config');
    buildSelects();
    apercu = null; modele = '';
  }

  // ── Enregistrement ──────────────────────────────────────────────────────
  let enCours = $state(false);
  let statut = $state({ texte: '', classe: '' });
  async function enregistrer() {
    if (!ref) return;
    enCours = true;
    try {
      const res = await api<{ renommages?: { ancien: string; nouveau: string; positions: number; flux: number }[] }>(
        'PUT', '/api/referential', { ...$state.snapshot(ref), renommages });
      const faits = (res?.renommages || []).filter(r => r.positions || r.flux);
      if (faits.length) {
        toast(faits.map(r => `« ${r.ancien} » → « ${r.nouveau} » : ${r.positions} position${r.positions > 1 ? 's' : ''}, ${r.flux} flux`).join(' · '), 'success');
      }
      renommages = [];
      // Positions et flux charges portent l'ancien nom : on relit tout.
      if (faits.length) reloadAll();
      S.config = await api('GET', '/api/config');
      buildSelects();
      refreshEntitySelect();
      statut = { texte: 'Référentiel enregistré.', classe: 'alert alert-success' };
      setTimeout(() => { statut = { texte: '', classe: '' }; }, 3000);
    } catch (err) {
      statut = { texte: `Erreur : ${(err as Error).message}`, classe: 'alert alert-error' };
    } finally { enCours = false; }
  }
</script>

<div class="page-header">
  <h1>Référentiel</h1>
  <div style="display:flex;gap:.75rem;align-items:center;flex-wrap:wrap">
    <div id="ref-save-status" style="font-size:13px" class={statut.classe || undefined}>{statut.texte}</div>
    <select id="ref-template-select" class="filter-select" style="width:auto" bind:value={modele} onchange={choisirModele}>
      {#if modeles}
        <option value="">Parcourir les modèles…</option>
        <option value="__saved__">Mon référentiel (enregistré)</option>
        {#each Object.keys(modeles) as nom (nom)}<option value={nom}>{nom}</option>{/each}
      {:else}
        <option value="">Charger un modèle…</option>
      {/if}
    </select>
    <button class="btn btn-primary" id="btn-save-referential" disabled={enCours} onclick={enregistrer}>{enCours ? 'Enregistrement…' : 'Enregistrer le référentiel'}</button>
  </div>
</div>
<p class="text-muted" style="margin-bottom:1.25rem;font-size:13px">
  Modifiez les listes et valeurs utilisées dans toute l'application. Les changements prennent effet après enregistrement.
</p>
<div id="ref-template-preview" class="card" style="margin-bottom:1.25rem;border:2px solid var(--primary);background:var(--primary-light)"
     style:display={apercu ? null : 'none'}>
  {#if apercu && modeles}
    {@const t = modeles[apercu]}
    <div class="template-preview">
      <div><strong>Titulaires :</strong> {(t.owners || []).join(', ')}</div>
      <div><strong>Catégories :</strong> {(t.categories || []).join(', ')}</div>
      <div><strong>Enveloppes :</strong> {Object.keys(t.envelope_meta || {}).join(', ')}</div>
      <div style="margin-top:.5rem;display:flex;gap:.5rem">
        <button class="btn btn-primary btn-sm" id="btn-apply-template" onclick={appliquerModele}>Appliquer ce modèle</button>
        <button class="btn btn-secondary btn-sm" id="btn-cancel-template" onclick={() => { apercu = null; modele = ''; }}>Annuler</button>
      </div>
    </div>
  {/if}
</div>

<div class="two-col">
  <div class="card">
    <h2>Titulaires</h2>
    <p class="text-muted" style="font-size:12.5px;margin-bottom:.875rem">
      Personnes dont les patrimoines sont suivis. Une suppression n'efface pas les positions existantes.
    </p>
    <div id="ref-owners-chips">
      {#if ref}
        {#each ref.owners as o, i (o + i)}
          <!-- L'espace entre deux etiquettes (inline-flex) fait leur ecart. -->
          {#if i}{' '}{/if}<span class="ref-chip">
            {o}
            <button type="button" class="chip-del" data-section="owners" data-index={i} aria-label="Supprimer {o}"
                    onclick={() => supprimerTitulaire(i)}><span aria-hidden="true">×</span></button>
          </span>
        {/each}
        <div style="display:flex;gap:.5rem;align-items:center;margin-top:.25rem">
          <input type="text" id="new-owner-input" class="ref-input" placeholder="Prénom / entité" bind:value={nouveaux.owners}
                 onkeydown={e => { if (e.key === 'Enter') { e.preventDefault(); ajouter('owners'); } }}>
          <button class="btn btn-secondary btn-sm" id="btn-add-owner" onclick={() => ajouter('owners')}>+ Ajouter</button>
        </div>
      {/if}
    </div>
  </div>
  <div class="card">
    <h2>Types d'entités</h2>
    <div id="ref-entity-types" style="margin-bottom:1.25rem">{@render liste('ref-entity-types', 'entity_types', 'Type d\'entité')}</div>
    <h2>Modes de valorisation <span class="text-muted" style="font-size:11px;font-weight:400">(label documentaire)</span></h2>
    <div id="ref-valuation-modes" style="margin-bottom:1.25rem">{@render liste('ref-valuation-modes', 'valuation_modes', 'Mode de valorisation')}</div>
    <h2>Types de flux</h2>
    <div id="ref-flux-types">{@render liste('ref-flux-types', 'flux_types', 'Type de flux')}</div>
  </div>
</div>

<div class="card">
  <h2>Catégories d'actifs &amp; mobilisabilité</h2>
  <p class="text-muted" style="font-size:12.5px;margin-bottom:.875rem">
    Le % mobilisable est appliqué au net attribué positif pour estimer la liquidité disponible par catégorie.
  </p>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex : zone defilante, atteignable au clavier -->
  <div class="table-scroll" tabindex="0" role="region" aria-label="Tableau défilant">
    <table class="data-table">
      <thead><tr>
        <th>Catégorie</th>
        <th class="num">% Mobilisable</th>
        <th></th>
      </tr></thead>
      <tbody id="ref-categories-body">
        {#if ref}
          {#each ref.categories as cat, i (i)}
            <tr>
              <td><input class="ref-input ref-cat-name" data-index={i} value={cat} style="width:100%"
                         onchange={e => renommerCategorie(i, e.currentTarget)}></td>
              <td style="text-align:right">
                <input class="ref-input ref-cat-mob" data-cat={cat} type="text" inputmode="decimal" min="0" max="100" step="5"
                       value={Math.round((ref.category_mobilizable[cat] ?? 0.8) * 100)} style="width:65px;text-align:right"
                       onchange={e => { ref!.category_mobilizable[cat] = parseLocaleNumber(e.currentTarget.value, 0) / 100; }}> %
              </td>
              <td>
                <button class="btn-icon del" data-section="categories" data-index={i} onclick={() => supprimerCategorie(i)}>Supprimer</button>
              </td>
            </tr>
          {/each}
          <tr id="ref-cat-add-row">
            <td><input type="text" id="new-cat-name" class="ref-input" placeholder="Nouvelle catégorie" style="width:100%" bind:value={nouvelleCat.nom}></td>
            <td style="text-align:right">
              <input type="text" inputmode="decimal" id="new-cat-mob" class="ref-input" min="0" max="100" step="5"
                     style="width:65px;text-align:right" bind:value={nouvelleCat.mob}> %
            </td>
            <td><button class="btn btn-secondary btn-sm" id="btn-add-cat" onclick={ajouterCategorie}>+ Ajouter</button></td>
          </tr>
        {/if}
      </tbody>
    </table>
  </div>
</div>

<div class="card">
  <h2>Alertes</h2>
  <p class="text-muted" style="font-size:12.5px;margin-bottom:.875rem">
    Affichées dans Synthèse quand le seuil est franchi. Stockées localement dans votre navigateur.
  </p>
  <div id="ref-alerts-list" style="margin-bottom:.75rem">
    {#if !alertes.length}
      <p class="text-muted" style="font-size:12.5px">Aucune alerte configurée.</p>
    {:else}
      {#each alertes as a, i (i)}
        {@const avecCat = a.metric === 'cat_pct' || a.metric === 'cat_abs'}
        <div class="alert-row" data-i={i}>
          <input class="ref-input alert-label" data-i={i} value={a.label || ''} placeholder="Label…" style="width:110px"
                 onchange={e => changerAlerte(i, 'label', e.currentTarget.value)}>
          <select class="filter-select alert-metric" data-i={i} style="width:auto" value={a.metric}
                  onchange={e => changerAlerte(i, 'metric', e.currentTarget.value)}>
            <option value="cat_pct">Catégorie — % du patrimoine net</option>
            <option value="cat_abs">Catégorie — montant net (€)</option>
            <option value="net">Patrimoine net total (€)</option>
            <option value="gross">Actifs bruts totaux (€)</option>
          </select>
          {#if avecCat}
            <select class="filter-select alert-cat" data-i={i} style="width:auto" value={a.category ?? categoriesConfig()[0]}
                    onchange={e => changerAlerte(i, 'category', e.currentTarget.value)}>
              {#each categoriesConfig() as c (c)}<option value={c}>{c}</option>{/each}
            </select>
          {/if}
          <select class="filter-select alert-op" data-i={i} style="width:60px" value={a.op}
                  onchange={e => changerAlerte(i, 'op', e.currentTarget.value)}>
            <option value="&lt;">&lt;</option>
            <option value="&gt;">&gt;</option>
          </select>
          {#key masque}
          <input class="ref-input alert-threshold" data-i={i} type="text" inputmode="decimal" style="width:80px"
                 value={masque && a.metric !== 'cat_pct' ? '' : String(a.threshold || 0)}
                 placeholder={masque && a.metric !== 'cat_pct' ? 'masqué' : undefined}
                 onchange={e => changerAlerte(i, 'threshold', e.currentTarget.value)}>
          {/key}
          <button class="btn-icon del alert-del" data-i={i} onclick={() => { alertes.splice(i, 1); enregistrerAlertes(); }}>Supprimer</button>
        </div>
      {/each}
    {/if}
  </div>
  <button class="btn btn-secondary btn-sm" id="btn-add-alert" onclick={ajouterAlerte}>+ Ajouter une alerte</button>
</div>

<div class="card">
  <h2>Enveloppes &amp; liquidité</h2>
  <p class="text-muted" style="font-size:12.5px;margin-bottom:.875rem">
    La liquidité détermine la classe d'horizon de disponibilité. La friction indique les contraintes de sortie (fiscale, frais, décote probable…).
  </p>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex : zone defilante, atteignable au clavier -->
  <div class="table-scroll" tabindex="0" role="region" aria-label="Tableau défilant">
    <table class="data-table">
      <thead><tr>
        <th>Enveloppe</th>
        <th>Liquidité</th>
        <th>Friction</th>
        <th></th>
      </tr></thead>
      <tbody id="ref-envelopes-body">
        {#if ref}
          {#each Object.entries(ref.envelope_meta) as [nom, m], i (i)}
            <tr>
              <td><input class="ref-input ref-env-name" data-index={i} data-orig={nom} value={nom} style="width:100%"
                         onchange={e => renommerEnveloppe(nom, e.currentTarget)}></td>
              <td>
                <select class="ref-input ref-env-liq" data-env={nom} style="width:100%" bind:value={m.liquidity}>
                  {#each liquidites() as l (l)}<option value={l}>{l}</option>{/each}
                </select>
              </td>
              <td><input class="ref-input ref-env-friction" data-env={nom} value={m.friction || ''} style="width:100%"
                         onchange={e => { m.friction = e.currentTarget.value; }}></td>
              <td><button class="btn-icon del" data-section="envelopes" data-env={nom} onclick={() => supprimerEnveloppe(nom)}>Supprimer</button></td>
            </tr>
          {/each}
          <tr>
            <td><input type="text" id="new-env-name" class="ref-input" placeholder="Nom de l'enveloppe" style="width:100%" bind:value={nouvelleEnv.nom}></td>
            <td>
              <select id="new-env-liq" class="ref-input" style="width:100%" bind:value={nouvelleEnv.liq}>
                {#each liquidites() as l (l)}<option value={l}>{l}</option>{/each}
              </select>
            </td>
            <td><input type="text" id="new-env-friction" class="ref-input" placeholder="ex: Fiscale" style="width:100%" bind:value={nouvelleEnv.friction}></td>
            <td><button class="btn btn-secondary btn-sm" id="btn-add-env" onclick={ajouterEnveloppe}>+ Ajouter</button></td>
          </tr>
        {/if}
      </tbody>
    </table>
  </div>
</div>

{#snippet liste(conteneur: string, cle: 'entity_types' | 'valuation_modes' | 'flux_types', indication: string)}
  {#if ref}
    {#each ref[cle] || [] as v, i (v + i)}
      {#if i}{' '}{/if}<span class="ref-chip">
        {v}
        <button type="button" class="chip-del" data-ref-key={cle} data-index={i} aria-label="Supprimer {v}"
                onclick={() => ref![cle].splice(i, 1)}><span aria-hidden="true">×</span></button>
      </span>
    {/each}
    <div style="display:flex;gap:.5rem;align-items:center;margin-top:.25rem">
      <input type="text" id="new-{conteneur}" class="ref-input" placeholder={indication} bind:value={nouveaux[cle]}>
      <button class="btn btn-secondary btn-sm" id="btn-add-{conteneur}" onclick={() => ajouter(cle)}>+ Ajouter</button>
    </div>
  {/if}
{/snippet}
