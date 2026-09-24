/**
 * Arborescence des positions.
 *
 * Remplace un arbre de <div> indentees dont chaque niveau decalait la colonne
 * des montants : on ne pouvait pas descendre une colonne des yeux. Ici c'est
 * un vrai tableau hierarchique (role="treegrid") : l'indentation ne touche que
 * la colonne du nom, valeur, dette, net et plus-value restent alignees.
 *
 * Deux lectures, deux questions :
 * - PAR NATURE (defaut) : comment mon patrimoine est reparti — liquidites,
 *   placements, immobilier, biens. Le titulaire devient une etiquette ;
 * - PAR TITULAIRE puis ETABLISSEMENT : le chemin du pointage, quand on
 *   verifie ses chiffres releve par releve, banque par banque ;
 * - A PLAT : tous les comptes sur un rang, pour les classer — ce que seule la
 *   vue Tableau permettait.
 *
 * Chaque colonne se trie, et le tri s'applique a tous les niveaux : les comptes
 * d'une nature, les etablissements d'un titulaire. Une valeur absente (une
 * plus-value inconnue) reste en bas dans les deux sens.
 *
 * Les lignes de titres d'un compte se chargent a l'ouverture de ce compte :
 * inutile de les demander toutes pour n'en regarder qu'une.
 *
 * Les boutons portent les `data-action` que le gestionnaire delegue de
 * #positions-tree-wrap (main.js) traite deja : editer, lignes, historique,
 * ajouter dans ce contexte. Aucune action n'est redefinie ici.
 */
import { S } from '../state.js';
import { api } from '../api.js';
import { fmt, esc, fmtPct } from '../utils.js';
import { NATURES, natureDe } from '../categories.js';
import { lirePref, ecrirePref } from '../preferences.js';

const CLE_GROUPE = 'financy_arbo_groupe';
const CLE_OUVERTS = 'financy_arbo_ouverts';
const CLE_TRI = 'financy_arbo_tri';

let _groupe = 'nature';
let _ouverts = null;              // Set des cles depliees ; null = defaut
let _recherche = '';
let _tri = { col: 'brut', sens: -1 };
const _lignesTitres = new Map();  // id position -> holdings, ou 'chargement'

// Lu au premier rendu, pas au chargement du module : les preferences
// partagees (regroupement, tri) arrivent de la base pendant le demarrage.
// Les noeuds ouverts restent propres a l'appareil.
let _reglagesLus = false;
function _lireReglages() {
  if (_reglagesLus) return;
  _reglagesLus = true;
  try {
    _groupe = lirePref(CLE_GROUPE) || 'nature';
    const o = localStorage.getItem(CLE_OUVERTS);
    if (o) _ouverts = new Set(JSON.parse(o));
    const t = lirePref(CLE_TRI);
    if (t) _tri = { ..._tri, ...JSON.parse(t) };
  } catch { /* session privee : on garde les valeurs par defaut */ }
}

function _memoriser() {
  ecrirePref(CLE_GROUPE, _groupe);
  ecrirePref(CLE_TRI, JSON.stringify(_tri));
  try {
    if (_ouverts) localStorage.setItem(CLE_OUVERTS, JSON.stringify([..._ouverts]));
  } catch { /* session privee */ }
}

/** Une lettre par titulaire ; deux quand deux prenoms commencent pareil
 *  (les enfants) — sinon l'etiquette ne distingue plus personne. */
let _initiales = {};
function _calculerInitiales(positions) {
  const noms = [...new Set(positions.map(p => p.owner).filter(Boolean))];
  _initiales = {};
  noms.forEach(n => {
    const une = n[0].toUpperCase();
    const rivaux = noms.filter(m => m[0].toUpperCase() === une);
    _initiales[n] = rivaux.length > 1 ? n.slice(0, 2) : une;
  });
}
const INITIALES = qui => _initiales[qui] || String(qui || '?').slice(0, 1);

