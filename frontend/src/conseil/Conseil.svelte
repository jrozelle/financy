<script lang="ts">
  /**
   * Onglet Conseil patrimonial. Les sections suivent l'ordre ou l'on s'en
   * sert : ce qu'il y a a regarder, ce qu'on pourrait faire, pourquoi ; puis
   * les hypotheses qui fondent le tout.
   *
   * Titulaire : celui de la barre du haut s'il en est un ; sinon le dernier
   * choisi ici, ou le premier qui a un profil, ou le premier du referentiel.
   * Les constats, eux, suivent toujours la barre du haut, famille comprise.
   *
   * Porte de static/modules/tabs/advisor.js, balisage a l'identique.
   */
  import { onDestroy } from 'svelte';
  import { api } from '/static/modules/api.js';
  import { fmtPct } from '/static/modules/utils.js';
  import Constats from './Constats.svelte';
  import Profil from './Profil.svelte';
  import Objectifs from './Objectifs.svelte';
  import Allocation from './Allocation.svelte';
  import Macro from './Macro.svelte';
  import Propositions from './Propositions.svelte';
  import type { Objectif, Profil as UnProfil } from './types';

  let { titulaires = [], owner = null, date = null, masque = false, visite = 0 }: {
    titulaires?: string[]; owner?: string | null; date?: string | null; masque?: boolean; visite?: number;
  } = $props();

  // ── Titulaire et donnees de son profil ─────────────────────────────────
  let proprietaire = $state<string | null>(null);
  let profils = $state(new Set<string>());
  let profil = $state<UnProfil | null>(null);
  let objectifs = $state<Objectif[]>([]);
  let version = $state(0);
  // Les profils existants d'abord : ouvrir celui d'un enfant qui n'en a pas
  // montrait un formulaire vide, et demander un profil absent renvoyait un 404.
  $effect(() => {
    void visite;
    const o = owner, liste = titulaires;
    api<{ owner: string }[]>('GET', '/api/advisor/profiles', null, { silent: true })
      .catch(() => [] as { owner: string }[])
      .then(l => {
        profils = new Set((l || []).map(p => p.owner));
        if (o && liste.includes(o)) proprietaire = o;
        else if (!proprietaire || !liste.includes(proprietaire)) proprietaire = liste.find(x => profils.has(x)) || liste[0] || null;
        version++;
      });
  });
  let jeton = 0;
  $effect(() => {
    void version;
    const p = proprietaire;
    if (!p) return;
    const j = ++jeton, enc = encodeURIComponent(p);
    Promise.all([
      profils.has(p) ? api<UnProfil>('GET', `/api/advisor/profiles/${enc}`, null, { silent: true }).catch(() => null) : Promise.resolve(null),
      api<Objectif[]>('GET', `/api/advisor/profiles/${enc}/objectives`, null, { silent: true }).catch(() => [] as Objectif[]),
    ]).then(([pr, ob]) => { if (j === jeton) { profil = pr; objectifs = ob; } });
  });
  async function rechargerObjectifs() {
    if (!proprietaire) return;
    objectifs = await api<Objectif[]>('GET', `/api/advisor/profiles/${encodeURIComponent(proprietaire)}/objectives`, null, { silent: true })
      .catch(() => [] as Objectif[]);
  }
  const profilEnregistre = () => { if (proprietaire) profils = new Set(profils).add(proprietaire); version++; };

  // ── Consommation de l'API Claude ───────────────────────────────────────
  interface Usage { days: { calls: number }[]; month_total_usd?: number; budget_usd?: number | null; mock_mode?: boolean }
  let usage = $state<Usage | null>(null);
  $effect(() => {
    void version;
    api<Usage>('GET', '/api/advisor/usage', null, { silent: true }).then(d => { usage = d; }).catch(() => {});
  });
  const depense = $derived(usage?.month_total_usd || 0);
  const budget = $derived(usage?.budget_usd);
  const part = $derived(budget && budget > 0 ? Math.min(100, depense / budget * 100) : null);

  // ── Navigation laterale : la section active est la derniere dont le haut
  // a passe sous la barre figee. Trier par proportion visible desavantageait
  // les sections longues.
  const SECTIONS = [['adv-constats', 'Constats'], ['adv-proposals', 'Propositions'], ['adv-allocation', 'Allocation'],
                    ['adv-macro', 'Macro'], ['adv-profile', 'Profil'], ['adv-objectives', 'Objectifs']];
  let active = $state('adv-constats');
  let attente = 0;
  function marquer() {
    const barre = (document.querySelector('.page-head')?.getBoundingClientRect().bottom || 0) + 24;
    const secs = SECTIONS.map(([id]) => document.getElementById(id)).filter(Boolean) as HTMLElement[];
    if (!secs.length) return;
    const ordonnees = secs.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
    let a = ordonnees[0];
    ordonnees.forEach(s => { if (s.getBoundingClientRect().top <= barre) a = s; });
    active = a.id;
  }
  const surDefilement = () => { cancelAnimationFrame(attente); attente = requestAnimationFrame(marquer); };
  $effect(() => {
    window.addEventListener('scroll', surDefilement, { passive: true });
    marquer();
    return () => window.removeEventListener('scroll', surDefilement);
  });
  onDestroy(() => cancelAnimationFrame(attente));
  function aller(e: MouseEvent, id: string) {
    const cible = document.getElementById(id);
    if (!cible) return;
    e.preventDefault();
    cible.scrollIntoView({ behavior: 'smooth', block: 'start' });
    active = id;
  }
