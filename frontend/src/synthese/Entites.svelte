<script lang="ts">
  /**
   * Entites (SCI, indivisions) : valeur, dette et net de chacune, et la part
   * qui revient a la famille — ou au titulaire choisi, avec sa part de dette
   * quand elle differe de sa part du bien. Vue d'un titulaire : ses seules
   * entites (les autres a « 0 € 0 % » n'apprenaient rien).
   *
   * Porte de static/modules/tabs/synthese.js (renderEntitiesSynthese).
   */
  import { fmt, fmtPct } from '/static/modules/utils.js';

  interface Entite { name: string; type?: string | null; gross_assets: number; debt: number; net_assets: number }
  interface Pos { owner: string; entity: string | null; net_attributed?: number; gross_attributed?: number;
                  debt_attributed?: number; ownership_pct?: number; debt_pct?: number | null }
  let { hote, entites = [], positions = [], owner = 'Famille', masque = false }: {
    hote: HTMLElement; entites?: Entite[]; positions?: Pos[]; owner?: string; masque?: boolean;
  } = $props();

  const famille = $derived(owner === 'Famille');
  const lignes = $derived.by(() => {
    const liste = famille ? entites : entites.filter(e => positions.some(p => p.entity === e.name && p.owner === owner));
    return liste.map(e => {
      const liees = positions.filter(p => p.entity === e.name);
      const somme = (champ: keyof Pos, ps = liees) => ps.reduce((s, p) => s + ((p[champ] as number) || 0), 0);
      const brutFamille = somme('gross_attributed');
      const siennes = liees.filter(p => p.owner === owner);
      return {
        e, netFamille: somme('net_attributed'),
        pctFamille: e.gross_assets > 0 ? fmtPct(brutFamille / e.gross_assets * 100, 0) : '',
        netTitulaire: famille ? null : somme('net_attributed', siennes),
        pctTitulaire: !famille && e.gross_assets > 0 ? siennes.reduce((s, p) => s + (p.ownership_pct || 0), 0) : null,
        // Le net suit aussi la part de DETTE, qui peut differer de la propriete.
        pctDette: !famille && e.debt > 0 ? siennes.reduce((s, p) => s + (p.debt_pct ?? p.ownership_pct ?? 0), 0) : null,
      };
    });
  });
  $effect(() => { hote.style.display = lignes.length ? '' : 'none'; });
</script>

<h2>Entités</h2>
  <p class="card-sub">SCI et indivisions, quote-part de détention appliquée</p>
<!-- svelte-ignore a11y_no_noninteractive_tabindex : zone qui defile, atteignable au clavier -->
<div id="entities-synthese" tabindex="0" role="region" aria-label="Entités">
  {#key masque}
  {#if lignes.length}
    <table class="owners-table">
      <thead><tr>
        <th>Entité</th>
        <th>Type</th>
        <th style="text-align:right">Actif brut total</th>
        <th style="text-align:right">Dette totale</th>
        <th style="text-align:right">Net total</th>
        <th style="text-align:right">Quote-part famille</th>
        {#if !famille}<th style="text-align:right">{owner}</th>{/if}
      </tr></thead>
      <tbody>
        {#each lignes as l (l.e.name)}
          <tr>
            <td><strong>{l.e.name}</strong></td>
            <td>{l.e.type || '—'}</td>
            <td style="text-align:right">{fmt(l.e.gross_assets)}</td>
            <td style="text-align:right">{l.e.debt > 0 ? fmt(l.e.debt) : '—'}</td>
            <td style="text-align:right;font-weight:600" class={l.e.net_assets >= 0 ? 'pos' : 'neg'}>{fmt(l.e.net_assets)}</td>
            <td style="text-align:right">
              {fmt(l.netFamille)}
              <span style="font-size:var(--fs-2xs);color:var(--text-muted);margin-left:var(--esp-4)">{l.pctFamille}</span>
            </td>
            {#if !famille}
              <td style="text-align:right;font-weight:700;color:var(--primary)">
                {fmt(l.netTitulaire)}
                {#if l.pctTitulaire !== null}<span style="font-size:var(--fs-2xs);color:var(--text-muted);margin-left:var(--esp-4)">{fmtPct(l.pctTitulaire * 100, 0)}{
                  l.pctDette !== null && Math.abs(l.pctDette - l.pctTitulaire) > 0.005 ? ` du bien, ${fmtPct(l.pctDette * 100, 0)} de la dette` : ''}</span>{/if}
              </td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
  {/key}
</div>
