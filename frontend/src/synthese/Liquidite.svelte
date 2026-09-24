<script lang="ts">
  /**
   * « Si vous aviez besoin d'argent » : ce qui est disponible, par delai.
   * Montants CUMULES : sous une semaine, on dispose aussi de ce qui l'etait
   * sous 24 h — la seule question qui compte est « de combien je dispose
   * d'ici la ? ». « Bloque » = le FINANCIER qui ne se mobilise pas (PER,
   * contrat nanti, decote de sortie) ; immobilier et biens hors decompte.
   *
   * Porte de static/modules/tabs/synthese.js (renderLiqBars).
   */
  import { fmt } from '/static/modules/utils.js';
  import { natureDe } from '/static/modules/categories.js';

  interface Pos { category: string; envelope: string | null; net_attributed?: number; mobilizable_value?: number }
  let { parLiquidite = {}, positions = [], masque = false }: {
    parLiquidite?: Record<string, number>; positions?: Pos[]; masque?: boolean;
  } = $props();

  const calcul = $derived.by(() => {
    const L = parLiquidite;
    const delais = [
      { cles: ['J0–J1'], libelle: 'Sous 24 heures' },
      { cles: ['J0–J1', 'J2–J7'], libelle: 'Sous une semaine' },
      { cles: ['J0–J1', 'J2–J7', 'J8–J30'], libelle: 'Sous un mois' },
    ];
    if (L['30J+']) delais.push({ cles: ['J0–J1', 'J2–J7', 'J8–J30', '30J+'], libelle: 'Au-delà d’un mois' });
    const mobilisable = ['J0–J1', 'J2–J7', 'J8–J30', '30J+'].reduce((s, k) => s + (L[k] || 0), 0);
    const financier = positions.filter(p => ['liq', 'fin'].includes(natureDe(p.category, p.envelope)));
    const bloque = financier.reduce((s, p) => s + Math.max(0, (p.net_attributed || 0) - (p.mobilizable_value || 0)), 0);
    const horsFinancier = positions.filter(p => !financier.includes(p)).reduce((s, p) => s + (p.net_attributed || 0), 0);
    const base = Math.max(mobilisable + bloque, 1);
    return {
      lignes: delais.map(d => ({ libelle: d.libelle, v: d.cles.reduce((s, k) => s + (L[k] || 0), 0) })),
      mobilisable, bloque, horsFinancier, base,
    };
  });
  const largeur = (v: number) => `${Math.min(100, (v / calcul.base) * 100).toFixed(1)}%`;
</script>

<h2>Si vous aviez besoin d’argent</h2>
<p class="card-sub">Délai réel pour mobiliser chaque euro</p>
<div id="liquidity-bars">
  {#key masque}
  <div class="dispo">
    {#each calcul.lignes as l (l.libelle)}
      <div class="dispo-ligne">
        <span class="dispo-n">{l.libelle}</span>
        <span class="dispo-v">{fmt(l.v)}</span>
        <span class="dispo-track"><span class="dispo-fill" style:width={largeur(l.v)} style:background="var(--chart-1)"></span></span>
      </div>
    {/each}
    {#if calcul.bloque >= 1}
      <div class="dispo-ligne dispo-bloque">
        <span class="dispo-n">Ce qui reste bloqué</span>
        <span class="dispo-v">{fmt(calcul.bloque)}</span>
        <span class="dispo-track"><span class="dispo-fill" style:width={largeur(calcul.bloque)} style:background="var(--text-muted)"></span></span>
      </div>
    {/if}
  </div>
  {#if calcul.mobilisable || calcul.bloque}
    <p class="dispo-note">Délais cumulés : chaque ligne inclut la précédente.
      « Bloqué » : le patrimoine financier qui ne se mobilise pas — épargne retraite, contrat nanti,
      décote de sortie.{Math.abs(calcul.horsFinancier) >= 1 ? ` Immobilier, biens et sociétés, hors de ce décompte : ${fmt(calcul.horsFinancier)} de net.` : ''}</p>
  {/if}
  {/key}
</div>
