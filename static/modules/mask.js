/**
 * Masquage d'affichage des montants (mode discretion).
 *
 * Sert a montrer l'interface sur les VRAIES donnees sans reveler le patrimoine :
 * demonstration par-dessus l'epaule, capture d'ecran, partage de bug.
 * N'altere aucune donnee — c'est une couche de formatage, reversible d'un clic.
 *
 * Forme retenue : `??? ??? 120,50 €`
 * - Les trois derniers chiffres de la partie entiere restent lisibles. Les
 *   totaux gardent ainsi de la vie (ils bougent, ils ont l'air vrais) la ou un
 *   bloc plein fige l'interface et la rend illisible a demontrer.
 * - Les groupes masques sont en nombre CONSTANT, meme pour 850 €. Sans cette
 *   largeur fixe, la longueur du nombre trahit l'ordre de grandeur aussi
 *   surement que le nombre lui-meme : `?? ???` contre `? ??? ???` se lit.
 *
 * Les quantites de titres sont masquees au meme titre que les euros : le cours
 * d'un ETF est public, une quantite visible suffit a retrouver le montant.
 */

const CLE = 'financy_mask';
const CAR = '?';                  // '*' fonctionne aussi, un seul endroit a changer
const GROUPES = 2;                // groupes de 3 caracteres masques, largeur fixe
const VISIBLES = 3;               // derniers chiffres laisses lisibles

const MASQUE = Array(GROUPES).fill(CAR.repeat(3)).join(' ');

let _actif = false;
const _abonnes = new Set();

/** Lecture du reglage persiste. localStorage peut lever (Safari prive). */
export function initMask() {
  try {
    _actif = localStorage.getItem(CLE) === '1';
  } catch { _actif = false; }
  _refleterDansLeDom();
  return _actif;
}

export const isMasked = () => _actif;

export function setMasked(on) {
  _actif = !!on;
  try {
    if (_actif) localStorage.setItem(CLE, '1');
    else localStorage.removeItem(CLE);
  } catch { /* session privee : le reglage ne survivra pas, tant pis */ }
  _refleterDansLeDom();
  _abonnes.forEach(fn => { try { fn(_actif); } catch { /* un abonne ne bloque pas les autres */ } });
}

export const toggleMask = () => setMasked(!_actif);

/** S'abonner aux bascules (les graphes doivent se redessiner). */
export function onMaskChange(fn) {
  _abonnes.add(fn);
  return () => _abonnes.delete(fn);
}

/** Marque l'etat sur <html> : le CSS peut styler les valeurs masquees. */
function _refleterDansLeDom() {
  if (typeof document === 'undefined') return;
  document.documentElement.classList.toggle('is-masked', _actif);
  document.querySelectorAll('[data-mask-toggle]').forEach(el => {
    el.setAttribute('aria-pressed', String(_actif));
  });
}

/**
 * Masque un nombre deja formate en francais, en gardant ses decimales.
 *
 * INVARIANT : la valeur passee doit etre ecrite EN ENTIER, jamais abregee.
 * Les trois chiffres laisses lisibles ne sont surs que si ce sont les unites,
 * dizaines et centaines. Sur une valeur abregee ils changent de rang et
 * trahissent tout : masquer "500 k€" rendrait "??? ??? 500 k€", soit
 * 500 000 € annonces en clair. Abreger et masquer ne se composent pas.
 * Pour un libelle abrege (axe de graphe), utiliser `maskAxis`, qui ne laisse
 * aucun chiffre.
 *
 * @param {string} texte  ex. "24 610,75"
 * @returns {string}      ex. "??? ??? 120,50"
 */
export function maskFormatted(texte) {
  const s = String(texte);
  const neg = /^[-−]/.test(s);
  // Le signe reste visible : perte ou gain se lit sans rien reveler du montant.
  const corps = neg ? s.slice(1) : s;
  const [entier, ...reste] = corps.split(',');
  const chiffres = entier.replace(/[^\d]/g, '');
  const queue = chiffres.slice(-VISIBLES).padStart(VISIBLES, '0');
  const dec = reste.length ? ',' + reste.join(',') : '';
  return (neg ? '−' : '') + MASQUE + ' ' + queue + dec;
}

/** Masque une valeur d'axe.
 *
 * Ne renvoie AUCUN chiffre, et c'est delibere : les libelles d'axes sont
 * abreges ("500 k€"), donc tout chiffre conserve y designerait des milliers ou
 * des millions. Un tick n'a de toute facon pas de chiffres utiles a montrer —
 * l'echelle se lit sur la forme de la courbe, pas sur ses graduations.
 */
export const maskAxis = () => MASQUE;
