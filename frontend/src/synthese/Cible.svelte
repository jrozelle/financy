<script lang="ts">
  /**
   * « Ecart a la cible » : la part de chaque categorie, et l'ecart en POINTS
   * a l'allocation visee — « 31,3 % · −3,7 pt » dit tout, et le trait sur la
   * barre montre la cible sans avoir a la lire. Une categorie a net negatif
   * (SCI endettee) reste listee : filtree, les autres totaliseraient plus de
   * 100 % sans explication.
   *
   * Porte de static/modules/targets.js (renderAllocationTargets) ; la fenetre
   * de saisie des cibles y reste, et previent la carte (« cibles:modifiees »).
   */
  import { fmtPct } from '/static/modules/utils.js';
  import { loadTargets, openTargetsModal } from '/static/modules/targets.js';

  type Totaux = Record<string, { net?: number; gross?: number; by_owner?: Record<string, number>; by_owner_gross?: Record<string, number> }>;
  let { synthese = null, owner = 'Famille', categories = [] }: {
    synthese?: { family?: { net?: number; gross?: number }; totals_by_owner?: Record<string, { net?: number; gross?: number }>;
                 totals_by_category?: Totaux } | null;
    owner?: string; categories?: string[];
  } = $props();

  let cibles = $state<Record<string, number>>({});
  let mode = $state<'net' | 'brut'>('net');
  const charger = async () => { cibles = { ...(await loadTargets()) }; };
  $effect(() => {
    charger();
    const rappel = () => charger();
    window.addEventListener('cibles:modifiees', rappel);
    return () => window.removeEventListener('cibles:modifiees', rappel);
  });

  const lignes = $derived.by(() => {
    const syn = synthese;
    if (!syn?.totals_by_category) return null;
    const famille = owner === 'Famille', brut = mode === 'brut';
    const base = brut ? (famille ? (syn.family?.gross || 0) : (syn.totals_by_owner?.[owner]?.gross || 0))
                      : (famille ? (syn.family?.net || 0) : (syn.totals_by_owner?.[owner]?.net || 0));
    const valeur = (cd: Totaux[string]) => brut ? (famille ? (cd.gross || 0) : (cd.by_owner_gross?.[owner] || 0))
                                                : (famille ? (cd.net || 0) : (cd.by_owner?.[owner] || 0));
    const toutes = [...new Set([...categories, ...Object.keys(syn.totals_by_category)])];
    return toutes.map(cat => {
      const val = valeur(syn.totals_by_category![cat] || {});
      const reel = base > 0 ? (val / base) * 100 : 0;
      const cible = cibles[cat] || 0;
      return { cat, val, reel, cible, ecart: reel - cible };
    }).filter(r => Math.abs(r.val) >= 1 || r.cible > 0).sort((a, b) => b.val - a.val);
  });

  /** Ecart en points de pourcentage, a la francaise : « +2,5 pt ». */
  const nf = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const points = (v: number) => {
    const s = nf.format(Math.abs(v));
    return `${s === '0,0' ? '' : v > 0 ? '+' : '−'}${s} pt`;
  };
</script>

<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.875rem;gap:.5rem">
  <h2 style="margin:0">Écart à la cible</h2>
<p class="card-sub">Le trait marque l’allocation visée</p>
  <div style="display:flex;align-items:center;gap:.5rem">
    <span id="alloc-mode-switch"><span style="display:inline-flex;border:1px solid var(--border);border-radius:6px;overflow:hidden;font-size:12px;vertical-align:middle">
      {#each ['net', 'brut'] as m (m)}
        <button type="button" data-alloc-mode={m} onclick={() => mode = m as 'net' | 'brut'}
                style="padding:.2rem .6rem;border:none;cursor:pointer;background:{m === mode ? 'var(--primary)' : 'transparent'};color:{m === mode ? 'var(--on-accent)' : 'var(--text)'}">{m === 'net' ? 'Net' : 'Brut'}</button>
      {/each}
    </span></span>
    <button class="btn btn-secondary btn-sm" id="btn-edit-targets" onclick={() => openTargetsModal()}>Modifier cibles</button>
  </div>
</div>
<div id="allocation-targets">
  {#if lignes === null}
    <p class="text-muted" style="font-size:13px">Aucune donnée.</p>
  {:else if !lignes.length}
    <p class="text-muted" style="font-size:13px">Cliquez sur "Modifier cibles" pour configurer.</p>
  {:else}
    <div class="cible-liste">
      {#each lignes as r (r.cat)}
        {@const ecart = r.cible === 0 ? null : r.ecart}
        {@const classe = ecart === null ? '' : ecart > 2 ? 'trop' : ecart < -2 ? 'pas-assez' : 'ok'}
        <div class="cible-ligne">
          <span class="cible-n">{r.cat}</span>
          <span class="cible-v">
            <span class="num">{fmtPct(r.reel)}</span>
            {#if ecart === null}<span class="cible-none">pas de cible</span>
            {:else}<span class="cible-ecart cible-ecart--{classe}">{points(ecart)}</span>{/if}
          </span>
          <span class="cible-track">
            <span class="cible-fill" style:width="{Math.max(0, Math.min(100, r.reel)).toFixed(1)}%"></span>
            {#if r.cible}<span class="cible-marque" style:left="{Math.min(100, r.cible).toFixed(1)}%" aria-hidden="true"></span>{/if}
          </span>
        </div>
      {/each}
    </div>
  {/if}
</div>
