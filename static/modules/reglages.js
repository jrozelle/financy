/**
 * Fenêtre de réglages à onglets.
 *
 * Referentiel, Import / Export et Outils occupaient quatre lignes de navigation
 * permanente pour des ecrans qu'on ouvre quelques fois par an, a cote d'un
 * engrenage qui portait les preferences. Un seul point d'entree desormais, et
 * ces ecrans deviennent des onglets — le rail ne garde que ce qu'on consulte.
 *
 * Les ecrans d'administration sont DEPLACES dans la fenetre au demarrage :
 * ce sont de gros blocs de <main>, et leurs identifiants et ecouteurs
 * survivent au deplacement. Les boutons de preferences, eux, sont poses
 * directement par le gabarit.
 *
 * Ouvrir un onglet ici ne NAVIGUE PAS : le chargeur injecte remplit l'ecran
 * demande sans toucher a l'onglet courant. Passer par `switchTab` masquait
 * l'ecran visible derriere la fenetre et lui volait son titre de page.
 */

const ECRANS = ['referentiel', 'import', 'tools'];

let _ouvert = false;
let _charger = null;      // injecte : reglages.js ne connait pas main.js

export function wireReglages(chargerEcran) {
  _charger = chargerEcran;
  const modal = document.getElementById('reglages-modal');
  if (!modal) return;

  // Les ecrans d'administration rejoignent la fenetre.
  const accueil = document.getElementById('reglages-accueil');
  ECRANS.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    if (el && accueil) accueil.appendChild(el);
  });

  document.getElementById('ouvrir-reglages')?.addEventListener('click', () => ouvrir('preferences'));
  modal.querySelectorAll('[data-fermer-reglages]').forEach(b =>
    b.addEventListener('click', fermer));
  modal.querySelectorAll('[data-reglage]').forEach(b =>
    b.addEventListener('click', () => ouvrir(b.dataset.reglage)));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && _ouvert) fermer();
  });
}

/** Un onglet de la fenetre plutot qu'un ecran de l'application ? */
export const estUnReglage = tab => ECRANS.includes(tab);

export function ouvrir(quoi = 'preferences') {
  const modal = document.getElementById('reglages-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  _ouvert = true;

  modal.querySelectorAll('[data-reglage]').forEach(b =>
    b.setAttribute('aria-selected', String(b.dataset.reglage === quoi)));

  const prefs = document.getElementById('reglages-preferences');
  const accueil = document.getElementById('reglages-accueil');
  const surPrefs = quoi === 'preferences';
  prefs?.classList.toggle('hidden', !surPrefs);
  accueil?.classList.toggle('hidden', surPrefs);

  // Un seul ecran visible a la fois, et on le charge comme avant.
  ECRANS.forEach(t => {
    document.getElementById(`tab-${t}`)?.classList.toggle('hidden', t !== quoi);
  });
  if (!surPrefs) _charger?.(quoi);

  modal.querySelector(`[data-reglage="${quoi}"]`)?.focus();
}

function fermer() {
  document.getElementById('reglages-modal')?.classList.add('hidden');
  _ouvert = false;
  // Rien a restaurer : l'ecran de fond n'a jamais ete quitte.
}
