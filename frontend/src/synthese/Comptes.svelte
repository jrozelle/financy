<script lang="ts">
  /**
   * « Vos comptes » : valeur, apports, frais et rendement, cote a cote.
   *
   * Le rendement affiche est le TRI : ce que l'argent a rapporte par an,
   * selon la date ou il a ete verse. Le TWR reste dans l'onglet Performance.
   * Tout vient de /api/performance : rien n'est recalcule ici.
   *
   * Porte de static/modules/tabs/comptes.js, balisage a l'identique.
   */
  import { api } from '/static/modules/api.js';
  import { fmt, fmtPct, fmtDate, sortArr } from '/static/modules/utils.js';
  import { estFinancier } from '/static/modules/categories.js';
  import EnTeteTri from '../commun/EnTeteTri.svelte';
  import { ecran } from '../commun/ecran.svelte';

  interface Groupe {
    label?: string; value: number; flux_net?: number; fees?: number; status?: string; reason?: string;
    categories?: string[]; tri?: number | null; tri_periode?: number | null; tri_jours?: number;
    suspect_periods?: unknown[];
  }
  interface Reponse { groups?: Groupe[]; global?: Groupe; first_date?: string }

  let { hote }: { hote: HTMLElement } = $props();

  let donnees = $state<Reponse | null>(null);
  let tri = $state<{ cle: string | null; sens: number }>({ cle: null, sens: 1 });
  let jeton = 0;

  /** Recharge pour le titulaire et l'arrete affiches : la carte suit l'arrete. */
  export async function recharger(owner: string | null, date: string | null) {
    const j = ++jeton;
    const q = new URLSearchParams();
    if (owner && owner !== 'Famille') q.set('owner', owner);
    if (date) q.set('fin', date);
    try {
      const d = await api<Reponse>('GET', `/api/performance?${q}`, null, { silent: true });
      if (j === jeton) donnees = d;
    } catch { if (j === jeton) donnees = null; }
  }

  // Une maison ou des parts de SCI ne sont pas des comptes : hors du tableau,
  // mais comptees sous le titre. Un compte cloture non plus : le lister avec
  // son solde de cloture le ferait passer pour un avoir du jour.
  const tous = $derived((donnees?.groups || []).filter(g => g.value && estFinancier(g.categories)));
  const hors = $derived((donnees?.groups || []).length - tous.length);
  const groupes = $derived(tous.filter(g => g.status !== 'closed'));
  const clotures = $derived(tous.length - groupes.length);
  $effect(() => { hote.style.display = groupes.length ? '' : 'none'; });

  /** Le TRI annuel ; a defaut — moins de six mois — le rendement sur la
   *  periode, avec sa duree : annualiser deux mois serait mentir. */
  function rendement(g: Groupe | undefined) {
    if (!g) return null;
    if (g.tri != null) return { taux: g.tri * 100, duree: 'par an' };
    if (g.tri_periode != null) return { taux: g.tri_periode * 100, duree: `sur ${g.tri_jours} j` };
    return null;
  }
  const lignes = $derived(sortArr(groupes.map(g => {
    const r = g.status === 'ok' ? rendement(g) : null;
    return { ...g, _r: r, _taux: r ? r.taux : null };
  }), tri.cle, tri.sens));
  const total = $derived(groupes.reduce((s, g) => s + (g.value || 0), 0));
  const frais = $derived(groupes.reduce((s, g) => s + (g.fees || 0), 0));
  const pied = $derived(rendement(donnees?.global));
  const basculer = (cle: string) => { tri = tri.cle === cle ? { cle, sens: -tri.sens } : { cle, sens: 1 }; };
  const pluriel = (n: number, mot: string) => `${n} ${mot}${n > 1 ? 's' : ''}`;
  // Au telephone, la carte faisait deux ecrans : les cinq premiers comptes,
  // le reste sur demande. Le pied, lui, totalise toujours tous les comptes.
  const VISIBLES = 5;
  let tout = $state(false);
  const coupe = $derived(ecran.telephone && !tout && lignes.length > VISIBLES + 1);
  const affiches = $derived(coupe ? lignes.slice(0, VISIBLES) : lignes);