// ── Construction des noeuds ──────────────────────────────────────────────
// Un noeud : { cle, niveau, nom, sous, chip, couleur, brut, dette, gain,
// mesures, enfants, position, titres }. Les montants sont les montants
// ATTRIBUES (la part du titulaire) : ce sont eux qui s'additionnent en total.

function _somme(noeuds) {
  const n = { brut: 0, dette: 0, gain: 0, mesures: 0 };
  noeuds.forEach(x => {
    n.brut += x.brut; n.dette += x.dette;
    if (x.mesures) { n.gain += x.gain; n.mesures += x.mesures; }
  });
  return n;
}

function _feuille(p, niveau, { avecEtab = true, avecTitulaire = true } = {}) {
  // « Cash & depots » sous chaque livret ne dirait rien : c'est la nature meme
  // du groupe. Ailleurs (Actions, Fonds euros), la categorie distingue deux
  // contrats d'un meme etablissement.
  const cat = p.label || p.category === p.envelope || p.category === 'Cash & dépôts' ? null : p.category;
  const sous = [p.label, avecEtab ? p.establishment : null, cat]
    .filter(Boolean).join(' · ');
  return {
    cle: `p${p.id}`, niveau, position: p,
    nom: p.envelope || p.category || '—', sous,
    chip: avecTitulaire ? INITIALES(p.owner) : '',
    brut: p.gross_attributed || 0, dette: p.debt_attributed || 0,
    gain: p.gain_attributed || 0, mesures: p.gain_lignes ? 1 : 0,
    titres: !!p.holdings_count,
    enfants: [],
  };
}

function _parNature(positions) {
  return NATURES.map(n => {
    const ps = positions.filter(p => natureDe(p.category, p.envelope) === n.id);
    if (!ps.length) return null;
    // Une entite (SCI, indivision) est UN bien : ses parts par titulaire se
    // lisent en la depliant, au lieu de s'eparpiller en autant de lignes.
    const parEntite = new Map();
    const comptes = [];
    ps.forEach(p => {
      if (!p.entity) { comptes.push(_feuille(p, 1)); return; }
      if (!parEntite.has(p.entity)) {
        const e = (S.entities || []).find(x => x.name === p.entity);
        const noeud = { cle: `e${p.entity}`, niveau: 1, nom: p.entity, sous: e?.type || 'Entité',
                        chip: '', enfants: [] };
        parEntite.set(p.entity, noeud);
        comptes.push(noeud);
      }
      const f = _feuille(p, 2, { avecEtab: false });
      f.nom = p.owner;
      f.sous = fmtPct((p.ownership_pct ?? 1) * 100, 0) + ' détenu';
      f.chip = '';
      parEntite.get(p.entity).enfants.push(f);
    });
    parEntite.forEach(e => Object.assign(e, _somme(e.enfants)));
    comptes.sort((a, b) => b.brut - a.brut);
    return { cle: `n${n.id}`, niveau: 0, nom: n.nom, sous: `${n.aide} · ${comptes.length} compte${comptes.length > 1 ? 's' : ''}`,
             couleur: n.couleur, enfants: comptes, ..._somme(comptes) };
  }).filter(Boolean);
}

function _parTitulaire(positions) {
  const titulaires = [...new Set(positions.map(p => p.owner))];
  return titulaires.map(qui => {
    const ps = positions.filter(p => p.owner === qui);
    const etabs = new Map();
    ps.forEach(p => {
      const nom = p.establishment || p.entity || 'Sans établissement';
      if (!etabs.has(nom)) etabs.set(nom, { cle: `t${qui}|${nom}`, niveau: 1, nom, sous: '', chip: '', enfants: [],
        contexte: { owner: qui, establishment: p.establishment || null, entity: p.establishment ? null : p.entity } });
      const f = _feuille(p, 2, { avecEtab: false, avecTitulaire: false });
      f.couleur = NATURES.find(n => n.id === natureDe(p.category, p.envelope))?.couleur;
      etabs.get(nom).enfants.push(f);
    });
    const liste = [...etabs.values()];
    liste.forEach(e => {
      Object.assign(e, _somme(e.enfants));
      e.enfants.sort((a, b) => b.brut - a.brut);
      e.sous = `${e.enfants.length} compte${e.enfants.length > 1 ? 's' : ''}`;
    });
    liste.sort((a, b) => b.brut - a.brut);
    return { cle: `t${qui}`, niveau: 0, nom: qui, chip: INITIALES(qui),
             sous: `${liste.length} établissement${liste.length > 1 ? 's' : ''}`,
             enfants: liste, ..._somme(liste) };
  }).sort((a, b) => b.brut - a.brut);
}

