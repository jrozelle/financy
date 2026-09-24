/**
 * Classement des categories en poches patrimoniales.
 *
 * Miroir de MACRO_BUCKETS dans `services/categories.py` — les deux doivent rester
 * synchronises. Ce module existe pour qu'il n'y ait qu'UNE copie cote client :
 * elle vivait dans synthese.js, et toute autre vue qui en avait besoin devait
 * la recopier.
 *
 * « Société » est l'ancien nom de « Parts sociales » : les deux sont listes,
 * une base non migree restant classee comme avant.
 */
export const MACRO_BUCKETS = {
  'Patrimoine financier':  ['Cash & dépôts', 'Monétaire', 'Obligations', 'Actions',
                            'Fond Euro', 'Produits Structurés', 'Crypto'],
  'Patrimoine immobilier': ['Immobilier', 'SCPI'],
  'Patrimoine autre':      ['Objets de valeur', 'Société', 'Parts sociales', 'Autre'],
};

/** Poche d'une categorie. Une categorie inconnue tombe dans « autre ». */
export function macroBucket(category) {
  for (const [bucket, cats] of Object.entries(MACRO_BUCKETS)) {
    if (cats.includes(category)) return bucket;
  }
  return 'Patrimoine autre';
}

/**
 * Une ligne relève-t-elle du patrimoine FINANCIER ?
 *
 * C'est la question qui separe un compte d'un bien : un PEA, un livret ou un
 * compte courant se tiennent, s'alimentent et se cloturent ; une maison, une
 * voiture ou des parts de SCI se possedent. Les melanger dans une liste de
 * comptes y fait entrer des lignes qui n'ont ni apport, ni frais, ni rendement
 * — et parfois une valeur negative, qui est une dette nette, pas un solde.
 *
 * @param {string[]} categories  categories portees par la ligne
 */
export const estFinancier = categories =>
  (categories || []).some(c => macroBucket(c) === 'Patrimoine financier');

/**
 * Nature d'une ligne, pour l'arborescence des positions.
 *
 * Plus fine que la poche : le patrimoine financier s'y partage entre ce qui
 * est DISPONIBLE (comptes, livrets) et ce qui est PLACE (PEA, assurance-vie,
 * PER...). C'est la premiere question qu'on pose a un patrimoine — combien
 * je peux sortir, combien travaille — et la poche ne la separait pas.
 */
export const NATURES = [
  { id: 'liq',   nom: 'Liquidités',            couleur: 'var(--nature-liq)',   aide: 'Comptes et livrets' },
  { id: 'fin',   nom: 'Placements financiers', couleur: 'var(--nature-fin)',   aide: 'PEA, assurance-vie, PER, titres' },
  { id: 'immo',  nom: 'Immobilier',            couleur: 'var(--nature-immo)',  aide: 'En direct, SCI, indivisions' },
  { id: 'biens', nom: 'Biens et sociétés',     couleur: 'var(--nature-biens)', aide: 'Objets de valeur, parts de société' },
];

/** Les especes d'un PEA ou d'une assurance-vie sont des « Cash & depots »,
 *  mais on ne les retire pas sans fermer ou racheter le contrat : ce ne sont
 *  pas des liquidites. L'enveloppe tranche. */
const ENVELOPPES_DE_PLACEMENT = new Set(['PEA', 'PEA-PME', 'Assurance-vie', 'PER', 'CTO', 'Crypto']);

export function natureDe(category, envelope) {
  if (category === 'Cash & dépôts') return ENVELOPPES_DE_PLACEMENT.has(envelope) ? 'fin' : 'liq';
  const poche = macroBucket(category);
  if (poche === 'Patrimoine financier') return 'fin';
  if (poche === 'Patrimoine immobilier') return 'immo';
  return 'biens';
}
