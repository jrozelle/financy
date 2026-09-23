/**
 * Synthese personnalisable : chaque carte est un widget qu'on deplace, qu'on
 * elargit ou retrecit sur la grille de 12 colonnes, et qu'on masque.
 *
 * La disposition vit en base (`/api/synthese/disposition`) et non dans le
 * navigateur : elle suit l'utilisateur du PC au telephone. Sur un ecran etroit
 * (moins de 1 200 px), l'ordre et les cartes masquees s'appliquent, la largeur
 * non — tout y tient sur une colonne.
 *
 * Aucune bibliotheque : le deplacement et le redimensionnement se font aux
 * evenements de pointeur, et tout reste possible au clavier (boutons « plus
 * tot / plus tard » par les fleches sur la poignee, largeurs, masquer).
 */
import { api } from './api.js';
import { esc } from './utils.js';
import { toast } from './dialogs.js';

// Ordre, largeur et nom par defaut : ceux de la mise en page d'origine.
const CARTES = [
  ['chiffres', 12, 'Chiffres clés'],
  ['contribution', 5, 'D’où vient la hausse'],
  ['historique', 7, 'Évolution du patrimoine net'],
  ['evolution', 12, 'Évolution par catégorie'],
  ['projection', 12, 'Projection'],
  ['repartition', 7, 'Répartition'],
  ['cible', 5, 'Écart à la cible'],
  ['mouvements', 7, 'Ce qui a bougé'],
  ['liquidite', 5, 'Si vous aviez besoin d’argent'],
  ['comptes', 12, 'Vos comptes'],
  ['entites', 12, 'Entités'],
  ['fiscalite', 12, 'Si vous vendiez tout'],
];
const DEFAUT_LARGEUR = Object.fromEntries(CARTES.map(([id, l]) => [id, l]));
const NOM = Object.fromEntries(CARTES.map(([id, , n]) => [id, n]));
const LARGEURS = [[4, '1/3'], [6, '1/2'], [8, '2/3'], [12, 'Pleine']];
const MIN_COLONNES = 3;

let _disp = null;          // { ordre: [], largeurs: {}, masquees: [] }
let _chargement = null;
let _edition = false;
let _observateur = null;
let _enregistrement = 0;

const onglet = () => document.getElementById('tab-synthese');
const carte = id => onglet()?.querySelector(`[data-carte="${id}"]`);

function _ordre() {
  const connus = CARTES.map(([id]) => id);
  const perso = (_disp?.ordre || []).filter(id => connus.includes(id));
  return [...perso, ...connus.filter(id => !perso.includes(id))];
}
const _largeur = id => _disp?.largeurs?.[id] || DEFAUT_LARGEUR[id];
const _masquee = id => (_disp?.masquees || []).includes(id);

/** Charge la disposition une fois, puis l'applique. Sans reseau (erreur),
 *  la mise en page d'origine reste. */
export async function appliquerDisposition() {
  if (!_disp) {
    _chargement ||= api('GET', '/api/synthese/disposition', null, { silent: true }).catch(() => ({}));
    _disp = await _chargement;
  }
  _appliquer();
  _bouton();
}

function _appliquer() {
  _ordre().forEach((id, i) => {
    const el = carte(id);
    if (!el) return;
    el.dataset.rang = String(i + 1);
    el.style.setProperty('--w-rang', String(i + 1));
    el.dataset.largeur = String(_largeur(id));
    el.style.setProperty('--w-largeur', String(_largeur(id)));
    el.classList.toggle('w-masquee', _masquee(id));
  });
}

function _enregistrer() {
  // Regroupe les rafales (glisser-deposer, redimensionnement) en une ecriture.
  clearTimeout(_enregistrement);
  _enregistrement = setTimeout(async () => {
    try {
      await api('PUT', '/api/synthese/disposition', {
        ordre: _ordre(), largeurs: _disp.largeurs || {}, masquees: _disp.masquees || [] });
    } catch { toast('Disposition non enregistrée', 'error'); }
  }, 400);
}

function _changer(fn) {
  _disp = { ordre: _ordre(), largeurs: { ...(_disp?.largeurs || {}) }, masquees: [...(_disp?.masquees || [])] };
  fn(_disp);
  _appliquer();
  if (_edition) _commandes();
  _enregistrer();
}

// ─── Bouton et barre d'edition ───────────────────────────────────────────────

function _bouton() {
  const tab = onglet();
  if (!tab || tab.querySelector('.w-perso-bouton')) return;
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'btn btn-secondary btn-sm w-perso-bouton';
  b.textContent = 'Personnaliser la synthèse';
  b.addEventListener('click', () => (_edition ? _quitter() : _entrer()));
  tab.appendChild(b);
}