/** Par etablissement : la banque ou l'assureur, puis ses comptes — le
 *  titulaire en pastille. C'est la lecture d'un releve : « ce que j'ai chez
 *  Boursorama », tous titulaires confondus. */
function _parEtablissement(positions) {
  const etabs = new Map();
  positions.forEach(p => {
    const nom = p.establishment || p.entity || 'Sans établissement';
    if (!etabs.has(nom)) etabs.set(nom, { cle: `e${nom}`, niveau: 0, nom, sous: '', enfants: [],
      contexte: { owner: p.owner, establishment: p.establishment || null, entity: p.establishment ? null : p.entity } });
    const f = _feuille(p, 1, { avecEtab: false });
    f.couleur = NATURES.find(n => n.id === natureDe(p.category, p.envelope))?.couleur;
    f.pastille = true;
    etabs.get(nom).enfants.push(f);
  });
  return [...etabs.values()].map(e => {
    const titulaires = new Set(e.enfants.map(f => f.position.owner));
    e.sous = `${e.enfants.length} compte${e.enfants.length > 1 ? 's' : ''}`
      + (titulaires.size > 1 ? ` · ${titulaires.size} titulaires` : '');
    // Un seul titulaire : « Ajouter » cree le compte a son nom ; plusieurs,
    // le formulaire demandera lequel.
    if (titulaires.size > 1) e.contexte = { ...e.contexte, owner: null };
    return Object.assign(e, _somme(e.enfants));
  }).sort((a, b) => b.brut - a.brut);
}

// ── Tri ──────────────────────────────────────────────────────────────────
const CLES_TRI = {
  nom:  n => (n.nom || '').toLocaleLowerCase('fr'),
  brut: n => n.brut,
  dette: n => n.dette,
  net:  n => n.brut - n.dette,
  pv:   n => (n.position ? (n.position.gain_lignes ? n.position.gain_attributed : null)
                         : (n.mesures ? n.gain : null)),
};
function _trier(noeuds) {
  const cle = CLES_TRI[_tri.col] || CLES_TRI.brut;
  const out = [...noeuds].sort((a, b) => {
    const x = cle(a), y = cle(b);
    if (x == null || y == null) return (x == null) - (y == null);
    if (typeof x === 'string') return _tri.sens * x.localeCompare(y, 'fr');
    return _tri.sens * (x - y);
  });
  out.forEach(n => { if (n.enfants?.length) n.enfants = _trier(n.enfants); });
  return out;
}

function _aPlat(positions) {
  return positions.map(p => {
    const f = _feuille(p, 0);
    f.visuel = 1;                    // un compte, pas un groupe : sans fond
    f.couleur = NATURES.find(n => n.id === natureDe(p.category, p.envelope))?.couleur;
    f.pastille = true;               // la nature se lit a la pastille
    if (p.entity) f.sous = [p.entity, f.sous].filter(Boolean).join(' · ');
    return f;
  });
}

// ── Recherche ────────────────────────────────────────────────────────────
// Un noeud reste s'il correspond ou si l'un de ses descendants correspond.
// Garde pour ses descendants seulement, il ne compte que ce qu'il montre : ses
// montants se recalculent, sans quoi le pied « filtre » additionnait des
// groupes entiers pour un seul compte visible. Les GROUPES retenus s'ouvrent
// d'office, pour qu'on voie ce qu'on a trouve ; un compte a titres, non —
// chercher « PEA » aurait charge les lignes de chaque PEA.
let _forces = new Set();          // groupes ouverts d'office par la recherche
let _fermesRecherche = new Set(); // ... et que l'utilisateur a replies depuis
let _rechercheVue = '';

