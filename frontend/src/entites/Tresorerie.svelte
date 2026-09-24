<script lang="ts">
  /**
   * Tresorerie des entites, lue sur leurs releves bancaires : pour une SCI a
   * credit, la mesure du levier. Les loyers couvrent-ils l'echeance, combien
   * les associes remettent-ils, et combien de capital ce complement rembourse.
   *
   * Import en deux temps : chaque releve est lu et verifie (il doit redonner
   * son solde final), puis enregistre sur le compte de l'entite choisie.
   *
   * Porte de static/modules/tabs/tresorerie.js, balisage a l'identique.
   */
  import { fmt, fmtDate } from '/static/modules/utils.js';
  import { toast } from '/static/modules/dialogs.js';
  import BlocTresorerie from './BlocTresorerie.svelte';
  import type { Tresorerie } from './donnees-tresorerie';

  let { donnees = null, entites = [], masque = false, onRecharger }: {
    donnees?: Tresorerie | null; entites?: string[]; masque?: boolean; onRecharger: () => Promise<void>;
  } = $props();

  const blocs = $derived((donnees?.entites || []).filter(b => b.periode));

  // ── Import de releves ──────────────────────────────────────────────────
  interface Releve { banque: string; debut: string; fin: string; operations: number; solde_final: number; entite_proposee?: string | null }
  let champ = $state<HTMLInputElement>();
  let lus = $state<{ f: File; r: Releve }[]>([]);
  let refus = $state<string[]>([]);
  let entite = $state('');

  async function envoyer(fichier: File, etape: 'preview' | 'commit', ent?: string) {
    const fd = new FormData();
    fd.append('file', fichier);
    if (ent) fd.append('entity', ent);
    const meta = document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]');
    const r = await fetch(`/api/entites/releves?step=${etape}`, { method: 'POST', body: fd,
      headers: meta ? { 'X-CSRF-Token': meta.content } : {} });
    const d = await r.json().catch(() => null);
    if (!r.ok) throw new Error(d?.error || `Import refusé (${r.status})`);
    return d;
  }

  async function lire(fichiers: File[]) {
    const ok: { f: File; r: Releve }[] = [], ko: string[] = [];
    for (const f of fichiers) {
      try { ok.push({ f, r: (await envoyer(f, 'preview')).releve }); }
      catch (e) { ko.push(`${f.name} : ${(e as Error).message}`); }
    }
    if (!ok.length) { lus = []; toast(ko[0] || 'Aucun relevé lisible', 'error'); return; }
    const proposee = ok.find(x => x.r.entite_proposee)?.r.entite_proposee;
    entite = proposee && entites.includes(proposee) ? proposee : entites[0] || '';
    lus = ok; refus = ko;
  }

  async function enregistrer() {
    let ajoutees = 0, deja = 0;
    try {
      for (const x of lus) {
        const d = await envoyer(x.f, 'commit', entite);
        ajoutees += d.ajoutees; deja += d.deja;
      }
    } catch (e) { toast((e as Error).message, 'error'); return; }
    lus = [];
    toast(`${ajoutees} opération${ajoutees > 1 ? 's' : ''} ajoutée${ajoutees > 1 ? 's' : ''}`
      + (deja ? `, ${deja} déjà connue${deja > 1 ? 's' : ''}` : ''), 'success');
    onRecharger();
  }
  const nbOps = $derived(lus.reduce((s, x) => s + x.r.operations, 0));
</script>

<div class="card" id="tresorerie-carte">
  <div class="card-head">
    <div>
      <h2>Trésorerie et levier</h2>
      <p class="card-sub">Ce que chaque entité reçoit, rembourse et coûte, lu sur ses relevés bancaires.</p>
    </div>
    <button type="button" class="btn btn-secondary btn-sm" id="treso-importer" onclick={() => champ?.click()}>Importer des relevés</button>
    <input type="file" id="treso-fichiers" accept="application/pdf" multiple hidden bind:this={champ}
           onchange={e => { const t = e.currentTarget; const f = [...(t.files || [])]; t.value = ''; lire(f); }}>
  </div>
  <div class="prets-apercu" id="treso-apercu" hidden={!lus.length}>
    {#if lus.length}
      <p><b>{lus.length} relevé{lus.length > 1 ? 's' : ''} vérifié{lus.length > 1 ? 's' : ''}</b>, {nbOps} opérations :
        chaque relevé redonne bien son solde final.</p>
      <ul class="treso-apercu-liste">{#each lus as x, j (j)}<li>{x.r.banque} · {fmtDate(x.r.debut)} → {fmtDate(x.r.fin)} ·
        {x.r.operations} opération{x.r.operations > 1 ? 's' : ''} · solde {fmt(x.r.solde_final)}</li>{/each}</ul>
      {#if refus.length}<p class="import-alerte">Écartés : {refus.join(' ; ')}</p>{/if}
      <div class="prets-apercu-champs">
        <label>Compte de l'entité <select id="treso-entite" class="filter-select" bind:value={entite}>
          {#each entites as e (e)}<option value={e}>{e}</option>{/each}</select></label>
        <button type="button" class="btn btn-primary btn-sm" id="treso-enregistrer" onclick={enregistrer}>Enregistrer</button>
        <button type="button" class="btn btn-secondary btn-sm" id="treso-annuler" onclick={() => lus = []}>Annuler</button>
      </div>
    {/if}
  </div>
  <div id="tresorerie-entites">
    {#if donnees}
      {#key masque}
      {#each blocs as b, i (b.entite)}
        <BlocTresorerie {b} idx={i} natures={donnees.natures} {onRecharger} />
      {:else}
        <p class="text-muted treso-vide">Importez les relevés du compte bancaire d'une SCI ou d'une holding :
          Financy en tire ce que l'entité reçoit, rembourse et coûte, et ce que ses associés y remettent.</p>
      {/each}
      {/key}
    {/if}
  </div>
</div>
