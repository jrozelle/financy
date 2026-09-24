<script lang="ts">
  /**
   * Arborescence des positions — seule vue de l'onglet.
   *
   * Un vrai tableau hierarchique (role="treegrid") : l'indentation ne touche
   * que la colonne du nom, valeur, dette, net et plus-value restent alignees.
   *
   * Quatre lectures :
   * - PAR NATURE (defaut) : comment le patrimoine se repartit — liquidites,
   *   placements, immobilier, biens ; une entite est UN bien, ses parts par
   *   titulaire se lisent en la depliant ;
   * - PAR TITULAIRE puis ETABLISSEMENT : le chemin du pointage, releve par
   *   releve ;
   * - PAR ETABLISSEMENT : « ce que j'ai chez Boursorama », tous titulaires ;
   * - A PLAT : tous les comptes sur un rang, pour les classer.
   *
   * Chaque colonne se trie, a tous les niveaux ; une valeur absente (une
   * plus-value inconnue) reste en bas dans les deux sens. Les lignes de titres
   * d'un compte se chargent a son ouverture.
   *
   * Les boutons portent les `data-action` que le gestionnaire delegue de
   * #positions-tree-wrap (main.js) traite : editer, lignes, historique,
   * ajouter dans ce contexte. Aucune action n'est redefinie ici.
   *
   * Porte de static/modules/tabs/arbo.js, balisage et classes a l'identique.
   */
  import { api } from '/static/modules/api.js';
  import { S } from '/static/modules/state.js';
  import { fmt, fmtPct } from '/static/modules/utils.js';
  import { NATURES, natureDe } from '/static/modules/categories.js';
  import { lirePref, ecrirePref } from '/static/modules/preferences.js';
  import type { Noeud, Position, Titre } from './types';

  let { positions = [] }: { positions: Position[] } = $props();

  // ── Reglages memorises ─────────────────────────────────────────────────
  // Regroupement et tri : partages entre appareils (preferences en base).
  // Noeuds ouverts : propres a l'appareil.
  const CLE_GROUPE = 'financy_arbo_groupe';
  const CLE_OUVERTS = 'financy_arbo_ouverts';
  const CLE_TRI = 'financy_arbo_tri';
  type Groupe = 'nature' | 'titulaire' | 'etablissement' | 'plat';
  type Tri = { col: 'nom' | 'brut' | 'dette' | 'net' | 'pv'; sens: number };

  const lireJson = <T,>(texte: string | null, defaut: T): T => {
    try { return texte ? JSON.parse(texte) : defaut; } catch { return defaut; }
  };
  const lireLocal = (cle: string) => { try { return localStorage.getItem(cle); } catch { return null; } };

  let groupe = $state<Groupe>((lirePref(CLE_GROUPE) as Groupe) || 'nature');
  let tri = $state<Tri>({ col: 'brut', sens: -1, ...lireJson(lirePref(CLE_TRI), {}) });
  let ouverts = $state<Set<string> | null>(
    lireLocal(CLE_OUVERTS) ? new Set(lireJson<string[]>(lireLocal(CLE_OUVERTS), [])) : null);
  let recherche = $state('');
  let saisie = $state('');
  let fermesRecherche = $state(new Set<string>());
  let titres = $state(new Map<number, Titre[] | 'chargement'>());

  function memoriser() {
    ecrirePref(CLE_GROUPE, groupe);
    ecrirePref(CLE_TRI, JSON.stringify(tri));
    try { if (ouverts) localStorage.setItem(CLE_OUVERTS, JSON.stringify([...ouverts])); } catch { /* session privee */ }
  }

  // La recherche suit la saisie apres une courte pause.
  let attente: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const v = saisie;
    clearTimeout(attente);
    attente = setTimeout(() => { recherche = v; }, 150);
    return () => clearTimeout(attente);
  });
  // Une nouvelle recherche repart des groupes ouverts d'office.
  let rechercheVue = '';
  $effect(() => {
    const q = recherche.trim().toLowerCase();
    if (q !== rechercheVue) { rechercheVue = q; fermesRecherche = new Set(); }
  });

  // ── Initiales ──────────────────────────────────────────────────────────
  // Une lettre par titulaire ; deux quand deux prenoms commencent pareil (les
  // enfants) — sinon l'etiquette ne distingue plus personne.
  const initiales = $derived.by(() => {
    const noms = [...new Set(((S.positions as Position[]) || positions).map(p => p.owner).filter(Boolean))];
    const out: Record<string, string> = {};
    noms.forEach(n => {
      const une = n[0].toUpperCase();
      out[n] = noms.filter(m => m[0].toUpperCase() === une).length > 1 ? n.slice(0, 2) : une;
    });
    return out;
  });
  const INITIALES = (qui: string) => initiales[qui] || String(qui || '?').slice(0, 1);

  // ── Construction des noeuds ────────────────────────────────────────────
  function somme(noeuds: Noeud[]) {
    const n = { brut: 0, dette: 0, gain: 0, mesures: 0 };
    noeuds.forEach(x => {
      n.brut += x.brut; n.dette += x.dette;
      if (x.mesures) { n.gain += x.gain; n.mesures += x.mesures; }
    });
    return n;
  }
  const couleurNature = (p: Position) => NATURES.find(n => n.id === natureDe(p.category, p.envelope))?.couleur;

  function feuille(p: Position, niveau: number, { avecEtab = true, avecTitulaire = true } = {}): Noeud {
    // « Cash & depots » sous chaque livret ne dirait rien : c'est la nature
    // meme du groupe. Ailleurs, la categorie distingue deux contrats.
    const cat = p.label || p.category === p.envelope || p.category === 'Cash & dépôts' ? null : p.category;
    return {
      cle: `p${p.id}`, niveau, position: p,
      nom: p.envelope || p.category || '—',
      sous: [p.label, avecEtab ? p.establishment : null, cat].filter(Boolean).join(' · '),
      chip: avecTitulaire ? INITIALES(p.owner) : '',
      brut: p.gross_attributed || 0, dette: p.debt_attributed || 0,
      gain: p.gain_attributed || 0, mesures: p.gain_lignes ? 1 : 0,
      titres: !!p.holdings_count, enfants: [],
    };
  }

  function parNature(ps: Position[]): Noeud[] {
    return NATURES.flatMap(n => {
      const dansN = ps.filter(p => natureDe(p.category, p.envelope) === n.id);
      if (!dansN.length) return [];
      const parEntite = new Map<string, Noeud>();
      const comptes: Noeud[] = [];
      dansN.forEach(p => {
        if (!p.entity) { comptes.push(feuille(p, 1)); return; }
        if (!parEntite.has(p.entity)) {
          const e = (S.entities || []).find(x => x.name === p.entity);
          const noeud: Noeud = { cle: `e${p.entity}`, niveau: 1, nom: p.entity, sous: e?.type || 'Entité', chip: '',
                                 brut: 0, dette: 0, gain: 0, mesures: 0, enfants: [] };
          parEntite.set(p.entity, noeud);
          comptes.push(noeud);
        }
        const f = feuille(p, 2, { avecEtab: false });
        f.nom = p.owner;
        f.sous = fmtPct((p.ownership_pct ?? 1) * 100, 0) + ' détenu';
        f.chip = '';
        parEntite.get(p.entity)!.enfants.push(f);
      });
      parEntite.forEach(e => Object.assign(e, somme(e.enfants)));
      comptes.sort((a, b) => b.brut - a.brut);
      return [{ cle: `n${n.id}`, niveau: 0, nom: n.nom, chip: '',
                sous: `${n.aide} · ${comptes.length} compte${comptes.length > 1 ? 's' : ''}`,
                couleur: n.couleur, enfants: comptes, ...somme(comptes) }];
    });
  }

  function parTitulaire(ps: Position[]): Noeud[] {
    return [...new Set(ps.map(p => p.owner))].map(qui => {
      const etabs = new Map<string, Noeud>();
      ps.filter(p => p.owner === qui).forEach(p => {
        const nom = p.establishment || p.entity || 'Sans établissement';
        if (!etabs.has(nom)) etabs.set(nom, { cle: `t${qui}|${nom}`, niveau: 1, nom, sous: '', chip: '', enfants: [],
          brut: 0, dette: 0, gain: 0, mesures: 0,
          contexte: { owner: qui, establishment: p.establishment || null, entity: p.establishment ? null : p.entity } });
        const f = feuille(p, 2, { avecEtab: false, avecTitulaire: false });
        f.couleur = couleurNature(p);
        etabs.get(nom)!.enfants.push(f);
      });
      const liste = [...etabs.values()];
      liste.forEach(e => {
        Object.assign(e, somme(e.enfants));
        e.enfants.sort((a, b) => b.brut - a.brut);
        e.sous = `${e.enfants.length} compte${e.enfants.length > 1 ? 's' : ''}`;
      });
      liste.sort((a, b) => b.brut - a.brut);
      return { cle: `t${qui}`, niveau: 0, nom: qui, chip: INITIALES(qui),
               sous: `${liste.length} établissement${liste.length > 1 ? 's' : ''}`,
               enfants: liste, ...somme(liste) };
    }).sort((a, b) => b.brut - a.brut);
  }

  function parEtablissement(ps: Position[]): Noeud[] {
    const etabs = new Map<string, Noeud>();
    ps.forEach(p => {
      const nom = p.establishment || p.entity || 'Sans établissement';
      if (!etabs.has(nom)) etabs.set(nom, { cle: `e${nom}`, niveau: 0, nom, sous: '', chip: '', enfants: [],
        brut: 0, dette: 0, gain: 0, mesures: 0,
        contexte: { owner: p.owner, establishment: p.establishment || null, entity: p.establishment ? null : p.entity } });
      const f = feuille(p, 1, { avecEtab: false });
      f.couleur = couleurNature(p);
      f.pastille = true;
      etabs.get(nom)!.enfants.push(f);
    });
    return [...etabs.values()].map(e => {
      const qui = new Set(e.enfants.map(f => f.position!.owner));
      e.sous = `${e.enfants.length} compte${e.enfants.length > 1 ? 's' : ''}`
        + (qui.size > 1 ? ` · ${qui.size} titulaires` : '');
      // Un seul titulaire : « Ajouter » cree le compte a son nom ; plusieurs,
      // le formulaire demandera lequel.
      if (qui.size > 1 && e.contexte) e.contexte = { ...e.contexte, owner: null };
      return Object.assign(e, somme(e.enfants));
    }).sort((a, b) => b.brut - a.brut);
  }

  function aPlat(ps: Position[]): Noeud[] {
    return ps.map(p => {
      const f = feuille(p, 0);
      f.visuel = 1;                  // un compte, pas un groupe : sans fond
      f.couleur = couleurNature(p);
      f.pastille = true;             // la nature se lit a la pastille
      if (p.entity) f.sous = [p.entity, f.sous].filter(Boolean).join(' · ');
      return f;
    });
  }

  const racinesBrutes = () => groupe === 'titulaire' ? parTitulaire(positions)
    : groupe === 'etablissement' ? parEtablissement(positions)
    : groupe === 'plat' ? aPlat(positions) : parNature(positions);

  // ── Tri ────────────────────────────────────────────────────────────────
  const CLES_TRI: Record<Tri['col'], (n: Noeud) => string | number | null> = {
    nom: n => (n.nom || '').toLocaleLowerCase('fr'),
    brut: n => n.brut,
    dette: n => n.dette,
    net: n => n.brut - n.dette,
    pv: n => (n.position ? (n.position.gain_lignes ? n.position.gain_attributed : null)
                         : (n.mesures ? n.gain : null)),
  };
  function trier(noeuds: Noeud[]): Noeud[] {
    const cle = CLES_TRI[tri.col] || CLES_TRI.brut;
    const out = [...noeuds].sort((a, b) => {
      const x = cle(a), y = cle(b);
      if (x == null || y == null) return Number(x == null) - Number(y == null);
      if (typeof x === 'string') return tri.sens * x.localeCompare(String(y), 'fr');
      return tri.sens * ((x as number) - (y as number));
    });
    out.forEach(n => { if (n.enfants?.length) n.enfants = trier(n.enfants); });
    return out;
  }

  // ── Recherche ──────────────────────────────────────────────────────────
  // Un noeud reste s'il correspond ou si l'un de ses descendants correspond ;
  // garde pour ses descendants, il ne compte que ce qu'il montre. Les GROUPES
  // retenus s'ouvrent d'office ; un compte a titres, non — chercher « PEA »
  // chargerait les lignes de chaque PEA.
  function filtrer(noeuds: Noeud[], q: string, forces: Set<string>): Noeud[] {
    const texte = (n: Noeud) => `${n.nom} ${n.sous} ${n.position?.owner || ''} ${n.position?.establishment || ''}`.toLowerCase();
    return noeuds.flatMap(n => {
      if (texte(n).includes(q)) {
        if (!n.position && n.enfants?.length) forces.add(n.cle);
        return [n];
      }
      const enfants = filtrer(n.enfants || [], q, forces);
      if (!enfants.length) return [];
      forces.add(n.cle);
      // « 15 comptes » quand six s'affichent : le decompte suit le filtre.
      const sous = (n.sous || '').replace(/\d+ comptes?\b/,
        `${enfants.length} sur ${n.enfants.length} compte${n.enfants.length > 1 ? 's' : ''}`);
      return [{ ...n, enfants, sous, ...somme(enfants) }];
    });
  }

  const q = $derived(recherche.trim().toLowerCase());
  const vue = $derived.by(() => {
    const forces = new Set<string>();
    let racines = trier(racinesBrutes());
    if (q) racines = filtrer(racines, q, forces);
    return { racines, forces, total: somme(racines) };
  });

  // ── Ouverture ──────────────────────────────────────────────────────────
  // Defaut : les groupes de tete ouverts, jamais un compte. A plat, les
  // comptes SONT la tete : tous ouverts, ils chargeraient chacun leurs titres.
  const ouvertParDefaut = (n: Noeud) => n.niveau === 0 && !n.position;
  function estOuvert(n: Noeud): boolean {
    if (vue.forces.has(n.cle)) return !fermesRecherche.has(n.cle);
    if (!ouverts) return ouvertParDefaut(n);
    return ouverts.has(n.cle);
  }
  const ouvrable = (n: Noeud) => !!(n.enfants?.length || n.titres);

  function basculer(cle: string) {
    if (vue.forces.has(cle)) {
      // Ouvert par la recherche : le replier ne touche pas l'etat memorise.
      const s = new Set(fermesRecherche);
      s.has(cle) ? s.delete(cle) : s.add(cle);
      fermesRecherche = s;
      return;
    }
    // Premier geste : on part de l'etat par defaut, meme regle qu'au rendu.
    const s = new Set(ouverts ?? racinesBrutes().filter(ouvertParDefaut).map(r => r.cle));
    s.has(cle) ? s.delete(cle) : s.add(cle);
    ouverts = s;
    memoriser();
  }
  function toutDeplier() {
    const toutes = new Set<string>();
    const parcourir = (ns: Noeud[]) => ns.forEach(n => { if (n.enfants?.length) { toutes.add(n.cle); parcourir(n.enfants); } });
    parcourir(racinesBrutes());
    ouverts = toutes; memoriser();
  }
  function toutReplier() { ouverts = new Set(); memoriser(); }
  function changerGroupe(g: Groupe) {
    if (g === groupe) return;
    groupe = g;
    ouverts = null;                  // chaque lecture a ses propres noeuds
    memoriser();
  }
  function trierPar(col: Tri['col']) {
    // Premier clic : decroissant sur un montant — on cherche le plus gros —,
    // croissant sur un nom.
    tri = tri.col === col ? { col, sens: -tri.sens } : { col, sens: col === 'nom' ? 1 : -1 };
    memoriser();
  }

  // ── Lignes de titres, chargees a l'ouverture de leur compte ────────────
  const aCharger = $derived.by(() => {
    const ids: number[] = [];
    const parcourir = (ns: Noeud[]) => ns.forEach(n => {
      if (!ouvrable(n) || !estOuvert(n)) return;
      if (n.enfants.length) parcourir(n.enfants);
      else if (n.titres && n.position && !titres.has(n.position.id)) ids.push(n.position.id);
    });
    parcourir(vue.racines);
    return ids;
  });
  $effect(() => { aCharger.forEach(chargerTitres); });

  async function chargerTitres(id: number) {
    titres = new Map(titres).set(id, 'chargement');
    let liste: Titre[] = [];
    try {
      const r = await api<{ holdings?: Titre[] }>('GET', `/api/positions/${id}/holdings`, null, { silent: true });
      liste = (r.holdings || []).slice().sort((a, b) =>
        (b.effective_value ?? b.market_value ?? 0) - (a.effective_value ?? a.market_value ?? 0));
    } catch { /* aucune ligne */ }
    titres = new Map(titres).set(id, liste);
  }

  /** Des lignes modifiees : redemandees a la prochaine ouverture. */
  export function oublierTitres(id?: number | null) {
    if (id == null) { titres = new Map(); return; }
    const m = new Map(titres); m.delete(id); titres = m;
  }

  function noeudsTitres(n: Noeud): Noeud[] {
    const h = titres.get(n.position!.id);
    if (!Array.isArray(h)) return [];
    const pct = n.position!.ownership_pct ?? 1;
    return h.map(t => {
      const v = (t.effective_value ?? t.market_value ?? 0) * pct;
      const cb = t.cost_basis, mv = t.market_value;
      const connu = !!cb && !(mv != null && Math.abs(cb - mv) < 0.01);
      return {
        cle: `h${t.id}`, niveau: n.niveau + 1, nom: t.name || t.isin, sous: t.isin && t.name ? t.isin : '',
        chip: '', brut: v, dette: 0, gain: 0, mesures: 0, enfants: [],
        gainTitre: connu ? ((t.effective_value ?? mv ?? 0) - cb!) * pct : null,
      };
    });
  }

  const signe = (v: number) => `${v >= 0 ? '+' : '−'}${fmt(Math.abs(v))}`;
  const groupes: [Groupe, string][] = [['nature', 'Nature'], ['titulaire', 'Titulaire'],
                                       ['etablissement', 'Établissement'], ['plat', 'À plat']];
