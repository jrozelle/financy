<script lang="ts">
  /**
   * Les releves importes d'une entite, un par fichier : compte, periode,
   * nombre d'operations. Un releve se retire (mal importe, mauvaise entite),
   * ou tous a la fois — ce qui permet aussi de supprimer l'entite, refusee
   * tant qu'elle a des releves.
   *
   * Le solde d'ouverture d'un compte vient de son plus ancien releve : le
   * retirer retire ce solde, et le toast le dit.
   */
  import { api } from '/static/modules/api.js';
  import { fmtDate, esc } from '/static/modules/utils.js';
  import { confirmDialog, toast } from '/static/modules/dialogs.js';
  import type { Bloc } from './donnees-tresorerie';

  let { b, onRecharger }: { b: Bloc; onRecharger: () => Promise<void> } = $props();

  interface Releve { source: string; compte: string; debut: string; fin: string; n: number }
  const releves = $derived.by(() => {
    const par = new Map<string, Releve>();
    for (const o of b.operations) {
      if (!o.source) continue;
      const r = par.get(o.source);
      if (!r) par.set(o.source, { source: o.source, compte: [o.banque, o.compte].filter(Boolean).join(' '), debut: o.date, fin: o.date, n: 1 });
      else { r.n++; if (o.date < r.debut) r.debut = o.date; if (o.date > r.fin) r.fin = o.date; }
    }
    return [...par.values()].sort((x, y) => y.debut.localeCompare(x.debut));
  });
  const pl = (n: number, mot: string) => `${n} ${mot}${n > 1 ? 's' : ''}`;
  const de = (nom: string) => (/^[aeiouyhàâéèêëîïôûü]/i.test(nom) ? `d'${nom}` : `de ${nom}`);
  const AVERTISSEMENT = "S'il est le plus ancien de son compte, le solde d'ouverture part avec lui : réimportez alors le premier relevé du compte pour le retrouver.";

  async function retirer(corps: { source: string } | { tout: true }, titre: string, detail: string) {
    if (!await confirmDialog(titre, detail, { confirmText: 'Supprimer' })) return;
    try {
      const r = await api<{ operations: number; soldes_retires: number }>('DELETE', `/api/entites/${encodeURIComponent(b.entite)}/releves`, corps);
      toast(`${pl(r.operations, 'opération')} supprimée${r.operations > 1 ? 's' : ''}` + (r.soldes_retires
        ? ` ; solde d'ouverture retiré — réimportez le premier relevé du compte pour le retrouver` : ''), 'success');
      await onRecharger();
    } catch { /* toast deja affiche */ }
  }
  const un = (r: Releve) => retirer({ source: r.source }, 'Supprimer ce relevé ?',
    `<strong>${esc(r.source)}</strong><br>${pl(r.n, 'opération')} du ${fmtDate(r.debut)} au ${fmtDate(r.fin)}${r.compte ? `, compte ${esc(r.compte)}` : ''}.<br>${AVERTISSEMENT}`);
  const tous = () => retirer({ tout: true }, `Supprimer tous les relevés ${de(b.entite)} ?`,
    `<strong>${pl(releves.length, 'relevé')}, ${pl(b.operations.length, 'opération')}</strong>, et les soldes d'ouverture de ses comptes.<br>Les arrêtés passés gardent la trésorerie qu'ils ont retenue.`);
</script>

<details class="treso-ops treso-releves">
  <summary>Les {releves.length} relevé{releves.length > 1 ? 's' : ''} importé{releves.length > 1 ? 's' : ''}</summary>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex : zone defilante, atteignable au clavier -->
  <div class="table-scroll" tabindex="0" role="region" aria-label="Relevés de {b.entite}">
    <table class="data-table">
      <thead><tr><th>Relevé</th><th>Compte</th><th>Période</th><th class="num">Opérations</th><th></th></tr></thead>
      <tbody>
        {#each releves as r (r.source)}
          <tr>
            <td class="treso-lib rel-nom">{r.source}</td>
            <td class="text-muted rel-compte">{r.compte}</td>
            <td class="rel-periode">{fmtDate(r.debut)} → {fmtDate(r.fin)}</td>
            <td class="num rel-n" data-lib="opération{r.n > 1 ? 's' : ''}">{r.n}</td>
            <td class="rel-action"><button type="button" class="btn-icon del" aria-label="Supprimer le relevé {r.source}" onclick={() => un(r)}>Supprimer</button></td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <p class="treso-note">La période va de la première à la dernière opération du relevé. {AVERTISSEMENT}</p>
  <div class="treso-parts-actions">
    <button type="button" class="btn btn-secondary btn-sm" onclick={tous}>Supprimer tous les relevés</button>
  </div>
</details>
