<script lang="ts">
  /**
   * « Si vous vendiez tout » : l'impot encore latent sur les plus-values.
   *
   * Trois chiffres et une reserve, en clair sous le montant : l'impot ne porte
   * que sur la part du patrimoine dont l'assiette est sure, et un montant
   * presente seul laisserait croire a un patrimoine quasi non taxe. Sous la
   * moitie couverte, pas d'estimation : la carte dit pourquoi, et ce qui
   * manque. Une enveloppe ecartee garde sa valeur et sa raison.
   *
   * Porte de static/modules/tabs/fiscalite.js, balisage a l'identique.
   */
  import { api } from '/static/modules/api.js';
  import { fmt, fmtPct } from '/static/modules/utils.js';

  interface Enveloppe { enveloppe: string; valeur: number; plus_value?: number; impot?: number;
                        motif?: string; reserve?: string; abattement?: number }
  interface Ecartee { enveloppe: string; valeur: number; motif: string }
  interface Reponse { date?: string; brut: number; impot?: number; net_apres_impot?: number;
                      valeur_ecartee?: number; enveloppes?: Enveloppe[]; non_calculees?: Ecartee[] }
  interface Contrat { owner: string; envelope: string; establishment?: string; date_effet?: string | null;
                      numero?: string; source?: string; maturite?: string; seuil_ans: number; mature?: boolean }

  let { hote, masque = false }: { hote: HTMLElement; masque?: boolean } = $props();

  /** Part minimale du patrimoine couverte pour que la carte ait un sens. */
  const COUVERTURE_MIN = 0.5;

  let donnees = $state<Reponse | null>(null);
  let jeton = 0;
  let parametres = { owner: null as string | null, date: null as string | null };

  export async function recharger(owner: string | null, date: string | null) {
    parametres = { owner, date };
    const j = ++jeton;
    const p = new URLSearchParams();
    if (date) p.set('date', date);
    if (owner && owner !== 'Famille') p.set('owner', owner);
    let d: Reponse | null = null;
    try { d = await api<Reponse>('GET', `/api/impot-latent?${p}`, null, { silent: true }); } catch { /* masquee */ }
    if (j === jeton) donnees = d;
  }

  const visible = $derived(!!donnees?.brut);
  $effect(() => { hote.style.display = visible ? '' : 'none'; });
  const couvert = $derived(donnees ? donnees.brut - (donnees.valeur_ecartee || 0) : 0);
  const couverture = $derived(donnees?.brut ? couvert / donnees.brut : 0);
  const nb = $derived((donnees?.non_calculees || []).length);
  const dateFr = (v?: string | null) => (v || '').split('-').reverse().join('/');

  // ── Detail depliable, et dates d'effet des contrats ─────────────────────
  let detailOuvert = $state(false);
  let contrats = $state<Contrat[] | null>(null);
  let dates = $state<string[]>([]);
  async function basculerDetail() {
    detailOuvert = !detailOuvert;
    if (detailOuvert && contrats === null) {
      try {
        const d = await api<{ contrats?: Contrat[] }>('GET', '/api/contrats', null, { silent: true });
        contrats = d.contrats || [];
        dates = contrats.map(c => c.date_effet || '');
      } catch { /* rien a montrer */ }
    }
  }
  async function enregistrerDates() {
    if (!contrats) return;
    const lignes = contrats.map((c, i) => ({ owner: c.owner, envelope: c.envelope, establishment: c.establishment,
      date_effet: dates[i] || null, numero: c.numero, source: c.source }));
    try {
      await api('PUT', '/api/contrats', { contrats: lignes });
      contrats = null; detailOuvert = false;
      await recharger(parametres.owner, parametres.date);
    } catch { /* toast deja affiche */ }
  }
</script>