</script>

{#snippet pv(n: Noeud)}
  {#if n.gainTitre !== undefined}
    {#if n.gainTitre == null}<span class="arbo-pv-na">PRU inconnu</span>
    {:else}<span class={n.gainTitre >= 0 ? 'pv-hausse' : 'pv-baisse'}>{signe(n.gainTitre)}</span>{/if}
  {:else if n.position}
    {@const p = n.position}
    {#if !p.has_holdings}<span class="arbo-pv-na">—</span><span class="arbo-pv-note">{p.entity ? 'valeur de l’entité' : 'sans lignes de titres'}</span>
    {:else if !p.gain_lignes}<span class="arbo-pv-na">PRU inconnu</span>
    {:else}<span class={(p.gain_attributed ?? 0) >= 0 ? 'pv-hausse' : 'pv-baisse'}>{signe(p.gain_attributed ?? 0)}</span>{#if p.gain_pct != null}<span
        class="arbo-pv-note arbo-pv-pct">{fmtPct(p.gain_pct * 100, 1, true)}</span>{/if}{#if p.gain_lignes < p.holdings_count}<span
        class="arbo-pv-note">{p.gain_lignes}/{p.holdings_count} lignes</span>{/if}{/if}
  {:else if n.mesures}
    <span class={n.gain >= 0 ? 'pv-hausse' : 'pv-baisse'}>{signe(n.gain)}</span><span
      class="arbo-pv-note">{n.mesures} compte{n.mesures > 1 ? 's' : ''} mesuré{n.mesures > 1 ? 's' : ''}</span>
  {/if}
{/snippet}

{#snippet ligne(n: Noeud, total: number, couleurHeritee?: string)}
  {@const couleur = n.couleur || couleurHeritee || 'var(--primary)'}
  {@const peut = ouvrable(n)}
  {@const ouvert = peut && estOuvert(n)}
  {@const part = total ? n.brut / total * 100 : 0}
  {@const net = n.brut - n.dette}
  {@const largeur = `${Math.max(.6, part).toFixed(2)}%`}
  <tr class="arbo-l{n.visuel ?? n.niveau}" aria-level={n.niveau + 1}
      aria-expanded={peut ? ouvert : undefined} data-cle={n.cle}>
    <td class="arbo-nom" role="gridcell">
      <div class="arbo-nom-in" style:--niv={n.niveau}>
        {#if peut}
          <button type="button" class="arbo-chevron" data-arbo-basculer={n.cle}
                  aria-label="{ouvert ? 'Replier' : 'Déplier'} {n.nom}" onclick={() => basculer(n.cle)}>
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M9 6l6 6-6 6"/></svg></button>
        {:else}<span class="arbo-chevron-vide"></span>{/if}
        {#if (n.niveau === 0 || n.pastille) && n.couleur}<span class="arbo-pastille" style:background={couleur}></span>{/if}
        <span class="arbo-texte">
          <span class="arbo-titre">{n.nom}</span>
          {#if n.sous}<span class="arbo-sous">{n.sous}</span>{/if}
        </span>
        {#if n.chip}<span class="arbo-chip">{n.chip}</span>{/if}
      </div>
      <span class="arbo-barre arbo-barre--mobile" aria-hidden="true"><i style:width={largeur} style:background={couleur}></i></span>
    </td>
    <td class="arbo-part" role="gridcell">
      <span class="arbo-barre" aria-hidden="true"><i style:width={largeur} style:background={couleur}></i></span>
      <span class="arbo-part-txt">{fmtPct(part, part < 10 ? 1 : 0)}</span>
    </td>
    <td class="num arbo-valeur" role="gridcell">{fmt(n.brut)}</td>
    <td class="num arbo-dette" class:is-dette={n.dette} role="gridcell">{n.dette ? fmt(n.dette) : '—'}</td>
    <td class="num arbo-net" class:is-negatif={net < 0} role="gridcell">{fmt(net)}
      <span class="arbo-pv-mobile">{@render pv(n)}</span></td>
    <td class="num arbo-pv" role="gridcell">{@render pv(n)}</td>
    <td class="arbo-actions" role="gridcell">
      {#if n.position}
        {@const p = n.position}
        <button type="button" class="arbo-act" data-action="edit-pos" data-id={p.id} aria-label="Éditer {n.nom}">Éditer</button>
        {#if p.holdings_count}<button type="button" class="arbo-act" data-action="manage-holdings" data-id={p.id}
          aria-label="Lignes de {n.nom}">Lignes</button>{/if}
        <button type="button" class="arbo-act" data-action="history-pos" data-id={p.id} aria-label="Historique de {n.nom}">Historique</button>
      {:else if n.contexte}
        {@const c = n.contexte}
        <!-- Un etablissement : son historique, et y ajouter un compte. -->
        <button type="button" class="arbo-act" data-action="history-etabl" data-owner={c.owner}
                data-establishment={c.establishment || undefined} data-entity={c.entity || undefined}
                aria-label="Historique de {n.nom}">Historique</button>
        <button type="button" class="arbo-act" data-action="add-pos-ctx" data-owner={c.owner}
                data-establishment={c.establishment || undefined} data-entity={c.entity || undefined}
                aria-label="Ajouter un compte chez {n.nom}">Ajouter</button>
      {/if}
    </td>
  </tr>
  {#if ouvert}
    {#if n.enfants.length}
      {#each n.enfants as e (e.cle)}{@render ligne(e, total, couleur)}{/each}
    {:else if n.titres && n.position}
      {#if Array.isArray(titres.get(n.position.id))}
        {#each noeudsTitres(n) as t (t.cle)}{@render ligne(t, total, couleur)}{/each}
      {:else}
        <tr class="arbo-l{n.niveau + 1}" aria-level={n.niveau + 2}><td class="arbo-nom" colspan="7">
          <div class="arbo-nom-in arbo-attente" style:--niv={n.niveau + 1}><span class="arbo-chevron-vide"></span>Chargement des lignes…</div></td></tr>
      {/if}
    {/if}
  {/if}
{/snippet}

{#snippet entete(col: Tri['col'], texte: string, cls: string, porteEtat = col !== 'brut')}
  <!-- « Part du brut » et « Valeur » trient la meme chose ; seule la seconde
       porte l'etat, pour ne pas l'annoncer deux fois. -->
  {@const actif = tri.col === col}
  <th scope="col" class={cls} aria-sort={porteEtat ? (actif ? (tri.sens > 0 ? 'ascending' : 'descending') : 'none') : undefined}>
    <button type="button" class="arbo-tri" data-arbo-tri={col} onclick={() => trierPar(col)}>{texte}<span
      aria-hidden="true">{actif ? (tri.sens > 0 ? ' ▲' : ' ▼') : ''}</span></button></th>
{/snippet}

<div class="arbo-barre-outils">
  <label class="sr-only" for="arbo-recherche">Rechercher un compte</label>
  <input type="search" id="arbo-recherche" class="arbo-recherche" placeholder="Rechercher un compte…" autocomplete="off"
         bind:value={saisie}>
  <span class="arbo-lib">Regrouper par</span>
  <div class="seg" role="group" aria-label="Regrouper par" id="arbo-groupes">
    {#each groupes as [g, lib] (g)}
      <button type="button" class="seg-btn" data-arbo-groupe={g} aria-pressed={groupe === g}
              onclick={() => changerGroupe(g)}>{lib}</button>
    {/each}
  </div>
  <span class="arbo-espace"></span>
  <button type="button" class="arbo-bouton" id="arbo-deplier" onclick={toutDeplier}>Tout déplier</button>
  <button type="button" class="arbo-bouton" id="arbo-replier" onclick={toutReplier}>Tout replier</button>
</div>
<div id="positions-tree-body">
  {#if !vue.racines.length}
    <p class="arbo-vide">{q ? `Aucun compte ne correspond à « ${recherche} ».` : 'Aucune position pour cet arrêté.'}</p>
  {:else}
    <div class="arbo-wrap">
      <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role : motif ARIA treegrid (niveaux, depliage) -->
      <table class="arbo" role="treegrid" aria-label="Arborescence des positions">
        <thead>
          <tr>
            {@render entete('nom', 'Nom', '')}
            {@render entete('brut', 'Part du brut', 'arbo-part')}
            {@render entete('brut', 'Valeur', 'num arbo-valeur', true)}
            {@render entete('dette', 'Dette', 'num arbo-dette')}
            {@render entete('net', 'Net', 'num arbo-net')}
            {@render entete('pv', 'Plus-value', 'num arbo-pv')}
            <th scope="col" class="arbo-actions"><span class="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>{#each vue.racines as r (r.cle)}{@render ligne(r, vue.total.brut)}{/each}</tbody>
        <tfoot>
          <tr>
            <td>Patrimoine{q ? ' (filtré)' : ''}</td>
            <td class="arbo-part"></td>
            <td class="num arbo-valeur">{fmt(vue.total.brut)}</td>
            <td class="num arbo-dette" class:is-dette={vue.total.dette}>{vue.total.dette ? fmt(vue.total.dette) : '—'}</td>
            <td class="num arbo-net">{fmt(vue.total.brut - vue.total.dette)}</td>
            <td class="num arbo-pv">{#if vue.total.mesures}<span class={vue.total.gain >= 0 ? 'pv-hausse' : 'pv-baisse'}>{signe(vue.total.gain)}</span>{/if}</td>
            <td class="arbo-actions"></td>
          </tr>
        </tfoot>
      </table>
    </div>
  {/if}
</div>
