<script lang="ts">
  /**
   * La synthese : douze cartes sur une grille de douze colonnes, qu'on
   * deplace, elargit ou masque. La disposition vit en base
   * (`/api/synthese/disposition`) : elle suit l'utilisateur du PC au
   * telephone. Sous 1 200 px, l'ordre et les masquees s'appliquent, la
   * largeur non (tout tient sur une colonne).
   *
   * Aucune bibliotheque : glisser et redimensionner aux evenements de
   * pointeur, et tout reste possible au clavier (fleches sur la poignee,
   * largeurs, masquer).
   *
   * Remplace static/modules/widgets.js, qui manipulait de l'exterieur des
   * cartes posees dans le gabarit (et devait reinjecter ses commandes a
   * chaque redessin). Classes et attributs a l'identique : style.css
   * s'applique tel quel.
   */
  import { tick } from 'svelte';
  import { api } from '/static/modules/api.js';
  import { toast } from '/static/modules/dialogs.js';
  import Chiffres from './Chiffres.svelte';
  import Contribution from './Contribution.svelte';
  import HistoriqueNet from './HistoriqueNet.svelte';
  import EvolutionGroupes from './EvolutionGroupes.svelte';
  import Projection from './Projection.svelte';
  import Repartition from './Repartition.svelte';
  import Cible from './Cible.svelte';
  import Mouvements from './Mouvements.svelte';
  import Liquidite from './Liquidite.svelte';
  import Comptes from './Comptes.svelte';
  import Entites from './Entites.svelte';
  import Fiscalite from './Fiscalite.svelte';

  type Props = Record<string, any>;
  let { onglet, cartes = null }: { onglet: HTMLElement; cartes: Props | null } = $props();

  // Ordre, largeur, nom par defaut, et l'element qui porte chaque carte.
  const CARTES: { id: string; largeur: number; nom: string; classe: string; elId?: string }[] = [
    { id: 'chiffres', largeur: 12, nom: 'Chiffres clés', classe: 'kpi-grid' },
    { id: 'contribution', largeur: 5, nom: 'D’où vient la hausse', classe: 'card', elId: 'card-contribution' },
    { id: 'historique', largeur: 7, nom: 'Évolution du patrimoine net', classe: 'card' },
    { id: 'evolution', largeur: 12, nom: 'Évolution par catégorie', classe: 'card', elId: 'synthese-history-detail-card' },
    { id: 'projection', largeur: 12, nom: 'Projection', classe: 'card', elId: 'card-projection' },
    { id: 'repartition', largeur: 7, nom: 'Répartition', classe: 'card card-repartition', elId: 'repartition-card' },
    { id: 'cible', largeur: 5, nom: 'Écart à la cible', classe: 'card' },
    { id: 'mouvements', largeur: 7, nom: 'Ce qui a bougé', classe: 'card' },
    { id: 'liquidite', largeur: 5, nom: 'Si vous aviez besoin d’argent', classe: 'card' },
    { id: 'comptes', largeur: 12, nom: 'Vos comptes', classe: 'card', elId: 'comptes-card' },
    { id: 'entites', largeur: 12, nom: 'Entités', classe: 'card', elId: 'entities-synthese-card' },
    { id: 'fiscalite', largeur: 12, nom: 'Si vous vendiez tout', classe: 'card', elId: 'fiscalite-card' },
  ];
  const IDS = CARTES.map(c => c.id);
  const DEF = Object.fromEntries(CARTES.map(c => [c.id, c]));
  const LARGEURS: [number, string][] = [[4, '1/3'], [6, '1/2'], [8, '2/3'], [12, 'Pleine']];
  const MIN_COLONNES = 3;

  // Elements hotes, pour les cartes qui se masquent seules faute de donnees.
  let hotes = $state<Record<string, HTMLElement | undefined>>({});
  // Cartes qui chargent leurs propres donnees.
  let comptes = $state<any>(), contribution = $state<any>(), fiscalite = $state<any>();

  // ── Disposition ────────────────────────────────────────────────────────
  type Disposition = { ordre?: string[]; largeurs?: Record<string, number>; masquees?: string[] };
  let disp = $state<Disposition>({});
  api<Disposition>('GET', '/api/synthese/disposition', null, { silent: true })
    .then(d => { disp = d || {}; }).catch(() => { /* mise en page d'origine */ });

  const ordre = $derived.by(() => {
    const perso = (disp.ordre || []).filter(id => IDS.includes(id));
    return [...perso, ...IDS.filter(id => !perso.includes(id))];
  });
  const largeur = (id: string) => disp.largeurs?.[id] || DEF[id].largeur;
  const masquee = (id: string) => (disp.masquees || []).includes(id);
  const rang = (id: string) => ordre.indexOf(id) + 1;

  let attente: ReturnType<typeof setTimeout> | undefined;
  function enregistrer() {
    // Regroupe les rafales (glisser, redimensionner) en une ecriture.
    clearTimeout(attente);
    attente = setTimeout(async () => {
      try { await api('PUT', '/api/synthese/disposition', { ordre, largeurs: disp.largeurs || {}, masquees: disp.masquees || [] }); }
      catch { toast('Disposition non enregistrée', 'error'); }
    }, 400);
  }
  function changer(fn: (d: Required<Disposition>) => void) {
    const d = { ordre: [...ordre], largeurs: { ...(disp.largeurs || {}) }, masquees: [...(disp.masquees || [])] };
    fn(d);
    disp = d;
    enregistrer();
  }
  async function dispositionOrigine() {
    disp = {};
    try { await api('PUT', '/api/synthese/disposition', {}); } catch { /* toast deja affiche */ }
  }

  // ── Edition ────────────────────────────────────────────────────────────
  let edition = $state(false);
  let bouton = $state<HTMLButtonElement>();
  let barre = $state<HTMLElement>();
  $effect(() => { onglet.classList.toggle('w-edition', edition); });
  export async function basculerEdition() {
    if (edition) { quitter(); return; }
    // La barre se cale sous l'en-tete, dont la hauteur varie.
    const entete = document.querySelector('.page-head');
    onglet.style.setProperty('--w-entete', `${entete ? entete.getBoundingClientRect().bottom : 56}px`);
    edition = true;
    window.scrollTo({ top: 0 });
    await Promise.resolve();
    barre?.querySelector('button')?.focus();
  }
  function quitter() { edition = false; bouton?.focus(); }
  function echap(e: KeyboardEvent) {
    if (edition && e.key === 'Escape' && !document.querySelector('.modal:not(.hidden)')) quitter();
  }

  function clavier(e: KeyboardEvent, id: string) {
    const pas = ({ ArrowUp: -1, ArrowLeft: -1, ArrowDown: 1, ArrowRight: 1 } as Record<string, number>)[e.key];
    const bout = ({ Home: -Infinity, End: Infinity } as Record<string, number>)[e.key];
    if (pas === undefined && bout === undefined) return;
    e.preventDefault();
    changer(d => {
      const i = d.ordre.indexOf(id);
      const j = Math.max(0, Math.min(d.ordre.length - 1, bout !== undefined ? (bout < 0 ? 0 : d.ordre.length - 1) : i + pas));
      d.ordre.splice(i, 1);
      d.ordre.splice(j, 0, id);
    });
    // La carte a change de place dans le DOM : le focus reste sur sa poignee.
    tick().then(() => hotes[id]?.querySelector<HTMLElement>('.w-poignee')?.focus());
  }

  // ── Glisser-deposer et redimensionnement ───────────────────────────────
  let glissee = $state<string | null>(null);
  function glisser(e: PointerEvent, id: string) {
    e.preventDefault();
    glissee = id;
    const poignee = e.currentTarget as HTMLElement;
    poignee.setPointerCapture(e.pointerId);
    const bouger = (ev: PointerEvent) => {
      // La carte la plus proche du pointeur, et le cote ou il se trouve :
      // plus sur que la carte « sous » le pointeur, qui change a chaque
      // reflux de la grille.
      let meilleure: { c: HTMLElement; r: DOMRect } | null = null, dmin = Infinity;
      onglet.querySelectorAll<HTMLElement>('[data-carte]').forEach(c => {
        if (c.dataset.carte === id || getComputedStyle(c).display === 'none') return;
        const r = c.getBoundingClientRect();
        const dx = Math.max(r.left - ev.clientX, 0, ev.clientX - r.right);
        const dy = Math.max(r.top - ev.clientY, 0, ev.clientY - r.bottom);
        const d = dx * dx + dy * dy;
        if (d < dmin) { dmin = d; meilleure = { c, r }; }
      });
      if (!meilleure) return;
      const { c, r } = meilleure as { c: HTMLElement; r: DOMRect };
      const memeRangee = ev.clientY >= r.top && ev.clientY <= r.bottom;
      const avant = memeRangee ? ev.clientX < r.left + r.width / 2 : ev.clientY < r.top + r.height / 2;
      const o = ordre.filter(x => x !== id);
      o.splice(o.indexOf(c.dataset.carte!) + (avant ? 0 : 1), 0, id);
      if (o.join() !== ordre.join()) disp = { ...disp, ordre: o };
    };
    const lacher = () => {
      poignee.removeEventListener('pointermove', bouger);
      poignee.removeEventListener('pointerup', lacher);
      poignee.removeEventListener('pointercancel', lacher);
      glissee = null;
      changer(() => {});
    };
    poignee.addEventListener('pointermove', bouger);
    poignee.addEventListener('pointerup', lacher);
    poignee.addEventListener('pointercancel', lacher);
  }
  function redimensionner(e: PointerEvent, id: string) {
    e.preventDefault();
    const el = hotes[id]!;
    const gap = parseFloat(getComputedStyle(onglet).columnGap) || 0;
    const colonne = (onglet.clientWidth - 11 * gap) / 12;
    const gauche = el.getBoundingClientRect().left;
    const bord = e.currentTarget as HTMLElement;
    bord.setPointerCapture(e.pointerId);
    const bouger = (ev: PointerEvent) => {
      // Calee sur la grille : le nombre de colonnes que couvre le pointeur.
      const n = Math.max(MIN_COLONNES, Math.min(12, Math.round((ev.clientX - gauche + gap) / (colonne + gap))));
      if (n !== largeur(id)) disp = { ...disp, largeurs: { ...(disp.largeurs || {}), [id]: n } };
    };
    const lacher = () => {
      bord.removeEventListener('pointermove', bouger);
      bord.removeEventListener('pointerup', lacher);
      bord.removeEventListener('pointercancel', lacher);
      changer(() => {});
    };
    bord.addEventListener('pointermove', bouger);
    bord.addEventListener('pointerup', lacher);
    bord.addEventListener('pointercancel', lacher);
  }

  // ── Donnees chargees par les cartes elles-memes ────────────────────────
  export async function recharger({ owner, date, dernier, cache }:
    { owner: string | null; date: string | null; dernier: string | null; cache: boolean }) {
    await Promise.resolve();       // les cartes sont montees au premier rendu
    comptes?.recharger(owner, date);
    fiscalite?.recharger(owner, date);
    if (!cache) contribution?.recharger(owner, date, dernier);
  }

  const POIGNEE = '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><g fill="currentColor"><circle cx="5" cy="3" r="1.3"/><circle cx="11" cy="3" r="1.3"/><circle cx="5" cy="8" r="1.3"/><circle cx="11" cy="8" r="1.3"/><circle cx="5" cy="13" r="1.3"/><circle cx="11" cy="13" r="1.3"/></g></svg>';
  const c = $derived(cartes || {});
