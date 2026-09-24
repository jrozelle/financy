<script lang="ts">
  /**
   * Import / Export (fenetre des Reglages) : import Excel et JSON, export
   * JSON, bascule vers la base de demonstration, copie de la base, remise a
   * zero. Ce qui touche le reste de l'application — dates, historique,
   * entites, rechargement complet — reste dans
   * static/modules/tabs/import-export.js, qui le passe ici.
   *
   * Porte de static/modules/tabs/import-export.js, balisage a l'identique.
   */
  import { api, getCsrfToken } from '/static/modules/api.js';
  import { confirmDialog, promptDialog, toast } from '/static/modules/dialogs.js';

  interface Rappels {
    avantImportJson: (data: Record<string, unknown>) => Promise<void>;
    apresImport: (json: boolean) => Promise<void>;
    apresReset: () => Promise<void>;
    basculerDemo: (demo: boolean) => Promise<void>;
    exporter: () => Promise<void>;
  }
  let { demo = null, rappels }: { demo?: { available: boolean; demo: boolean } | null; rappels: Rappels } = $props();

  interface Resultat { texte: string; ok: boolean }
  let fichierXlsx = $state<HTMLInputElement>();
  let fichierJson = $state<HTMLInputElement>();
  let xlsx = $state<Resultat | null>(null);
  let json = $state<Resultat | null>(null);
  let enCours = $state({ xlsx: false, json: false });

  async function importerXlsx() {
    const f = fichierXlsx?.files?.[0];
    if (!f) { xlsx = { texte: 'Sélectionnez un fichier .xlsx.', ok: false }; return; }
    const fd = new FormData();
    fd.append('file', f);
    enCours.xlsx = true;
    try {
      const res = await fetch('/api/import', { method: 'POST', body: fd, headers: { 'X-CSRF-Token': getCsrfToken() } });
      const data = await res.json();
      if (res.ok) {
        const parts = [`✓ ${data.imported} position(s)`];
        if (data.entities) parts.push(`${data.entities} entité(s)`);
        xlsx = { texte: parts.join(' · ') + ' importée(s).', ok: true };
        await rappels.apresImport(false);
      } else xlsx = { texte: `Erreur : ${data.error}`, ok: false };
    } catch (err) { xlsx = { texte: `Erreur : ${(err as Error).message}`, ok: false }; }
    finally { enCours.xlsx = false; }
  }

  async function importerJson() {
    const f = fichierJson?.files?.[0];
    if (!f) { json = { texte: 'Sélectionnez un fichier .json.', ok: false }; return; }
    enCours.json = true;
    try {
      const data = JSON.parse(await f.text());
      await rappels.avantImportJson(data);
      const r = await api<Record<string, number | string | null>>('POST', '/api/import-json', data);
      const n = (v: unknown, un: string, plusieurs: string) => v ? `${v} ${(v as number) > 1 ? plusieurs : un}` : null;
      const ajoute = [n(r.positions, 'position', 'positions'), n(r.holdings, 'ligne de titres', 'lignes de titres'),
                      n(r.flux, 'flux', 'flux'), n(r.transactions, 'opération', 'opérations'),
                      n(r.entities, 'entité', 'entités')].filter(Boolean);
      // Ce qui existait deja n'est ni double ni ecrase : le dire, sinon
      // « rien de nouveau » laisse croire a un echec.
      const garde = [n(r.positions_existantes, 'position déjà présente', 'positions déjà présentes'),
                     n(r.doublons, 'doublon écarté', 'doublons écartés')].filter(Boolean);
      json = { ok: true, texte: `Ajouté : ${ajoute.join(', ') || 'rien de nouveau'}.`
        + (garde.length ? ` Conservé tel quel : ${garde.join(', ')}.` : '')
        + (r.backup ? ` Copie de la base avant import : ${r.backup}.` : '') };
      await rappels.apresImport(true);
    } catch (err) { json = { texte: `Erreur : ${(err as Error).message}`, ok: false }; }
    finally { enCours.json = false; }
  }

  // ── Mode demo ───────────────────────────────────────────────────────────
  let coche = $state(false);
  $effect.pre(() => { coche = !!demo?.demo; });
  const statutDemo = $derived(demo ? (coche ? 'Actuellement : base de démonstration.' : 'Actuellement : vos données réelles.') : 'Chargement…');
  async function basculer(e: Event) {
    const caseDemo = e.currentTarget as HTMLInputElement, voulu = caseDemo.checked;
    try {
      await api('PUT', '/api/demo-mode', { demo: voulu });
      coche = voulu;
      toast(voulu ? 'Mode démo activé' : 'Retour aux données réelles');
      await rappels.basculerDemo(voulu);
    } catch (err) {
      // L'etat n'a pas change : la case se remet a la main.
      caseDemo.checked = !voulu;
      toast('Erreur : ' + (err as Error).message);
    }
  }

  // ── Copie et remise a zero ─────────────────────────────────────────────
  let copie = $state<Resultat | null>(null);
  async function sauvegarder() {
    try {
      const r = await api<{ size_kb: number }>('POST', '/api/backup');
      copie = { texte: `✓ Backup créé (${r.size_kb} Ko)`, ok: true };
      toast('Backup créé');
    } catch (err) { copie = { texte: 'Erreur : ' + (err as Error).message, ok: false }; }
  }

  const LIBELLES: Record<string, string> = {
    positions: 'positions', flux: 'flux', entities: 'entités', entity_snapshots: 'snapshots entités',
    snapshot_notes: 'notes de snapshot', holdings: 'lignes holdings', holdings_snapshots: 'snapshots holdings',
    price_history: 'cours historiques', securities: 'securities',
  };
  interface Reset { total?: number; deleted?: Record<string, number>; backup?: { filename?: string; size_kb?: number } }
  let reset = $state<Reset | null>(null);
  let minuterie = 0;
  async function vider() {
    if (!await confirmDialog('Vider TOUTE la base ?',
      'Positions, flux et entités seront supprimés <strong>définitivement</strong>.<br>Faites un export JSON avant si vous souhaitez conserver vos données.',
      { confirmText: 'Tout supprimer' })) return;
    const confirmation = await promptDialog('Confirmation requise', { placeholder: 'Tapez VIDER', confirmText: 'Confirmer' });
    if (String(confirmation || '').trim().toUpperCase() !== 'VIDER') {
      toast('Reset annulé : confirmation incorrecte', 'error');
      return;
    }
    let r: Reset;
    try { r = await api<Reset>('POST', '/api/reset', { confirm: 'VIDER' }); } catch { return; }
    await rappels.apresReset();
    reset = r;
    clearTimeout(minuterie);
    minuterie = window.setTimeout(() => { reset = null; }, 8000);
  }
