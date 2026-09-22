/**
 * Fenêtre de réglages à onglets.
 *
 * Referentiel, Import / Export et Outils occupaient quatre lignes de navigation
 * permanente pour des ecrans qu'on ouvre quelques fois par an, a cote d'un
 * engrenage qui portait les preferences. Un seul point d'entree desormais, et
 * ces ecrans deviennent des onglets — le rail ne garde que ce qu'on consulte.
 *
 * Les ecrans existants ne sont pas reecrits : leurs noeuds sont DEPLACES dans
 * la fenetre. Identifiants et ecouteurs survivent, `switchTab` continue de les
 * charger comme avant, et l'onglet reste accessible par URL.
 */
import { S } from './state.js';

const ECRANS = ['referentiel', 'import', 'tools'];

let _ouvert = false;
let _charger = null;      // switchTab, injecte : reglages.js ne connait pas main.js

export function wireReglages(switchTab) {
  _charger = switchTab;
  const modal = document.getElementById('reglages-modal');
  if (!modal) return;

  // Les preferences reprennent les boutons deja construits, plutot que de les
  // dupliquer : un seul comportement, un seul endroit ou le corriger.
  deplacer('theme-toggle', 'pref-theme');
  deplacer('positions-col-picker', 'pref-col-positions');
  deplacer('actifs-col-picker', 'pref-col-actifs');
  deplacer('btn-open-settings', 'pref-api');
  deplacer('btn-keyboard-help', 'pref-raccourcis');

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
  if (!surPrefs) _charger?.(quoi, { pushHistory: false });

  modal.querySelector(`[data-reglage="${quoi}"]`)?.focus();
}

function fermer() {
  document.getElementById('reglages-modal')?.classList.add('hidden');
  _ouvert = false;
  // L'ecran de fond reprend la main : sans cela, l'onglet reste marque comme
  // courant alors que la fenetre est refermee.
  if (S.currentTab && !ECRANS.includes(S.currentTab)) _charger?.(S.currentTab, { pushHistory: false });
}

function deplacer(id, hote) {
  const el = document.getElementById(id);
  const h = document.getElementById(hote);
  if (el && h) h.appendChild(el);
}
