<script lang="ts">
  /**
   * Vue macroeconomique : generee par Claude (sans recherche web) ou editee a
   * la main, elle sert de contexte aux propositions d'arbitrage.
   *
   * Porte de static/modules/tabs/advisor.js (_loadMacro, refreshMacro,
   * saveMacro), balisage a l'identique.
   */
  import { api } from '/static/modules/api.js';
  import { toast } from '/static/modules/dialogs.js';
  import { updateDemoBadge } from '/static/modules/tabs/import-export.js';

  let { version = 0 }: { version?: number } = $props();

  interface Snap { id: number; regime_rates?: string; inflation_view?: string; equities_bias?: string; raw_summary?: string;
                   source?: string; date?: string }
  let snap = $state<Snap | null>(null);
  let charge = $state(false);
  let llm = $state({ dispo: false, mock: false });
  let f = $state({ taux: 'neutre', inflation: 'maitrisee', biais: 'neutre', synthese: '' });
  let enCours = $state(false);
  let rechargement = $state(0);

  $effect(() => {
    void version; void rechargement;
    api<{ llm_available?: boolean; llm_mock?: boolean; snapshot?: Snap | null }>('GET', '/api/advisor/macro/latest', null, { silent: true })
      .then(d => {
        llm = { dispo: !!d.llm_available, mock: !!d.llm_mock };
        // Le modele simule allume le badge « démo » de la barre.
        updateDemoBadge({ llmMock: llm.mock });
        snap = d.snapshot || null;
        if (snap) f = { taux: snap.regime_rates || 'neutre', inflation: snap.inflation_view || 'maitrisee',
                        biais: snap.equities_bias || 'neutre', synthese: snap.raw_summary || '' };
        charge = true;
      }).catch(() => {});
  });

  async function actualiser() {
    enCours = true;
    try {
      const r = await api<{ meta?: { cost_usd?: number; latency_ms?: number; cached?: boolean } }>('POST', '/api/advisor/macro/refresh');
      const cost = r.meta?.cost_usd, dur = r.meta?.latency_ms;
      const parts = ['Macro actualisée'];
      if (r.meta?.cached) parts.push('(cache)');
      else if (cost || dur) parts.push(`(${cost ? cost.toFixed(4) + ' $' : ''}${cost && dur ? ', ' : ''}${dur ? (dur / 1000).toFixed(1) + ' s' : ''})`);
      toast(parts.join(' '), 'success');
      rechargement++;
    } catch { /* toast deja affiche */ } finally { enCours = false; }
  }
  async function enregistrer() {
    if (!snap) return;
    try {
      await api('PATCH', `/api/advisor/macro/${snap.id}`, { regime_rates: f.taux, inflation_view: f.inflation,
        equities_bias: f.biais, raw_summary: f.synthese });
      toast('Snapshot macro enregistré', 'success');
      rechargement++;
    } catch { /* toast deja affiche */ }
  }
</script>

<div class="card" id="adv-macro">
  <h2>Vue macroéconomique</h2>
  <p class="text-muted" style="font-size:var(--fs-sm);margin-bottom:var(--esp-14)">
    Synthèse générée par Claude (sans web search) ou éditée à la main.
    Utilisée comme contexte pour les propositions d'arbitrage.
  </p>
  <div id="macro-empty" class="text-muted" style="font-size:var(--fs-sm);margin-bottom:var(--esp-14)" style:display={charge && !snap ? null : 'none'}>
    Aucun arrêté pour le moment.
  </div>
  <div id="macro-content" class="form-grid" style="margin-bottom:var(--esp-14)" style:display={snap ? null : 'none'}>
    <div class="form-group">
      <label for="macro-rates">Régime de taux</label>
      <select id="macro-rates" bind:value={f.taux}><option value="bas">Bas</option><option value="neutre">Neutre</option><option value="haut">Haut</option></select>
    </div>
    <div class="form-group">
      <label for="macro-inflation">Inflation</label>
      <select id="macro-inflation" bind:value={f.inflation}><option value="maitrisee">Maîtrisée</option><option value="persistante">Persistante</option></select>
    </div>
    <div class="form-group">
      <label for="macro-bias">Biais actions</label>
      <select id="macro-bias" bind:value={f.biais}><option value="defensif">Défensif</option><option value="neutre">Neutre</option><option value="offensif">Offensif</option></select>
    </div>
    <div class="form-group full-span" style="grid-column:1 / -1">
      <label for="macro-summary">Synthèse</label>
      <textarea id="macro-summary" rows="4" maxlength="4000" bind:value={f.synthese}
        style="border:1px solid var(--border);border-radius:6px;padding:var(--esp-8) var(--esp-12);font-size:var(--fs-sm);background:var(--card);color:var(--text);font-family:inherit;resize:vertical"></textarea>
    </div>
  </div>
  <div id="macro-meta" class="text-muted" style="font-size:var(--fs-xs);margin-bottom:var(--esp-8)">{snap ? `Source : ${snap.source === 'manual' ? 'manuelle' : 'LLM'} · ${snap.date || ''}` : ''}</div>
  <div style="display:flex;gap:var(--esp-8);flex-wrap:wrap">
    <button type="button" class="btn btn-primary" id="btn-macro-refresh" class:is-loading={enCours} disabled={enCours || (charge && !llm.dispo)}
      title={charge ? (llm.dispo ? (llm.mock ? 'Mode mock : reponse fictive' : 'Appel Claude API') : 'ANTHROPIC_API_KEY absente') : undefined}
      onclick={actualiser}>{enCours ? 'Appel Claude…' : 'Actualiser via Claude'}</button>
    <button type="button" class="btn btn-secondary" id="btn-macro-save" onclick={enregistrer}>Enregistrer ma version</button>
  </div>
</div>