</script>

<div class="page-header"><h1>Import / Export</h1></div>
<div class="two-col">

  <div class="card">
    <h2>Importer depuis Excel</h2>
    <p class="text-muted" style="margin-bottom:1rem">
      Importez les onglets <strong>Positions</strong> et <strong>Flux</strong>
      depuis votre fichier <code>.xlsx</code>.<br>
      Les données existantes ne sont pas effacées.
    </p>
    <div class="form-group">
      <label for="import-file">Fichier .xlsx</label>
      <input type="file" id="import-file" accept=".xlsx" bind:this={fichierXlsx}>
    </div>
    <button class="btn btn-primary" id="btn-import" style="margin-top:.75rem" disabled={enCours.xlsx}
            onclick={importerXlsx}>{enCours.xlsx ? 'Import en cours…' : 'Importer'}</button>
    <div id="import-result" style="margin-top:1rem">{#if xlsx}<div class="alert alert-{xlsx.ok ? 'success' : 'error'}">{xlsx.texte}</div>{/if}</div>
  </div>

  <div class="card">
    <h2>Importer depuis JSON</h2>
    <p class="text-muted" style="margin-bottom:1rem">
      Restaure un export JSON. Ce qui existe déjà est gardé tel quel, jamais doublé ni écrasé ;
      une copie de la base est faite avant.
    </p>
    <div class="form-group">
      <label for="import-json-file">Fichier .json</label>
      <input type="file" id="import-json-file" accept=".json" bind:this={fichierJson}>
    </div>
    <button class="btn btn-primary" id="btn-import-json" style="margin-top:.75rem" disabled={enCours.json}
            onclick={importerJson}>{enCours.json ? 'Import en cours…' : 'Importer JSON'}</button>
    <div id="import-json-result" style="margin-top:1rem">{#if json}<div class="alert alert-{json.ok ? 'success' : 'error'}">{json.texte}</div>{/if}</div>
  </div>

  <div class="card">
    <h2>Exporter en JSON</h2>
    <p class="text-muted" style="margin-bottom:1rem">
      Toutes vos données — positions et lignes de titres, flux, opérations, entités, cours,
      profils, référentiel — en un fichier. La clé API n'y figure pas.
    </p>
    <button class="btn btn-secondary" id="btn-export" onclick={() => rappels.exporter()}>Télécharger patrimoine.json</button>
  </div>

  <div class="card" id="demo-card" style:display={demo && !demo.available ? 'none' : null}>
    <h2>Mode démo</h2>
    <p class="text-muted" style="margin-bottom:1rem">
      Bascule vers une base de données fictive pour explorer l'application sans risque.<br>
      Vos vraies données ne sont pas affectées.
    </p>
    <!-- Le libelle dit ce que la case active ; l'etat se lit a cote. -->
    <label class="toggle-label" style="display:flex;align-items:center;gap:.5rem;cursor:pointer">
      <input type="checkbox" id="demo-toggle" aria-describedby="demo-status" checked={coche} onchange={basculer}>
      Utiliser la base de démonstration
    </label>
    <p class="form-aide" id="demo-status" aria-live="polite">{statutDemo}</p>
  </div>

  <div class="card">
    <h2>Sauvegarder la base</h2>
    <p class="text-muted" style="margin-bottom:1rem">
      Crée une copie horodatée de la base de données dans le dossier <code>backups/</code>.
    </p>
    <button class="btn btn-secondary" id="btn-backup" onclick={sauvegarder}>Créer un backup</button>
    <div id="backup-result" style="margin-top:.75rem">{#if copie}<div class="alert alert-{copie.ok ? 'success' : 'error'}">{copie.texte}</div>{/if}</div>
  </div>

  <div class="card" style="border: 1px solid #fca5a5">
    <h2 style="color:var(--danger)">Zone dangereuse</h2>
    <p class="text-muted" style="margin-bottom:1rem">
      Supprime toutes les positions, flux et entités.<br>
      <strong>Irréversible</strong> — fais un export JSON avant.
    </p>
    <button class="btn" style="background:var(--danger);color:var(--on-accent);border-color:var(--danger)" id="btn-reset" onclick={vider}>Vider la base</button>
    <div id="reset-result" style="margin-top:.75rem">
      {#if reset}
        {@const lignes = Object.entries(reset.deleted || {}).filter(([, n]) => n > 0)}
        <div class="alert alert-success">
          Base vidée — <strong>{(reset.total || 0).toLocaleString('fr-FR')}</strong> ligne(s) supprimée(s).
          {#if reset.backup?.filename}<br>Backup automatique : <strong>{reset.backup.filename}</strong> ({reset.backup.size_kb} Ko).{/if}
          {#if lignes.length}<ul style="margin:.4rem 0 0 1.1rem;font-size:var(--fs-sm)">{#each lignes as [t, n] (t)}<li>{n.toLocaleString('fr-FR')} {LIBELLES[t] || t}</li>{/each}</ul>{/if}
        </div>
      {/if}
    </div>
  </div>

</div>
