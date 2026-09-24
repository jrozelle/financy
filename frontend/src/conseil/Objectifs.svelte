<script lang="ts">
  /**
   * Objectifs patrimoniaux du titulaire, multi-horizons : une ligne editable
   * par projet, enregistree ou supprimee a part.
   *
   * Porte de static/modules/tabs/advisor.js (_renderObjectives et suivants).
   */
  import { api } from '/static/modules/api.js';
  import { esc, parseLocaleNumber } from '/static/modules/utils.js';
  import { toast, confirmDialog } from '/static/modules/dialogs.js';
  import type { Objectif } from './types';

  let { proprietaire = null, objectifs = [], onRecharger }: {
    proprietaire?: string | null; objectifs?: Objectif[]; onRecharger: () => Promise<void>;
  } = $props();

  interface Ligne { id: number; label: string; montant: string; horizon: string; priorite: string }
  let lignes = $state<Ligne[]>([]);
  $effect.pre(() => {
    lignes = objectifs.map(o => ({ id: o.id, label: o.label || '', montant: String(o.target_amount ?? ''),
                                   horizon: String(o.horizon_years ?? ''), priorite: String(o.priority) }));
  });

  async function ajouter() {
    if (!proprietaire) return;
    try {
      await api('POST', `/api/advisor/profiles/${encodeURIComponent(proprietaire)}/objectives`,
                { label: 'Nouvel objectif', horizon_years: 10, priority: 3 });
      await onRecharger();
    } catch { /* toast deja affiche */ }
  }
  async function enregistrer(l: Ligne) {
    const payload = {
      label: l.label.trim(),
      target_amount: l.montant ? parseLocaleNumber(l.montant) : null,
      horizon_years: l.horizon ? parseInt(String(parseLocaleNumber(l.horizon)), 10) : null,
      priority: parseInt(l.priorite),
    };
    if (!payload.label) { toast('Libellé requis', 'error'); return; }
    try {
      await api('PATCH', `/api/advisor/objectives/${l.id}`, payload);
      toast('Objectif enregistré', 'success');
    } catch { /* toast deja affiche */ }
  }
  async function supprimer(l: Ligne) {
    if (!await confirmDialog('Supprimer l\'objectif ?', `<strong>${esc(l.label)}</strong>`, { confirmText: 'Supprimer' })) return;
    try {
      await api('DELETE', `/api/advisor/objectives/${l.id}`);
      await onRecharger();
    } catch { /* toast deja affiche */ }
  }
</script>

<div class="card" id="adv-objectives">
  <h2>Objectifs</h2>
  <p class="text-muted" style="font-size:12.5px;margin-bottom:.875rem">
    Projets patrimoniaux multi-horizons. Pris en compte pour affiner l'allocation cible en phase ultérieure.
  </p>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex : zone defilante, atteignable au clavier -->
  <div class="advisor-objectives-wrap" tabindex="0" role="region" aria-label="Objectifs">
    <table class="data-table" id="advisor-objectives-table">
      <thead>
        <tr>
          <th>Libellé</th>
          <th class="num">Montant cible (€)</th>
          <th class="num">Horizon (ans)</th>
          <th>Priorité</th>
          <th></th>
        </tr>
      </thead>
      <tbody id="advisor-objectives-tbody">
        {#each lignes as l (l.id)}
          <tr data-oid={l.id}>
            <td><input type="text" class="obj-label" maxlength="200" bind:value={l.label}></td>
            <td class="num"><input type="text" inputmode="decimal" class="obj-amount" step="100" min="0" bind:value={l.montant}></td>
            <td class="num"><input type="text" inputmode="numeric" class="obj-horizon" step="1" min="0" max="100" bind:value={l.horizon}></td>
            <td>
              <select class="obj-priority" bind:value={l.priorite}>
                {#each ['1', '2', '3', '4', '5'] as p (p)}<option value={p}>{p}</option>{/each}
              </select>
            </td>
            <td>
              <button type="button" class="btn-icon" data-action="save-obj" onclick={() => enregistrer(l)}>Enregistrer</button>
              <button type="button" class="btn-icon del" data-action="del-obj" onclick={() => supprimer(l)}>Supprimer</button>
            </td>
          </tr>
        {:else}
          <tr><td colspan="5" style="text-align:center;padding:1rem;color:var(--text-muted);font-style:italic">Aucun objectif. Ajoutez une ligne pour documenter vos projets patrimoniaux.</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
  <button type="button" class="btn btn-secondary btn-sm" id="btn-add-objective" style="margin-top:.75rem" onclick={ajouter}>+ Ajouter un objectif</button>
</div>
