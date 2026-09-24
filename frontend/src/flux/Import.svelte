<script lang="ts">
  /**
   * Import d'avis d'operes et de releves d'especes, en deux temps : on lit et
   * on montre, l'utilisateur valide, on ecrit. Rien n'est insere sans
   * confirmation, et un document deja importe est ecarte.
   *
   * L'apercu se calcule avec le titulaire et l'etablissement qui seront
   * ecrits — doublons et flux provisoires a corriger en dependent — : il se
   * relance a chaque changement de ces deux listes. Un etablissement lu dans
   * un document mais absent des positions (une variante d'orthographe)
   * creerait un compte fantome : le plus probable des etablissements connus
   * est alors impose, et l'apercu le dit.
   *
   * Porte de static/modules/tabs/flux.js (import), balisage a l'identique.
   */
  import { fmt, fmtDate } from '/static/modules/utils.js';
  import { toast } from '/static/modules/dialogs.js';

  interface Ligne { date?: string; duplicate?: boolean; duplicate_reason?: string; warnings?: string[]; net_eur?: number;
                    establishment?: string | null }
  interface Tx extends Ligne { side: 'ACHAT' | 'VENTE'; name?: string; isin?: string; envelope?: string }
  interface Fx extends Ligne { flux_type?: string; label?: string; corrects?: number; correction_reason?: string }
  interface Resume { transactions: number; flux: number; corrections?: number; duplicates?: number; warnings?: number;
                     unknown_isins?: string[]; rejected?: { file: string; reason: string }[];
                     unresolved_envelopes?: string[]; known_establishments?: string[] }
  interface Reponse { transactions: Tx[]; flux: Fx[]; summary: Resume }

  let { titulaires = [], titulaireDefaut = '', onEnregistre }: {
    titulaires?: string[]; titulaireDefaut?: string; onEnregistre: () => void;
  } = $props();

  let lot = $state<{ fichiers: File[]; d: Reponse; owner: string; etab: string;
                     doc: { connus: boolean; lus: string[] } } | null>(null);
  let occupe = $state(false);
  let dessus = $state(false);
  let enregistrement = $state<'' | 'en cours' | 'echec'>('');
  let champ = $state<HTMLInputElement>();

  const etabsLus = (d: Reponse) => [...new Set([...d.transactions, ...d.flux].map(x => x.establishment).filter(Boolean) as string[])];
  const etabsConnus = (d: Reponse) => {
    const connus = new Set(d.summary?.known_establishments || []);
    return [...d.transactions, ...d.flux].every(x => !x.establishment || connus.has(x.establishment));
  };
  /** Celui que le parseur a devine s'il figure dans les positions, sinon un
   *  connu de meme racine (« BoursoBank » / « Boursorama »). */
  function etabDevine(d: Reponse) {
    const connus = d.summary?.known_establishments || [];
    const devine = d.transactions?.[0]?.establishment || d.flux?.[0]?.establishment;
    if (devine && connus.includes(devine)) return devine;
    const racine = (x?: string | null) => (x || '').toLowerCase().normalize('NFD').replace(/[^a-z]/g, '').slice(0, 5);
    return connus.find(k => devine && racine(k) === racine(devine)) || '';
  }

  async function envoyer(fichiers: File[], etape: 'preview' | 'commit', owner: string, etab: string) {
    const fd = new FormData();
    fd.append('owner', owner);
    if (etab) fd.append('establishment', etab);
    fichiers.forEach(f => fd.append('files', f));
    const meta = document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]');
    const res = await fetch(`/api/import/movements?step=${etape}`, { method: 'POST', body: fd,
      headers: meta ? { 'X-CSRF-Token': meta.content } : {} });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.error || `Import refusé (${res.status})`);
    return data;
  }

  async function apercu(fichiers: File[], owner = titulaireDefaut, etab = '') {
    const pdfs = fichiers.filter(f => f.type === 'application/pdf' || /\.pdf$/i.test(f.name));
    if (!pdfs.length) { toast('Déposez des fichiers PDF', 'error'); return; }
    // Le serveur refuse plus de 10 Mo : le dire avant d'envoyer.
    const poids = pdfs.reduce((t, f) => t + f.size, 0);
    if (poids > 10 * 1024 * 1024) {
      toast(`${pdfs.length} fichiers, ${(poids / 1048576).toFixed(1).replace('.', ',')} Mo : 10 Mo au plus par envoi. Déposez-les en plusieurs fois.`, 'error');
      return;
    }
    occupe = true;
    try {
      const d: Reponse = await envoyer(pdfs, 'preview', owner, etab);
      // Ce que dit le document se lit sur l'apercu sans etablissement impose.
      const doc = etab && lot ? lot.doc : { connus: etabsConnus(d), lus: etabsLus(d) };
      if (!etab && !doc.connus) {
        const devine = etabDevine(d);
        if (devine) { lot = { fichiers: pdfs, d, owner, etab, doc }; return apercu(pdfs, owner, devine); }
      }
      lot = { fichiers: pdfs, d, owner, etab, doc };
      enregistrement = '';
    } catch (e) { toast((e as Error).message, 'error'); }
    finally { occupe = false; }
  }

  async function enregistrer() {
    if (!lot) return;
    enregistrement = 'en cours';
    try {
      const d = await envoyer(lot.fichiers, 'commit', lot.owner, lot.etab);
      const i = d.inserted;
      const corr = i.corrections ? `, ${i.corrections} flux provisoire${i.corrections > 1 ? 's' : ''} redaté${i.corrections > 1 ? 's' : ''}` : '';
      toast(`${i.flux} flux et ${i.transactions} opération${i.transactions > 1 ? 's' : ''} enregistré${i.transactions > 1 ? 's' : ''}${corr}`, 'success');
      lot = null;
      onEnregistre();
    } catch (e) { toast((e as Error).message, 'error'); enregistrement = 'echec'; }
  }

  const lignes = $derived(lot ? [
    ...lot.d.transactions.map(t => ({ dup: t.duplicate, reason: t.duplicate_reason, date: t.date,
      kind: t.side === 'ACHAT' ? 'Achat' : 'Vente', label: `${t.name || t.isin || '?'}${t.envelope ? ' · ' + t.envelope : ''}`,
      amount: t.net_eur, warn: t.warnings, corrige: null as string | null })),
    ...lot.d.flux.map(f => ({ dup: f.duplicate, reason: f.duplicate_reason, date: f.date, kind: f.flux_type,
      label: f.label || '', amount: f.net_eur, warn: f.warnings, corrige: f.corrects ? f.correction_reason || null : null })),
  ].sort((a, b) => (a.date || '').localeCompare(b.date || '')) : []);
  const s = $derived(lot?.d.summary);
  const total = $derived(s ? s.transactions + s.flux + (s.corrections || 0) : 0);
  const euros = (v?: number | null) => v == null ? '—' : fmt(v, 2);
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_static_element_interactions -->
<div id="flux-drop" class="dropzone" class:is-over={dessus} class:is-busy={occupe} tabindex="0" role="button"
     aria-label="Importer des avis d'opérés ou des relevés d'espèces"
     onclick={() => champ?.click()}
     onkeydown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); champ?.click(); } }}
     ondragenter={e => { e.preventDefault(); dessus = true; }} ondragover={e => { e.preventDefault(); dessus = true; }}
     ondragleave={e => { e.preventDefault(); dessus = false; }}
     ondrop={e => { e.preventDefault(); dessus = false; apercu([...(e.dataTransfer?.files || [])]); }}>
  <input type="file" id="flux-drop-input" accept="application/pdf" multiple hidden bind:this={champ}
         onchange={e => { const t = e.currentTarget; apercu([...(t.files || [])]); t.value = ''; }}>
  <span class="dropzone-main"><span class="dz-souris">Déposez ici</span><span class="dz-doigt">Choisissez</span> vos avis d'opérés ou relevés d'espèces</span>
  <span class="dropzone-sub">PDF BoursoBank · plusieurs fichiers acceptés · rien n'est écrit avant votre validation</span>
