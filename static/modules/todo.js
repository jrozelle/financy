/**
 * Barre « À traiter » de la synthèse.
 *
 * Remplace trois bandeaux empiles sans hierarchie par une zone unique, et rend
 * visibles des signaux qui ne l'etaient que dans le bon onglet — un ecart de
 * quantite ne se voyait que depuis Actifs, un cours perime nulle part.
 *
 * Repliee par defaut sur UNE ligne : les indicateurs de patrimoine sont ce
 * qu'on vient voir, trois items deplies les repoussaient sous la ligne de
 * flottaison. Mais replier n'est pas cacher — la barre nomme le probleme le
 * plus grave et denombre le reste, on sait quoi sans deplier.
 *
 * Deux sources fusionnees :
 * - le serveur (`/api/todo`) pour ce qui se calcule en base : ecarts de
 *   quantite, cours perimes, flux provisoires ;
 * - l'appelant, pour ce que le front evalue deja contre la synthese en main
 *   (double-comptage d'entites, seuils definis par l'utilisateur).
 */
import { api } from './api.js';
import { fmt, esc } from './utils.js';

const HOTE = 'todo-zone';
const ORDRE = { warn: 0, info: 1 };

let _serveur = [];
let _front = [];
let _ouvert = false;
let _switchTab = null;
let _jeton = 0;

/** Injecte la navigation : todo.js ne connait pas main.js, qui l'importe. */
export function wireTodo(switchTab) {
  _switchTab = switchTab;
}

export async function loadTodo(date, signauxFront = []) {
  // Changer vite d'arrete ou de titulaire lance plusieurs requetes : seule la
  // derniere ecrit, une reponse lente ne remet pas les signaux d'un autre arrete.
  const jeton = ++_jeton;
  let serveur;
  try {
    const d = await api('GET', `/api/todo${date ? `?date=${date}` : ''}`, null, { silent: true });
    serveur = d.signaux || [];
  } catch {
    serveur = [];        // un controle indisponible ne doit pas vider la page
  }
  if (jeton !== _jeton) return;
  _front = signauxFront;
  _serveur = serveur;
  render();
}

/** Reaffiche avec les signaux serveur deja recus : la bascule du mode
 *  discretion ne change que l'ecriture des montants. */
export function renderTodo(signauxFront = _front) {
  _front = signauxFront;
  render();
}

function tous() {
  return [..._serveur, ..._front]
    .sort((a, b) => (ORDRE[a.severite] ?? 9) - (ORDRE[b.severite] ?? 9));
}

function render() {
  const hote = document.getElementById(HOTE);
  if (!hote) return;
  const signaux = tous();

  if (!signaux.length) {
    hote.replaceChildren();
    hote.classList.add('hidden');
    return;
  }
  hote.classList.remove('hidden');

  const tete = signaux[0];
  const reste = signaux.length - 1;
  const grave = signaux.some(s => s.severite === 'warn');

  hote.innerHTML = `
    <section class="todo${grave ? ' todo--warn' : ''}">
      <button type="button" class="todo-bar" id="todo-toggle"
              aria-expanded="${_ouvert}" aria-controls="todo-list">
        <span class="todo-count">${signaux.length}</span>
        <span class="todo-lead">${esc(tete.titre)}</span>
        ${tete.montant ? `<span class="todo-amount">${fmt(tete.montant)}</span>` : ''}
        ${reste ? `<span class="todo-more">et ${reste} autre${reste > 1 ? 's' : ''}</span>` : ''}
        <span class="todo-chev" aria-hidden="true">▾</span>
      </button>
      <div class="todo-list" id="todo-list"${_ouvert ? '' : ' hidden'}>
        ${signaux.map(item).join('')}
      </div>
    </section>`;

  document.getElementById('todo-toggle').addEventListener('click', () => {
    _ouvert = !_ouvert;
    render();
    // Le bouton est reconstruit : sans cela le focus tombait sur <body>.
    document.getElementById('todo-toggle')?.focus();
  });
  hote.querySelectorAll('[data-go]').forEach(b => {
    b.addEventListener('click', () => _switchTab?.(b.dataset.go));
  });
}

function item(s) {
  return `
    <div class="todo-item">
      <span class="todo-sev todo-sev--${s.severite === 'warn' ? 'warn' : 'info'}"></span>
      <div class="todo-texte">
        <b>${esc(s.titre)}</b>
        <p>${esc(s.detail || '')}${
          s.montant ? ` · <span class="num">${fmt(s.montant)}</span>` : ''}</p>
      </div>
      ${s.onglet && s.action
        ? `<button type="button" class="btn btn-sm todo-action" data-go="${esc(s.onglet)}">${esc(s.action)}</button>`
        : ''}
    </div>`;
}