function _filtrer(noeuds, q) {
  const texte = n => `${n.nom} ${n.sous} ${n.position?.owner || ''} ${n.position?.establishment || ''}`.toLowerCase();
  return noeuds.map(n => {
    if (texte(n).includes(q)) {
      if (!n.position && n.enfants?.length) _forces.add(n.cle);
      return n;
    }
    const enfants = _filtrer(n.enfants || [], q);
    if (!enfants.length) return null;
    _forces.add(n.cle);
    // « 15 comptes » quand six s'affichent : le decompte suit le filtre.
    const sous = (n.sous || '').replace(/\d+ comptes?\b/, `${enfants.length} sur ${n.enfants.length} compte${n.enfants.length > 1 ? 's' : ''}`);
    return { ...n, enfants, sous, ..._somme(enfants) };
  }).filter(Boolean);
}

// ── Rendu ────────────────────────────────────────────────────────────────

const CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M9 6l6 6-6 6"/></svg>';

/** Defaut : les groupes de tete ouverts, jamais un compte. A plat, les comptes
 *  SONT la tete — tous ouverts, ils chargeaient chacun leurs lignes de titres. */
const _ouvertParDefaut = n => n.niveau === 0 && !n.position;

function _estOuvert(n) {
  if (_forces.has(n.cle)) return !_fermesRecherche.has(n.cle);
  if (!_ouverts) return _ouvertParDefaut(n);
  return _ouverts.has(n.cle);
}

function _racines() {
  const ps = _dernier.positions;
  return _groupe === 'titulaire' ? _parTitulaire(ps) : _groupe === 'etablissement' ? _parEtablissement(ps)
       : _groupe === 'plat' ? _aPlat(ps) : _parNature(ps);
}

function _cellulePv(n) {
  if (n.pvHtml != null) return n.pvHtml;
  const p = n.position;
  if (p) {
    // Pas de plus-value sans lignes de titres : le dire, plutot qu'une case vide.
    if (!p.has_holdings) return `<span class="arbo-pv-na">—</span><span class="arbo-pv-note">${
      p.entity ? 'valeur de l’entité' : 'sans lignes de titres'}</span>`;
    if (!p.gain_lignes) return '<span class="arbo-pv-na">PRU inconnu</span>';
    const partiel = p.gain_lignes < p.holdings_count
      ? `<span class="arbo-pv-note">${p.gain_lignes}/${p.holdings_count} lignes</span>` : '';
    return `<span class="${p.gain_attributed >= 0 ? 'pv-hausse' : 'pv-baisse'}">${p.gain_attributed >= 0 ? '+' : '−'}${fmt(Math.abs(p.gain_attributed))}</span>`
         + (p.gain_pct != null ? `<span class="arbo-pv-note arbo-pv-pct">${fmtPct(p.gain_pct * 100, 1, true)}</span>` : '')
         + partiel;
  }
  if (!n.mesures) return '';
  return `<span class="${n.gain >= 0 ? 'pv-hausse' : 'pv-baisse'}">${n.gain >= 0 ? '+' : '−'}${fmt(Math.abs(n.gain))}</span>`
       + `<span class="arbo-pv-note">${n.mesures} compte${n.mesures > 1 ? 's' : ''} mesuré${n.mesures > 1 ? 's' : ''}</span>`;
}