</div>

<div id="flux-import-report" class={lot ? 'import-report' : 'hidden'}>
  {#if lot && s}
    {@const orphelines = s.unresolved_envelopes || []}
    <h3>{lot.fichiers.length} fichier{lot.fichiers.length > 1 ? 's' : ''} lu{lot.fichiers.length > 1 ? 's' : ''}</h3>
    <div class="import-tally">
      <span><b>{s.transactions}</b> opération{s.transactions > 1 ? 's' : ''} de titres</span>
      <span><b>{s.flux}</b> flux de trésorerie</span>
      {#if s.corrections}{@const p = s.corrections > 1 ? 's' : ''}<span><b>{s.corrections}</b> flux provisoire{p} attesté{p}, redaté{p}</span>{/if}
      {#if s.duplicates}{@const p = s.duplicates > 1 ? 's' : ''}<span class="text-muted"><b>{s.duplicates}</b> déjà enregistré{p}, ignoré{p}</span>{/if}
      {#if s.warnings}<span class="negative"><b>{s.warnings}</b> à vérifier</span>{/if}
      {#if s.unknown_isins?.length}<span><b>{s.unknown_isins.length}</b> valeur{s.unknown_isins.length > 1 ? 's' : ''} à créer</span>{/if}
      {#if s.rejected?.length}<span class="negative"><b>{s.rejected.length}</b> non reconnu{s.rejected.length > 1 ? 's' : ''}</span>{/if}
    </div>
    {#if !lot.doc.connus}
      <p class="import-alerte">Le document nomme {lot.doc.lus.map(e => `« ${e} »`).join(', ') || 'un établissement'},
        absent de vos positions. {#if lot.etab}Rattaché à <b>{lot.etab}</b> : changez-le ci-dessous s'il ne correspond pas.{:else}Choisissez ci-dessous l’établissement de vos positions qui lui correspond.{/if}</p>
    {/if}
    {#if orphelines.length}
      <p class="import-alerte">{orphelines.length > 1 ? 'Enveloppes' : 'Enveloppe'} sans compte correspondant dans vos positions :
        <b>{orphelines.join(', ')}</b>. Les flux seraient enregistrés sans compte à neutraliser, et le
        rendement de ce compte ne les verrait pas. Créez le compte, ou vérifiez l'orthographe, avant d'enregistrer.</p>
    {/if}
    {#if s.rejected?.length}
      <div class="import-lines">{#each s.rejected as r, i (i)}<div class="import-line"><span>—</span><span class="negative">rejeté</span>
        <span>{r.file} — {r.reason}</span><span></span></div>{/each}</div>
    {/if}
    {#if lignes.length}
      <div class="import-lines">
        {#each lignes as l, i (i)}
          <div class="import-line" class:is-dup={l.dup}>
            <span>{fmtDate(l.date || '')}</span>
            <span>{l.kind || ''}</span>
            <span>{l.label}{#if l.dup} <span class="badge badge-blk">{l.reason || 'doublon'}</span>{/if}{#if l.corrige} <span
              class="badge badge-j27">{l.corrige}</span>{/if}{#if l.warn?.length} <span class="badge badge-30">à vérifier</span><span
              class="import-avert">{l.warn.join(' · ')}</span>{/if}</span>
            <span class="num">{euros(l.amount)}</span>
          </div>
        {/each}
      </div>
    {/if}
    <div class="import-actions">
      <button class="btn btn-primary" id="flux-import-go" disabled={!total || !(lot.doc.connus || lot.etab) || enregistrement === 'en cours'}
              onclick={enregistrer}>{enregistrement === 'en cours' ? 'Enregistrement…' : enregistrement === 'echec' ? 'Réessayer'
                : total ? `Enregistrer ${total} mouvement${total > 1 ? 's' : ''}` : 'Rien à enregistrer'}</button>
      <button class="btn" id="flux-import-cancel" onclick={() => lot = null}>Annuler</button>
      <label class="import-owner">Au nom de
        <select id="flux-import-owner" class="filter-select" value={lot.owner}
                onchange={e => apercu(lot!.fichiers, e.currentTarget.value, lot!.etab)}>
          {#each titulaires as o (o)}<option value={o}>{o}</option>{/each}
        </select>
      </label>
      <label class="import-owner">Établissement
        <select id="flux-import-etab" class="filter-select" value={lot.etab}
                onchange={e => apercu(lot!.fichiers, lot!.owner, e.currentTarget.value)}>
          {#if lot.doc.connus}<option value="">Selon le document</option>{:else}<option value="" disabled>Choisir…</option>{/if}
          {#each s.known_establishments || [] as e (e)}<option value={e}>{e}</option>{/each}
        </select>
      </label>
    </div>
  {/if}
</div>