</script>

{#if groupes.length}
  <div class="card-head">
    <div>
      <h2>Vos comptes</h2>
      <p class="card-sub">Ce que votre argent a rapporté, selon la date de vos versements · frais déduits{
        donnees?.first_date ? ` · depuis le ${fmtDate(donnees.first_date)}` : ''}{
        clotures ? ` · ${pluriel(clotures, 'compte')} ${clotures > 1 ? 'clôturés' : 'clôturé'}, non ${clotures > 1 ? 'listés' : 'listé'}` : ''}{
        hors ? ` · ${pluriel(hors, 'ligne')} hors placements financiers (immobilier, biens, sociétés), à voir dans Répartition` : ''}</p>
    </div>
    <button type="button" class="link-carte" data-tab-switch="performance">Tout voir</button>
  </div>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex : zone qui defile, atteignable au clavier -->
  <div class="comptes-wrap" tabindex="0" role="region" aria-label="Vos comptes">
    <table class="comptes">
      <thead id="comptes-thead">
        <tr>
          <EnTeteTri cle="label" {tri} surTri={basculer}>Compte</EnTeteTri>
          <EnTeteTri cle="value" {tri} surTri={basculer}>Valeur</EnTeteTri>
          <EnTeteTri cle="flux_net" {tri} surTri={basculer}>Apports</EnTeteTri>
          <EnTeteTri cle="fees" {tri} surTri={basculer}>Frais</EnTeteTri>
          <EnTeteTri cle="_taux" {tri} surTri={basculer}>Rendement</EnTeteTri>
        </tr>
      </thead>
      <tbody id="comptes-tbody">
        {#each affiches as g, i (`${g.label}-${i}`)}
          {@const classe = g._taux == null ? 'neutre' : g._taux >= 0 ? 'hausse' : 'baisse'}
          <tr>
            <td><span class="compte-n">{g.label || ''}</span></td>
            <td class="num">{fmt(g.value)}</td>
            <td class="num">{g.flux_net ? fmt(g.flux_net) : '—'}</td>
            <td class="num">{g.fees ? fmt(g.fees) : '—'}</td>
            <!-- Un compte non mesurable garde sa ligne et sa valeur ; sa raison
                 est dite. Un taux sur un journal incomplet le dit aussi. -->
            <td>{#if g._r}<span class="taux taux--{classe}">{fmtPct(g._r.taux, 1, true)}</span> <span
                class="taux-duree">{g._r.duree}</span>{#if g.suspect_periods?.length} <span
                class="taux-alerte">écart inexpliqué : un flux manque au journal ?</span>{/if}
              {:else}<span class="taux taux--neutre">{g.reason || 'hors calcul'}</span>{/if}</td>
          </tr>
        {/each}
      </tbody>
      <tfoot>
        <tr>
          <td>{groupes.length} comptes</td>
          <td class="num">{fmt(total)}</td>
          <td class="num"></td>
          <td class="num">{frais ? fmt(frais) : '—'}</td>
          <td>{#if pied}<span class="taux taux--{pied.taux >= 0 ? 'hausse' : 'baisse'}">{fmtPct(pied.taux, 1, true)}</span> <span
              class="taux-duree">{pied.duree}</span>{/if}</td>
        </tr>
      </tfoot>
    </table>
  </div>
  {#if ecran.telephone && lignes.length > VISIBLES + 1}
    <button type="button" class="btn-link mv-plus" aria-expanded={tout} aria-controls="comptes-tbody"
            onclick={() => tout = !tout}>{tout ? 'Réduire' : `Voir les ${lignes.length - VISIBLES} autres comptes`}</button>
  {/if}
{/if}
