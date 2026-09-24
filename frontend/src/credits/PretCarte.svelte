<script lang="ts">
  // Un credit : ce qui reste du, ce que coute le mois, quand il finit, et ce
  // que couterait le solder aujourd'hui (IRA face aux interets evites).
  import { fmt, fmtDate, fmtPct } from '/static/modules/utils.js';
  import type { Pret } from './types';

  let { pret, couleur, entites, titulaire, onEntite, onIra, onSupprimer }: {
    pret: Pret; couleur: string; entites: string[]; titulaire: string | null;
    onEntite: (id: number, entite: string | null) => void;
    onIra: (id: number, mode: 'legale' | 'aucune') => void;
    onSupprimer: (id: number) => void;
  } = $props();

  const part = $derived(pret.montant
    ? Math.max(0, Math.min(100, (pret.rembourse / pret.montant) * 100)) : 0);

  function dans(fin: string): string {
    const mois = Math.round((Date.parse(fin) - Date.now()) / (30.44 * 864e5));
    return mois <= 0 ? 'remboursé' : mois < 24 ? `dans ${mois} mois` : `dans ${Math.round(mois / 12)} ans`;
  }

  const modeIra = $derived((pret.ira_mode || pret.ira_contrat) === 'aucune' ? 'aucune' : 'legale');
  const taux = $derived(pret.taux_retenu
    ? `${fmtPct(pret.taux_retenu, 2)}${pret.taux_deduit ? ' (déduit de l’échéancier)' : ''}`
    : 'taux inconnu');
  const gain = $derived(pret.interets_restants - pret.ira);
</script>

<div class="pret" data-id={pret.id}>
  <div class="pret-nom">
    <i style:background={couleur}></i>
    <span><b>{pret.libelle}</b><small>{pret.preteur || ''}{pret.taux ? ` · ${fmtPct(pret.taux, 2)}` : ''}
      · {fmt(pret.montant)} empruntés{#if pret.differe}{' '}·
        <b class="pret-differe">différé {pret.differe.type} jusqu’au {fmtDate(pret.differe.jusqu_au)}</b>{/if}{#if pret.part != null && pret.part < 1}{' '}·
        <b class="pret-part">part de {titulaire} : {fmtPct(pret.part * 100, 0)}</b>{/if}</small></span>
  </div>
  <label class="pret-entite"><span class="sr-only">Entité de {pret.libelle}</span>
    <select class="filter-select" value={pret.entity ?? ''}
            onchange={e => onEntite(pret.id, e.currentTarget.value || null)}>
      <option value="">Aucune entité</option>
      {#each entites as nom (nom)}<option value={nom}>{nom}</option>{/each}
    </select></label>
  <div class="pret-chiffre"><small>Restant dû</small><b>{fmt(pret.crd)}</b></div>
  <div class="pret-chiffre"><small>Mensualité</small><b>{pret.differe ? fmt(pret.echeance_du_mois)
      : (pret.mensualite != null ? fmt(pret.mensualite) : '—')}</b>{#if pret.differe && pret.mensualite}
      <small class="pret-differe">puis {fmt(pret.mensualite)}</small>{/if}</div>
  <div class="pret-chiffre"><small>Fin</small><b>{fmtDate(pret.fin)}</b><small>{dans(pret.fin)}</small></div>
  <div class="pret-chiffre"><small>Intérêts restants</small><b>{fmt(pret.interets_restants)}</b></div>
  <div class="pret-avancement" aria-label="{fmtPct(part, 0)} remboursé">
    <span class="pret-barre"><span style:width="{part.toFixed(1)}%"></span></span>
    <small>{fmtPct(part, 0)} remboursé</small>
  </div>
  <button type="button" class="btn-icon del" data-pret-suppr={pret.id}
          aria-label="Supprimer {pret.libelle}" onclick={() => onSupprimer(pret.id)}>Supprimer</button>
  {#if pret.crd}
    <div class="pret-solder">
      <span>Solder aujourd'hui : <b>{fmt(pret.crd + pret.ira)}</b>, dont <b>{fmt(pret.ira)}</b> d'IRA
        {pret.ira ? `(plafond légal : 6 mois d'intérêts à ${taux}, ou 3 % du restant dû)` : '(le contrat y renonce)'}
        — évite {fmt(pret.interets_restants)} d'intérêts et d'assurance à venir{gain > 0 ? `, soit ${fmt(gain)} de moins au total` : ''}.</span>
      <label class="pret-ira"><span class="sr-only">IRA de {pret.libelle}</span>
        <select class="filter-select" value={modeIra}
                onchange={e => onIra(pret.id, e.currentTarget.value as 'legale' | 'aucune')}>
          <option value="legale">IRA au plafond légal</option>
          <option value="aucune">Contrat sans IRA</option>
        </select></label>
    </div>
  {/if}
</div>
