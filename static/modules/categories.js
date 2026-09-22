/**
 * Classement des categories en poches patrimoniales.
 *
 * Miroir de MACRO_BUCKETS dans `routes/synthese.py` — les deux doivent rester
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