{#snippet tableau(d: Reponse)}
  {#if d.enveloppes?.length}
    <table class="fisc-table">
      <thead>
        <tr>
          <th scope="col">Enveloppe</th>
          <th scope="col">Valeur</th>
          <th scope="col">Plus-value</th>
          <th scope="col">Impôt</th>
          <th scope="col">Régime</th>
        </tr>
      </thead>
      <tbody>
        {#each d.enveloppes as l, i (i)}
          <tr>
            <td>{l.enveloppe}</td>
            <td class="num">{fmt(l.valeur)}</td>
            <td class="num">{l.plus_value ? fmt(l.plus_value) : '—'}</td>
            <td class="num">{l.impot ? fmt(l.impot) : '—'}</td>
            <td class="fisc-regime">
              {l.motif || ''}
              {#if l.reserve}<span class="fisc-reserve">{l.reserve}</span>{/if}
              {#if l.abattement}<span class="fisc-reserve">Abattement de {fmt(l.abattement)} appliqué</span>{/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
  {#if d.non_calculees?.length}
    <h3 class="fisc-h3">Hors calcul — {fmt(d.valeur_ecartee)}</h3>
    <ul class="fisc-ecartees">
      {#each d.non_calculees as e, i (i)}
        <li>
          <span class="fisc-ec-nom">{e.enveloppe}</span>
          <span class="fisc-ec-val">{fmt(e.valeur)}</span>
          <span class="fisc-ec-motif">{e.motif}</span>
        </li>
      {/each}
    </ul>
  {/if}
  <div id="fisc-contrats">
    {#if contrats?.length}
      <h3 class="fisc-h3">Ancienneté des contrats</h3>
      <table class="fisc-table fisc-contrats">
        <thead><tr><th scope="col">Contrat</th><th scope="col">Date d'effet</th><th scope="col">Échéance fiscale</th></tr></thead>
        <tbody>
          {#each contrats as c, i (i)}
            <tr data-i={i}>
              <td>{c.envelope} · {c.owner}{c.establishment ? ` · ${c.establishment}` : ''}</td>
              <td><input type="date" class="ref-input" bind:value={dates[i]}
                         aria-label="Date d'effet du contrat {c.envelope} de {c.owner}"></td>
              <td>{#if c.maturite}{c.seuil_ans} ans le {dateFr(c.maturite)}{c.mature ? ' — atteint' : ''}
                {:else}<span class="fisc-reserve">Sans date : supposé de plus de {c.seuil_ans} ans</span>{/if}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <button type="button" class="btn btn-secondary btn-sm" id="fisc-contrats-ok" onclick={enregistrerDates}>Enregistrer les dates</button>
    {/if}
  </div>
{/snippet}

{#key masque}
{#if visible && donnees}
  <div class="card-head">
    <div>
      <h2>Si vous vendiez tout</h2>
      <p class="card-sub">Impôt latent sur les plus-values, au {dateFr(donnees.date)}</p>
    </div>
  </div>
  {#if couverture < COUVERTURE_MIN}
    <p class="fisc-portee">
      Pas d'estimation : seul {fmtPct(couverture * 100, 0)} du patrimoine a une assiette sûre
      (versements saisis ou prix de revient des lignes), il en faudrait au moins la moitié. Un chiffre
      calculé sur le reste se lirait comme un total.
    </p>
    <button type="button" class="fisc-detail-btn" aria-expanded={detailOuvert} aria-controls="fisc-detail"
            onclick={basculerDetail}>Ce qui manque, enveloppe par enveloppe</button>
  {:else}
    <div class="fisc-chiffres">
      <div class="fisc-bloc">
        <span class="fisc-label">Patrimoine brut</span>
        <span class="fisc-val">{fmt(donnees.brut)}</span>
      </div>
      <div class="fisc-bloc fisc-bloc--impot">
        <span class="fisc-label">Impôt estimé</span>
        <span class="fisc-val">{donnees.impot ? '−' + fmt(donnees.impot) : fmt(0)}</span>
      </div>
      <div class="fisc-bloc fisc-bloc--net">
        <span class="fisc-label">Brut après impôt</span>
        <span class="fisc-val">{fmt(donnees.net_apres_impot)}</span>
      </div>
    </div>
    <p class="fisc-portee">
      Calculé sur <strong>{fmt(couvert)}</strong> du patrimoine, soit
      {fmtPct(couverture * 100, 0)}.{nb ? ` ${nb} enveloppe${nb > 1 ? 's' : ''} sans assiette
      sûre ${nb > 1 ? 'restent' : 'reste'} hors du calcul.` : ''}
      L'ancienneté des assurances-vie et des PEA vient de leur date d'effet ; un
      contrat sans date est supposé mature, au régime le plus favorable.
    </p>
    <button type="button" class="fisc-detail-btn" aria-expanded={detailOuvert} aria-controls="fisc-detail"
            onclick={basculerDetail}>Détail par enveloppe</button>
  {/if}
  <div class="fisc-detail" class:hidden={!detailOuvert} id="fisc-detail">{@render tableau(donnees)}</div>
{/if}
{/key}