</script>

<svelte:window onkeydown={echap} />

{#if edition}
  {@const cachees = ordre.filter(masquee)}
  <div class="w-barre" role="region" aria-label="Personnalisation de la synthèse" bind:this={barre}>
    <strong>Personnalisation</strong>
    <span class="text-muted w-aide">Glissez une carte par sa poignée, élargissez-la par son bord droit, ou utilisez ses boutons.</span>
    <span class="w-masquees">{#if cachees.length}Masquées :{#each cachees as id (id)} <button type="button" class="btn btn-secondary btn-sm"
      data-afficher={id} onclick={() => changer(d => { d.masquees = d.masquees.filter(x => x !== id); })}>Afficher « {DEF[id].nom} »</button>{/each}{:else}Aucune carte masquée.{/if}</span>
    <span class="w-fin">
      <button type="button" class="btn btn-secondary btn-sm" data-action="defaut" onclick={dispositionOrigine}>Disposition d’origine</button>
      <button type="button" class="btn btn-primary btn-sm" data-action="fin" onclick={quitter}>Terminer</button>
    </span>
  </div>
{/if}

<!-- Les cartes dans l'ordre choisi : la grille les place (--w-rang), et le
     DOM suit le meme ordre, pour que le clavier et les lecteurs d'ecran
     parcourent la page comme on la voit. -->
{#each ordre as id (id)}
  {@const carte = DEF[id]}
  <div class={carte.classe} id={carte.elId} data-carte={id} bind:this={hotes[id]}
       data-rang={rang(id)} style:--w-rang={rang(id)} data-largeur={largeur(id)} style:--w-largeur={largeur(id)}
       class:w-masquee={masquee(id)} class:w-glisse={glissee === id}>
    {#if edition}
      {@const nom = DEF[id].nom}
      <div class="w-commandes">
        <button type="button" class="w-poignee" data-w="glisser"
                aria-label="Déplacer « {nom} », position {rang(id)} sur {ordre.length} : glisser, ou flèches du clavier"
                onpointerdown={e => glisser(e, id)} onkeydown={e => clavier(e, id)}>{@html POIGNEE}</button>
        <span class="w-nom">{nom}</span>
        <span class="w-largeurs" role="group" aria-label="Largeur de « {nom} »">{#each LARGEURS as [n, lib] (n)}<button type="button"
          data-w="largeur" data-n={n} aria-pressed={largeur(id) === n}
          onclick={() => changer(d => { d.largeurs[id] = n; })}>{lib}</button>{/each}</span>
        <button type="button" data-w="masquer" aria-pressed={masquee(id)}
                onclick={() => changer(d => { d.masquees = masquee(id) ? d.masquees.filter(x => x !== id) : [...d.masquees, id]; })}>{masquee(id) ? 'Afficher' : 'Masquer'}</button>
      </div>
    {/if}
    {#if hotes[id]}
      {#if id === 'chiffres' && c.chiffres}<Chiffres {...c.chiffres} />
      {:else if id === 'contribution'}<Contribution bind:this={contribution} hote={hotes[id]!} masque={c.masque} />
      {:else if id === 'historique' && c.historique}<HistoriqueNet {...c.historique} masque={c.masque} />
      {:else if id === 'evolution' && c.evolution}<EvolutionGroupes hote={hotes[id]!} {...c.evolution} masque={c.masque} />
      {:else if id === 'projection' && c.projection}<Projection hote={hotes[id]!} {...c.projection} masque={c.masque} />
      {:else if id === 'repartition' && c.repartition}<Repartition {...c.repartition} masque={c.masque} />
      {:else if id === 'cible' && c.cible}<Cible {...c.cible} />
      {:else if id === 'mouvements' && c.mouvements}<Mouvements {...c.mouvements} masque={c.masque} />
      {:else if id === 'liquidite' && c.liquidite}<Liquidite {...c.liquidite} masque={c.masque} />
      {:else if id === 'comptes'}<Comptes bind:this={comptes} hote={hotes[id]!} />
      {:else if id === 'entites' && c.entites}<Entites hote={hotes[id]!} {...c.entites} masque={c.masque} />
      {:else if id === 'fiscalite'}<Fiscalite bind:this={fiscalite} hote={hotes[id]!} masque={c.masque} />
      {/if}
    {/if}
    {#if edition}
      <div class="w-bord" aria-hidden="true" onpointerdown={e => redimensionner(e, id)}></div>
      <span class="w-vide">Vide pour cette vue : elle s’affiche quand elle a des données.</span>
    {/if}
  </div>
{/each}

<button type="button" class="btn btn-secondary btn-sm w-perso-bouton" bind:this={bouton}
        onclick={basculerEdition}>{edition ? 'Terminer la personnalisation' : 'Personnaliser la synthèse'}</button>