function _entrer() {
  _edition = true;
  const tab = onglet();
  tab.classList.add('w-edition');
  // La barre se cale sous l'en-tete, dont la hauteur varie (deux lignes sur
  // telephone).
  const entete = document.querySelector('.page-head');
  tab.style.setProperty('--w-entete', `${entete ? entete.getBoundingClientRect().bottom : 56}px`);
  tab.querySelector('.w-perso-bouton').textContent = 'Terminer la personnalisation';
  _commandes();
  // Une carte qui se redessine pendant l'edition (un chargement tardif) perd
  // ses commandes : on les lui rend.
  _observateur = new MutationObserver(() => {
    if (CARTES.some(([id]) => carte(id) && !carte(id).querySelector(':scope > .w-commandes'))) _commandes();
  });
  _observateur.observe(tab, { childList: true, subtree: true });
  document.addEventListener('keydown', _echap);
  tab.querySelector('.w-barre button')?.focus();
}

function _quitter() {
  _edition = false;
  _observateur?.disconnect();
  document.removeEventListener('keydown', _echap);
  const tab = onglet();
  tab.classList.remove('w-edition');
  tab.querySelectorAll('.w-commandes, .w-bord, .w-barre, .w-vide').forEach(n => n.remove());
  const b = tab.querySelector('.w-perso-bouton');
  b.textContent = 'Personnaliser la synthèse';
  b.focus();
}

function _echap(e) {
  if (e.key === 'Escape' && !document.querySelector('.modal:not(.hidden)')) _quitter();
}

function _barre() {
  const tab = onglet();
  let barre = tab.querySelector('.w-barre');
  if (!barre) {
    barre = document.createElement('div');
    barre.className = 'w-barre';
    barre.setAttribute('role', 'region');
    barre.setAttribute('aria-label', 'Personnalisation de la synthèse');
    tab.prepend(barre);
    barre.addEventListener('click', e => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.afficher) _changer(d => { d.masquees = d.masquees.filter(x => x !== b.dataset.afficher); });
      if (b.dataset.action === 'fin') _quitter();
      if (b.dataset.action === 'defaut') _defaut();
    });
  }
  const masquees = _ordre().filter(_masquee);
  barre.innerHTML = `
    <strong>Personnalisation</strong>
    <span class="text-muted w-aide">Glissez une carte par sa poignée, élargissez-la par son bord droit, ou utilisez ses boutons.</span>
    <span class="w-masquees">${masquees.length ? 'Masquées :' + masquees.map(id =>
      ` <button type="button" class="btn btn-secondary btn-sm" data-afficher="${id}">Afficher « ${esc(NOM[id])} »</button>`).join('')
      : 'Aucune carte masquée.'}</span>
    <span class="w-fin">
      <button type="button" class="btn btn-secondary btn-sm" data-action="defaut">Disposition d’origine</button>
      <button type="button" class="btn btn-primary btn-sm" data-action="fin">Terminer</button>
    </span>`;
}

async function _defaut() {
  _disp = {};
  _appliquer();
  _commandes();
  try { await api('PUT', '/api/synthese/disposition', {}); } catch { /* toast deja affiche */ }
}

// ─── Commandes de chaque carte ───────────────────────────────────────────────

const POIGNEE = `<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><g fill="currentColor">
  <circle cx="5" cy="3" r="1.3"/><circle cx="11" cy="3" r="1.3"/><circle cx="5" cy="8" r="1.3"/>
  <circle cx="11" cy="8" r="1.3"/><circle cx="5" cy="13" r="1.3"/><circle cx="11" cy="13" r="1.3"/></g></svg>`;

function _commandes() {
  _barre();
  const ordre = _ordre();
  ordre.forEach((id, i) => {
    const el = carte(id);
    if (!el) return;
    el.querySelectorAll(':scope > .w-commandes, :scope > .w-bord, :scope > .w-vide').forEach(n => n.remove());
    const nom = esc(NOM[id]);
    const l = _largeur(id);
    const boite = document.createElement('div');
    boite.className = 'w-commandes';
    boite.innerHTML = `
      <button type="button" class="w-poignee" data-w="glisser"
              aria-label="Déplacer « ${nom} », position ${i + 1} sur ${ordre.length} : glisser, ou flèches du clavier">${POIGNEE}</button>
      <span class="w-nom">${nom}</span>
      <span class="w-largeurs" role="group" aria-label="Largeur de « ${nom} »">${LARGEURS.map(([n, lib]) =>
        `<button type="button" data-w="largeur" data-n="${n}" aria-pressed="${l === n}">${lib}</button>`).join('')}</span>
      <button type="button" data-w="masquer" aria-pressed="${_masquee(id)}">${_masquee(id) ? 'Afficher' : 'Masquer'}</button>`;
    boite.addEventListener('click', e => _clic(e, id));
    const poignee = boite.querySelector('.w-poignee');
    poignee.addEventListener('pointerdown', e => _glisser(e, id));
    // Au clavier, la poignee deplace : fleches d'un cran, Debut / Fin aux bouts.
    poignee.addEventListener('keydown', e => _clavier(e, id));
    el.prepend(boite);
    const bord = document.createElement('div');
    bord.className = 'w-bord';
    bord.setAttribute('aria-hidden', 'true');
    bord.addEventListener('pointerdown', e => _redimensionner(e, id));
    el.appendChild(bord);
    if (el.style.display === 'none') {
      const vide = document.createElement('span');
      vide.className = 'w-vide';
      vide.textContent = 'Vide pour cette vue : elle s’affiche quand elle a des données.';
      el.appendChild(vide);
    }
  });
}