function _ligne(n, total, couleurHeritee) {
  const couleur = n.couleur || couleurHeritee || 'var(--primary)';
  const ouvrable = (n.enfants && n.enfants.length) || n.titres;
  const ouvert = ouvrable && _estOuvert(n);
  const part = total ? n.brut / total * 100 : 0;
  const net = n.brut - n.dette;
  const p = n.position;
  const libelle = esc(n.nom);
  let actions = '';
  if (p) {
    actions = `
      <button type="button" class="arbo-act" data-action="edit-pos" data-id="${p.id}" aria-label="Éditer ${libelle}">Éditer</button>
      ${p.holdings_count ? `<button type="button" class="arbo-act" data-action="manage-holdings" data-id="${p.id}" aria-label="Lignes de ${libelle}">Lignes</button>` : ''}
      <button type="button" class="arbo-act" data-action="history-pos" data-id="${p.id}" aria-label="Historique de ${libelle}">Historique</button>`;
  } else if (n.contexte) {
    // Un etablissement d'un titulaire : son historique, et y ajouter un compte.
    const c = n.contexte;
    const attrs = `data-owner="${esc(c.owner)}"${c.establishment ? ` data-establishment="${esc(c.establishment)}"` : ''}${c.entity ? ` data-entity="${esc(c.entity)}"` : ''}`;
    actions = `
      <button type="button" class="arbo-act" data-action="history-etabl" ${attrs} aria-label="Historique de ${libelle}">Historique</button>
      <button type="button" class="arbo-act" data-action="add-pos-ctx" ${attrs} aria-label="Ajouter un compte chez ${libelle}">Ajouter</button>`;
  }
  return `
    <tr class="arbo-l${n.visuel ?? n.niveau}" role="row" aria-level="${n.niveau + 1}"
        ${ouvrable ? `aria-expanded="${ouvert}"` : ''} data-cle="${esc(n.cle)}">
      <td class="arbo-nom" role="gridcell">
        <div class="arbo-nom-in" style="--niv:${n.niveau}">
          ${ouvrable
            ? `<button type="button" class="arbo-chevron" data-arbo-basculer="${esc(n.cle)}"
                 aria-label="${ouvert ? 'Replier' : 'Déplier'} ${esc(n.nom)}">${CHEVRON}</button>`
            : '<span class="arbo-chevron-vide"></span>'}
          ${(n.niveau === 0 || n.pastille) && n.couleur ? `<span class="arbo-pastille" style="background:${couleur}"></span>` : ''}
          <span class="arbo-texte">
            <span class="arbo-titre">${esc(n.nom)}</span>
            ${n.sous ? `<span class="arbo-sous">${esc(n.sous)}</span>` : ''}
          </span>
          ${n.chip ? `<span class="arbo-chip">${esc(n.chip)}</span>` : ''}
        </div>
        <span class="arbo-barre arbo-barre--mobile" aria-hidden="true"><i style="width:${Math.max(.6, part).toFixed(2)}%;background:${couleur}"></i></span>
      </td>
      <td class="arbo-part" role="gridcell">
        <span class="arbo-barre" aria-hidden="true"><i style="width:${Math.max(.6, part).toFixed(2)}%;background:${couleur}"></i></span>
        <span class="arbo-part-txt">${fmtPct(part, part < 10 ? 1 : 0)}</span>
      </td>
      <td class="num arbo-valeur" role="gridcell">${fmt(n.brut)}</td>
      <td class="num arbo-dette ${n.dette ? 'is-dette' : ''}" role="gridcell">${n.dette ? fmt(n.dette) : '—'}</td>
      <td class="num arbo-net ${net < 0 ? 'is-negatif' : ''}" role="gridcell">${fmt(net)}
        <span class="arbo-pv-mobile">${_cellulePv(n)}</span></td>
      <td class="num arbo-pv" role="gridcell">${_cellulePv(n)}</td>
      <td class="arbo-actions" role="gridcell">${actions}</td>
    </tr>
    ${ouvert ? _enfants(n, total, couleur) : ''}`;
}

