/**
 * Selecteur de l'en-tete sur telephone : une etiquette a la largeur de la
 * valeur affichee, le <select> natif pose dessus, transparent.
 *
 * Un <select> prend la largeur de sa plus longue option, pas de celle qu'il
 * montre : dans une barre etroite, « Famille » devenait « Fami… », suivi d'un
 * blanc jusqu'au chevron. L'etiquette suit la valeur ; le select garde le
 * toucher, le clavier, la roue native d'iOS et son nom accessible.
 *
 * Sur ecran large, l'etiquette est masquee (CSS) et le select s'affiche tel
 * quel.
 */

const _setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');

export function etiqueter(sel, court = t => t) {
  if (!sel || sel.closest('.ctx-sel')) return;
  const hote = document.createElement('span');
  hote.className = 'ctx-sel';
  const val = document.createElement('span');
  val.className = 'ctx-val';
  val.setAttribute('aria-hidden', 'true');
  sel.replaceWith(hote);
  hote.append(val, sel);

  const maj = () => { val.textContent = court(sel.selectedOptions[0]?.textContent.trim() || ''); };
  // Trois facons de changer la valeur : le geste de l'utilisateur, une
  // affectation par le code (`sel.value = ...`), un remplacement des options.
  sel.addEventListener('change', maj);
  Object.defineProperty(sel, 'value', {
    configurable: true,
    get() { return _setter.get.call(this); },
    set(v) { _setter.set.call(this, v); maj(); },
  });
  new MutationObserver(maj).observe(sel, { childList: true, subtree: true });
  maj();
}

/** « 02/09/2026 » -> « 02/09/26 » : l'annee sur deux chiffres suffit a lire
 *  un arrete, et rend la place d'une icone. */
export const dateCourte = t => t.replace(/^(\d{2}\/\d{2}\/)\d{2}(\d{2})$/, '$1$2');