function _clavier(e, id) {
  const pas = { ArrowUp: -1, ArrowLeft: -1, ArrowDown: 1, ArrowRight: 1 }[e.key];
  const bout = { Home: -Infinity, End: Infinity }[e.key];
  if (pas === undefined && bout === undefined) return;
  e.preventDefault();
  _changer(d => {
    const i = d.ordre.indexOf(id);
    const j = Math.max(0, Math.min(d.ordre.length - 1, bout !== undefined ? (bout < 0 ? 0 : d.ordre.length - 1) : i + pas));
    d.ordre.splice(i, 1);
    d.ordre.splice(j, 0, id);
  });
  carte(id)?.querySelector('.w-poignee')?.focus();
}

function _clic(e, id) {
  const b = e.target.closest('button[data-w]');
  if (!b || b.disabled) return;
  const w = b.dataset.w;
  if (w === 'largeur') {
    _changer(d => { d.largeurs[id] = +b.dataset.n; });
    carte(id)?.querySelector(`.w-commandes [data-w="largeur"][data-n="${b.dataset.n}"]`)?.focus();
  } else if (w === 'masquer') {
    _changer(d => {
      d.masquees = _masquee(id) ? d.masquees.filter(x => x !== id) : [...d.masquees, id];
    });
    carte(id)?.querySelector('.w-commandes [data-w="masquer"]')?.focus();
  }
}

// ─── Glisser-deposer et redimensionnement ────────────────────────────────────

function _glisser(e, id) {
  e.preventDefault();
  const el = carte(id);
  el.classList.add('w-glisse');
  const poignee = e.currentTarget;
  poignee.setPointerCapture(e.pointerId);
  const bouger = ev => {
    // La carte la plus proche du pointeur, et le cote ou il se trouve : avant
    // si le pointeur est au-dessus de son centre (ou a sa gauche, sur une meme
    // rangee), apres sinon. Plus sur que la carte « sous » le pointeur, qui
    // change a chaque reflux de la grille.
    let meilleure = null, dmin = Infinity;
    onglet().querySelectorAll('[data-carte]').forEach(c => {
      if (c.dataset.carte === id || getComputedStyle(c).display === 'none') return;
      const r = c.getBoundingClientRect();
      const dx = Math.max(r.left - ev.clientX, 0, ev.clientX - r.right);
      const dy = Math.max(r.top - ev.clientY, 0, ev.clientY - r.bottom);
      const d = dx * dx + dy * dy;
      if (d < dmin) { dmin = d; meilleure = { c, r }; }
    });
    if (!meilleure) return;
    const { c, r } = meilleure;
    const memeRangee = ev.clientY >= r.top && ev.clientY <= r.bottom;
    const avant = memeRangee ? ev.clientX < r.left + r.width / 2 : ev.clientY < r.top + r.height / 2;
    const ordre = _ordre().filter(x => x !== id);
    ordre.splice(ordre.indexOf(c.dataset.carte) + (avant ? 0 : 1), 0, id);
    if (ordre.join() !== _ordre().join()) {
      _disp = { ..._disp, ordre };
      _appliquer();
    }
  };
  const lacher = () => {
    poignee.removeEventListener('pointermove', bouger);
    poignee.removeEventListener('pointerup', lacher);
    poignee.removeEventListener('pointercancel', lacher);
    el.classList.remove('w-glisse');
    _changer(() => {});
  };
  poignee.addEventListener('pointermove', bouger);
  poignee.addEventListener('pointerup', lacher);
  poignee.addEventListener('pointercancel', lacher);
}

function _redimensionner(e, id) {
  e.preventDefault();
  const el = carte(id);
  const tab = onglet();
  const gap = parseFloat(getComputedStyle(tab).columnGap) || 0;
  const colonne = (tab.clientWidth - 11 * gap) / 12;
  const gauche = el.getBoundingClientRect().left;
  const bord = e.currentTarget;
  bord.setPointerCapture(e.pointerId);
  const bouger = ev => {
    // Calee sur la grille : le nombre de colonnes que couvre le pointeur.
    const n = Math.max(MIN_COLONNES, Math.min(12, Math.round((ev.clientX - gauche + gap) / (colonne + gap))));
    if (n !== _largeur(id)) {
      _disp = { ..._disp, largeurs: { ...(_disp?.largeurs || {}), [id]: n } };
      _appliquer();
    }
  };
  const lacher = () => {
    bord.removeEventListener('pointermove', bouger);
    bord.removeEventListener('pointerup', lacher);
    bord.removeEventListener('pointercancel', lacher);
    _changer(() => {});
  };
  bord.addEventListener('pointermove', bouger);
  bord.addEventListener('pointerup', lacher);
  bord.addEventListener('pointercancel', lacher);
}