function _enfants(n, total, couleur) {
  if (n.enfants?.length) return n.enfants.map(e => _ligne(e, total, couleur)).join('');
  if (!n.titres) return '';
  const h = _lignesTitres.get(n.position.id);
  if (!h || h === 'chargement') {
    if (!h) _chargerTitres(n.position.id);
    return `<tr class="arbo-l${n.niveau + 1}" role="row" aria-level="${n.niveau + 2}"><td class="arbo-nom" colspan="7">
      <div class="arbo-nom-in arbo-attente" style="--niv:${n.niveau + 1}"><span class="arbo-chevron-vide"></span>Chargement des lignes…</div></td></tr>`;
  }
  const pct = n.position.ownership_pct ?? 1;
  return h.map(t => {
    const v = (t.effective_value ?? t.market_value ?? 0) * pct;
    const cb = t.cost_basis, mv = t.market_value;
    const connu = cb && !(mv != null && Math.abs(cb - mv) < 0.01);
    const g = connu ? (((t.effective_value ?? mv ?? 0) - cb) * pct) : null;
    return _ligne({
      cle: `h${t.id}`, niveau: n.niveau + 1,
      nom: t.name || t.isin, sous: t.isin && t.name ? t.isin : '',
      chip: '', brut: v, dette: 0, gain: 0, mesures: 0, enfants: [],
      pvHtml: g == null ? '<span class="arbo-pv-na">PRU inconnu</span>'
        : `<span class="${g >= 0 ? 'pv-hausse' : 'pv-baisse'}">${g >= 0 ? '+' : '−'}${fmt(Math.abs(g))}</span>`,
    }, total, couleur);
  }).join('');
}

async function _chargerTitres(id) {
  _lignesTitres.set(id, 'chargement');
  try {
    const r = await api('GET', `/api/positions/${id}/holdings`, null, { silent: true });
    _lignesTitres.set(id, (r.holdings || []).slice().sort((a, b) =>
      (b.effective_value ?? b.market_value ?? 0) - (a.effective_value ?? a.market_value ?? 0)));
  } catch {
    _lignesTitres.set(id, []);
  }
  if (_dernier) renderArbo(_dernier.positions);
}

let _dernier = null;

export function renderArbo(positions) {
  _lireReglages();
  _dernier = { positions };
  _calculerInitiales(S.positions || positions);
  const hote = document.getElementById('positions-tree-body');
  if (!hote) return;
  _cablerBarre();

  let racines = _trier(_racines());
  const q = _recherche.trim().toLowerCase();
  // Une nouvelle recherche repart des groupes ouverts d'office.
  if (q !== _rechercheVue) { _fermesRecherche = new Set(); _rechercheVue = q; }
  _forces = new Set();
  if (q) racines = _filtrer(racines, q);
  const t = _somme(racines);

  if (!racines.length) {
    hote.innerHTML = `<p class="arbo-vide">${q ? `Aucun compte ne correspond à « ${esc(_recherche)} ».` : 'Aucune position pour cet arrêté.'}</p>`;
    return;
  }
  hote.innerHTML = `
    <div class="arbo-wrap">
      <table class="arbo" role="treegrid" aria-label="Arborescence des positions">
        <thead>
          <tr>
            ${_th('nom', 'Nom', '')}
            ${_th('brut', 'Part du brut', 'arbo-part')}
            ${_th('brut', 'Valeur', 'num arbo-valeur', true)}
            ${_th('dette', 'Dette', 'num arbo-dette')}
            ${_th('net', 'Net', 'num arbo-net')}
            ${_th('pv', 'Plus-value', 'num arbo-pv')}
            <th scope="col" class="arbo-actions"><span class="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>${racines.map(r => _ligne(r, t.brut)).join('')}</tbody>
        <tfoot>
          <tr>
            <td>Patrimoine${q ? ' (filtré)' : ''}</td>
            <td class="arbo-part"></td>
            <td class="num arbo-valeur">${fmt(t.brut)}</td>
            <td class="num arbo-dette ${t.dette ? 'is-dette' : ''}">${t.dette ? fmt(t.dette) : '—'}</td>
            <td class="num arbo-net">${fmt(t.brut - t.dette)}</td>
            <td class="num arbo-pv">${t.mesures ? `<span class="${t.gain >= 0 ? 'pv-hausse' : 'pv-baisse'}">${t.gain >= 0 ? '+' : '−'}${fmt(Math.abs(t.gain))}</span>` : ''}</td>
            <td class="arbo-actions"></td>
          </tr>
        </tfoot>
      </table>
    </div>`;
}