</script>

<div class="page-header"><h1>Conseil patrimonial</h1></div>
<div class="advisor-disclaimer">
  <strong>Outil personnel à vocation pédagogique.</strong>
  Ne constitue pas un conseil en investissement réglementé.
  Les propositions sont générées par des règles automatiques, à croiser avec votre propre jugement ou celui d'un conseiller CIF.
</div>

<div class="advisor-layout">
  <aside class="advisor-sidebar" aria-label="Sections du conseil">
    {#each SECTIONS as [id, lib] (id)}
      <a href="#{id}" class="advisor-sidebar-link" class:is-active={active === id} data-anchor={id} onclick={e => aller(e, id)}>{lib}</a>
    {/each}
  </aside>
  <div class="advisor-content">
    <Constats {owner} {date} {masque} {visite} />
    <Profil {titulaires} bind:proprietaire {profil} onEnregistre={profilEnregistre} />
    <Objectifs {proprietaire} {objectifs} onRecharger={rechargerObjectifs} />
    <Allocation {proprietaire} avecProfil={!!profil} {version} {masque} />
    <Macro {version} />
    <Propositions {proprietaire} {version} {masque} />

    <div class="card" id="adv-usage">
      <h2>Consommation API Claude</h2>
      <div id="advisor-usage-summary" class="text-muted" style="font-size:var(--fs-sm)">
        {#if usage}
          Ce mois : <strong>{depense.toFixed(4)} $</strong>{#if usage.mock_mode}{' '}<span class="h-badge h-badge-muted">mock</span>{/if}
          · Aujourd'hui : {usage.days.length ? usage.days[usage.days.length - 1].calls : 0} appel(s)
          {#if budget != null && budget > 0 && part != null}
            <div style="margin-top:var(--esp-8)">
              <div style="height:6px;background:var(--bg);border-radius:3px;overflow:hidden;border:1px solid var(--border)">
                <div style="height:100%;width:{part}%;background:{part >= 100 ? 'var(--danger)' : part >= 80 ? 'var(--warning)' : 'var(--primary)'};transition:width .25s"></div>
              </div>
              <div style="font-size:var(--fs-2xs);color:var(--text-muted);margin-top:var(--esp-4)">
                {depense.toFixed(4)} $ / {budget.toFixed(2)} $ ({fmtPct(part, 0)})
              </div>
            </div>
            {#if part >= 80 && part < 100}
              <div class="advisor-budget-warning" style="margin-top:var(--esp-8);padding:var(--esp-6) var(--esp-10);border-left:3px solid var(--warning);background:rgba(234,179,8,.1);font-size:var(--fs-xs);border-radius:4px">
                Budget mensuel consommé à {fmtPct(part, 0)}. Les prochains appels Claude
                passeront toujours, mais envisagez d'augmenter <code>ADVISOR_BUDGET_USD</code>.
              </div>
            {:else if part >= 100}
              <div class="advisor-budget-warning" style="margin-top:var(--esp-8);padding:var(--esp-6) var(--esp-10);border-left:3px solid var(--danger);background:rgba(239,68,68,.1);font-size:var(--fs-xs);border-radius:4px">
                <strong>Budget mensuel dépassé.</strong> Les prochains appels Claude seront bloqués
                jusqu'à augmentation de <code>ADVISOR_BUDGET_USD</code> ou mois suivant.
              </div>
            {/if}
          {/if}
        {/if}
      </div>
    </div>
  </div>
</div>
