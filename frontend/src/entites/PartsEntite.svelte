<script lang="ts">
  /**
   * Les parts detenues, valorisees au prix de retrait. Les prix se mettent a
   * jour a chaque bulletin trimestriel ; sans prix de retrait publie, il est
   * estime a la souscription moins 10 % de commission.
   *
   * Porte de static/modules/tabs/tresorerie.js (_parts), balisage a
   * l'identique.
   */
  import { api } from '/static/modules/api.js';
  import { fmt, parseLocaleNumber } from '/static/modules/utils.js';
  import { toast, promptDialog } from '/static/modules/dialogs.js';
  import type { Bloc, Part } from './donnees-tresorerie';

  let { b, idx, onRecharger }: { b: Bloc; idx: number; onRecharger: () => Promise<void> } = $props();

  const CHAMPS = [['parts', 'Nombre de parts'], ['montant_souscrit', 'Prix payé'],
                  ['prix_souscription', 'Prix de souscription'], ['prix_retrait', 'Prix de retrait']] as const;
  type Champ = typeof CHAMPS[number][0];
  interface Ligne { nom: string; saisie: Record<Champ | 'date_prix', string>; lue: Part | null }

  const versLigne = (l: Part): Ligne => ({ nom: l.nom, lue: l, saisie: {
    parts: String(l.parts ?? ''), montant_souscrit: String(l.montant_souscrit ?? ''),
    prix_souscription: String(l.prix_souscription ?? ''), prix_retrait: String(l.prix_retrait ?? ''),
    date_prix: l.date_prix || '' } });
  // Les saisies repartent des donnees a chaque rechargement.
  let lignes = $state<Ligne[]>([]);
  $effect.pre(() => { lignes = (b.parts?.lignes || []).map(versLigne); });
  const lues = $derived(b.parts?.lignes || []);

  async function ajouter() {
    const nom = (await promptDialog('Nom de la part', { placeholder: 'ex. : Immorente', confirmText: 'Ajouter' }))?.trim();
    if (!nom) return;
    lignes.push({ nom, lue: null, saisie: { parts: '', montant_souscrit: '', prix_souscription: '', prix_retrait: '', date_prix: '' } });
  }

  async function enregistrer() {
    const parts = lignes.map(l => {
      const r: Record<string, string | number | null> = { nom: l.nom };
      for (const [k] of CHAMPS) r[k] = l.saisie[k].trim() === '' ? null : parseLocaleNumber(l.saisie[k], null);
      r.date_prix = l.saisie.date_prix || null;
      return r;
    });
    try {
      await api('PUT', `/api/entites/${encodeURIComponent(b.entite)}/parts`, { parts });
      toast('Prix enregistrés : la prochaine mise à jour proposera la valeur au prix de retrait', 'success');
      onRecharger();
    } catch { /* toast deja affiche */ }
  }
</script>

<details class="treso-parts" open={!lues.length}>
  <summary>Parts détenues{lues.length ? ` : ${fmt(b.parts?.valeur_retrait)} au prix de retrait` : ''}</summary>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex : zone defilante, atteignable au clavier -->
  <div class="table-scroll" tabindex="0" role="region" aria-label="Parts de {b.entite}">
    <table class="data-table" data-parts={idx}>
      <thead><tr><th>Part</th><th class="num">Nombre</th><th class="num">Prix payé</th>
        <th class="num">Souscription</th><th class="num">Retrait</th><th class="num">Valeur de retrait</th><th>Prix au</th></tr></thead>
      <tbody>
        {#each lignes as l, j (j)}
          <tr data-nom={l.nom}>
            <td>{l.nom}</td>
            {#each CHAMPS as [k, lib] (k)}
              <td class="num"><input type="text" inputmode="decimal" class="ref-input treso-prix" data-k={k}
                bind:value={l.saisie[k]} aria-label="{lib} de {l.nom}">{#if k === 'prix_retrait' && l.lue?.retrait_estime}<span
                class="treso-estime">estimé à {fmt(l.lue.prix_retrait_retenu)}</span>{/if}</td>
            {/each}
            <td class="num">{l.lue?.valeur_retrait != null ? fmt(l.lue.valeur_retrait) : '—'}</td>
            <td><input type="date" class="ref-input" data-k="date_prix" bind:value={l.saisie.date_prix} aria-label="Date des prix de {l.nom}"></td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <div class="treso-parts-actions">
    <button type="button" class="btn btn-secondary btn-sm" data-parts-ajouter={idx} onclick={ajouter}>Ajouter une part</button>
    <button type="button" class="btn btn-primary btn-sm" data-parts-enregistrer={idx} onclick={enregistrer}>Enregistrer les prix</button>
  </div>
</details>