/** Un en-tete triable : un vrai bouton, et l'etat annonce par aria-sort.
 *  « Part du brut » et « Valeur » trient la meme chose ; seule la seconde
 *  porte l'etat, pour ne pas l'annoncer deux fois. */
function _th(col, texte, cls, porteEtat = col !== 'brut') {
  const actif = _tri.col === col;
  const sens = actif ? (_tri.sens > 0 ? 'ascending' : 'descending') : 'none';
  const fleche = actif ? (_tri.sens > 0 ? ' ▲' : ' ▼') : '';
  return `<th scope="col" class="${cls}"${porteEtat ? ` aria-sort="${sens}"` : ''}>
    <button type="button" class="arbo-tri" data-arbo-tri="${col}">${texte}<span aria-hidden="true">${fleche}</span></button></th>`;
}

// ── Barre d'outils : recherche, regroupement, tout deplier ──────────────
let _barreCablee = false;
function _cablerBarre() {
  document.querySelectorAll('[data-arbo-groupe]').forEach(b =>
    b.setAttribute('aria-pressed', String(b.dataset.arboGroupe === _groupe)));
  if (_barreCablee) return;
  _barreCablee = true;

  const rerendre = () => _dernier && renderArbo(_dernier.positions);
  document.getElementById('arbo-groupes')?.addEventListener('click', e => {
    const b = e.target.closest('[data-arbo-groupe]');
    if (!b || b.dataset.arboGroupe === _groupe) return;
    _groupe = b.dataset.arboGroupe;
    _ouverts = null;                       // chaque lecture a ses propres noeuds
    _memoriser();
    rerendre();
  });
  let attente = null;
  document.getElementById('arbo-recherche')?.addEventListener('input', e => {
    clearTimeout(attente);
    attente = setTimeout(() => { _recherche = e.target.value; rerendre(); }, 150);
  });
  document.getElementById('arbo-deplier')?.addEventListener('click', () => {
    const toutes = new Set();
    const racines = _racines();
    const parcourir = ns => ns.forEach(n => { if (n.enfants?.length) { toutes.add(n.cle); parcourir(n.enfants); } });
    parcourir(racines);
    _ouverts = toutes; _memoriser(); rerendre();
  });
  document.getElementById('arbo-replier')?.addEventListener('click', () => {
    _ouverts = new Set(); _memoriser(); rerendre();
  });

  const hote = document.getElementById('positions-tree-body');
  hote?.addEventListener('click', e => {
    const tri = e.target.closest('[data-arbo-tri]');
    if (tri) {
      const col = tri.dataset.arboTri;
      // Premier clic : decroissant sur un montant — on cherche le plus gros —,
      // croissant sur un nom.
      _tri = _tri.col === col ? { col, sens: -_tri.sens } : { col, sens: col === 'nom' ? 1 : -1 };
      _memoriser();
      rerendre();
      hote.querySelector(`[data-arbo-tri="${col}"]`)?.focus();
      return;
    }
    const bas = e.target.closest('[data-arbo-basculer]');
    if (bas) {
      const cle = bas.dataset.arboBasculer;
      if (_forces.has(cle)) {
        // Ouvert par la recherche : le replier ne touche pas l'etat memorise.
        _fermesRecherche.has(cle) ? _fermesRecherche.delete(cle) : _fermesRecherche.add(cle);
      } else {
        if (!_ouverts) {
          // Premier geste : on part de l'etat par defaut, meme regle qu'au rendu.
          _ouverts = new Set(_racines().filter(_ouvertParDefaut).map(r => r.cle));
        }
        _ouverts.has(cle) ? _ouverts.delete(cle) : _ouverts.add(cle);
        _memoriser();
      }
      rerendre();
      // Le focus reste sur le chevron qu'on vient d'actionner.
      hote.querySelector(`[data-arbo-basculer="${CSS.escape(cle)}"]`)?.focus();
    }
  });
}

/** Une ligne de titres modifiee : on les redemandera a la prochaine ouverture. */
export function oublierTitres(id) {
  if (id == null) _lignesTitres.clear(); else _lignesTitres.delete(id);
}
