<script lang="ts">
  /**
   * Profil du titulaire : horizon, tolerance au risque, situation. Il fonde
   * l'allocation cible et les propositions ; l'enregistrer les recalcule.
   *
   * Porte de static/modules/tabs/advisor.js (_fillProfileForm, saveProfile).
   */
  import { api } from '/static/modules/api.js';
  import { parseLocaleNumber } from '/static/modules/utils.js';
  import { toast } from '/static/modules/dialogs.js';
  import type { Profil } from './types';

  let { titulaires = [], proprietaire = $bindable(null), profil = null, onEnregistre }: {
    titulaires?: string[]; proprietaire?: string | null; profil?: Profil | null; onEnregistre: () => void;
  } = $props();

  // Les champs repartent du profil charge a chaque changement de titulaire.
  let f = $state({ horizon: '', risque: '3', statut: '', retraite: '', enfants: '0', reserve: '', residence: false, lbo: false, notes: '' });
  $effect.pre(() => {
    void proprietaire;
    const p = profil || ({} as Partial<Profil>);
    f = { horizon: String(p.horizon_years ?? ''), risque: String(p.risk_tolerance ?? 3), statut: p.employment_type ?? '',
          retraite: String(p.pension_age ?? ''), enfants: String(p.children_count ?? 0), reserve: String(p.reserve_eur ?? ''),
          residence: !!p.main_residence_owned, lbo: !!p.has_lbo, notes: p.notes ?? '' };
  });
  const nombre = (v: string) => {
    if (v === '' || v == null) return null;
    const n = parseLocaleNumber(v);
    return isNaN(n) ? null : n;
  };

  async function enregistrer(e: SubmitEvent) {
    e.preventDefault();
    if (!proprietaire) return;
    const payload = {
      horizon_years: nombre(f.horizon), risk_tolerance: nombre(f.risque), employment_type: f.statut || null,
      pension_age: nombre(f.retraite), children_count: nombre(f.enfants), reserve_eur: nombre(f.reserve),
      main_residence_owned: f.residence, has_lbo: f.lbo, notes: f.notes.trim(),
    };
    try {
      await api('PUT', `/api/advisor/profiles/${encodeURIComponent(proprietaire)}`, payload);
      toast('Profil enregistré', 'success');
      onEnregistre();
    } catch { /* toast deja affiche */ }
  }
</script>

<div class="card" id="adv-profile">
  <h2>Profil du titulaire</h2>
  <div style="margin-bottom:var(--esp-12)">
    <label for="advisor-owner-select" style="font-size:var(--fs-xs);color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.04em">Titulaire</label>
    <select id="advisor-owner-select" class="filter-select" style="margin-left:var(--esp-8)" aria-label="Titulaire du profil" bind:value={proprietaire}>
      {#each titulaires as o (o)}<option value={o}>{o}</option>{/each}
    </select>
  </div>
  <form id="advisor-profile-form" onsubmit={enregistrer}>
    <div class="form-grid">
      <div class="form-group">
        <label for="adv-horizon">Horizon (années)</label>
        <input type="text" inputmode="numeric" id="adv-horizon" min="0" max="100" step="1" bind:value={f.horizon}>
      </div>
      <div class="form-group">
        <label for="adv-risk">Tolérance au risque</label>
        <select id="adv-risk" bind:value={f.risque}>
          <option value="1">1 — Prudent</option>
          <option value="2">2 — Modéré bas</option>
          <option value="3">3 — Équilibré</option>
          <option value="4">4 — Dynamique</option>
          <option value="5">5 — Offensif</option>
        </select>
      </div>
      <div class="form-group">
        <label for="adv-employment">Statut professionnel</label>
        <select id="adv-employment" bind:value={f.statut}>
          <option value="">—</option>
          <option value="salarie">Salarié</option>
          <option value="TNS">TNS / Dirigeant</option>
          <option value="fonction_publique">Fonction publique</option>
          <option value="retraite">Retraité</option>
          <option value="autre">Autre</option>
        </select>
      </div>
      <div class="form-group">
        <label for="adv-pension-age">Âge de départ souhaité</label>
        <input type="text" inputmode="numeric" id="adv-pension-age" min="18" max="120" step="1" placeholder="ex: 65" bind:value={f.retraite}>
      </div>
      <div class="form-group">
        <label for="adv-children">Enfants à charge</label>
        <input type="text" inputmode="numeric" id="adv-children" min="0" max="20" step="1" bind:value={f.enfants}>
      </div>
      <div class="form-group">
        <label for="adv-reserve">Réserve à garder disponible</label>
        <input type="text" inputmode="decimal" id="adv-reserve" placeholder="ex : 30 000" aria-describedby="adv-reserve-aide" bind:value={f.reserve}>
        <p class="form-aide" id="adv-reserve-aide">Précaution, apport, nantissement d'un crédit :
          les propositions n'investissent jamais ce montant.</p>
      </div>
      <div class="form-group" style="align-self:end">
        <label style="display:flex;align-items:center;gap:var(--esp-6);cursor:pointer">
          <input type="checkbox" id="adv-main-residence" bind:checked={f.residence}> Résidence principale détenue
        </label>
        <label style="display:flex;align-items:center;gap:var(--esp-6);cursor:pointer">
          <input type="checkbox" id="adv-lbo" bind:checked={f.lbo}> Patrimoine pro (LBO, actions de société)
        </label>
      </div>
      <div class="form-group full-span">
        <label for="adv-notes">Notes / contexte</label>
        <input type="text" id="adv-notes" maxlength="2000" placeholder="Ex: objectif transmission, concentration immobilière, etc." bind:value={f.notes}>
      </div>
    </div>
    <div class="modal-actions">
      <button type="submit" class="btn btn-primary">Enregistrer le profil</button>
    </div>
  </form>
</div>
