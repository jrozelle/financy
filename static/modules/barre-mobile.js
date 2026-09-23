/**
 * Barre du bas sur telephone : quels onglets y figurent, et dans quel ordre.
 *
 * Quatre onglets au plus (la cinquieme case est « Plus »), les autres passent
 * sous « Plus », dans l'ordre choisi. Le reglage vit en base
 * (`/api/preferences/barre-mobile`) : il se fait depuis n'importe quel
 * appareil. Sans reglage, la barre d'origine reste (Synthese, Positions,
 * Performance, Conseil).
 *
 * Classe propre au mobile (`m-cache`) : `fin-rail-sub` sert aussi, sur ecran
 * large, a indenter les sous-onglets du rail, et n'est pas touchee.
 */
import { api } from './api.js';
import { esc } from './utils.js';
import { toast } from './dialogs.js';

const MAX = 4;
let _pref = null;

const rail = () => document.getElementById('fin-rail');
const items = () => [...(rail()?.querySelectorAll('.fin-rail-item[data-tab]') || [])];
const nom = el => el.querySelector('.fin-rail-lib')?.textContent.trim() || el.dataset.tab;

function _defaut() {
  const tous = items();
  return { ordre: tous.map(e => e.dataset.tab), visibles: tous.filter(e => !e.classList.contains('fin-rail-sub')).map(e => e.dataset.tab) };
}

function _etat() {
  const d = _defaut();
  if (!_pref?.visibles?.length) return d;
  const ordre = [...(_pref.ordre || []).filter(t => d.ordre.includes(t)), ...d.ordre.filter(t => !(_pref.ordre || []).includes(t))];
  return { ordre, visibles: _pref.visibles.filter(t => d.ordre.includes(t)) };
}

export async function initBarreMobile() {
  try { _pref = await api('GET', '/api/preferences/barre-mobile', null, { silent: true }); } catch { _pref = {}; }
  _appliquer();
}

function _appliquer() {
  const r = rail();
  if (!r) return;
  const { ordre, visibles } = _etat();
  r.classList.toggle('m-perso', Boolean(_pref?.visibles?.length));
  items().forEach(el => {
    const t = el.dataset.tab;
    // Dans la barre, les onglets choisis dans leur ordre ; sous « Plus », les
    // autres a la suite.
    const rang = visibles.includes(t) ? visibles.indexOf(t) : MAX + ordre.indexOf(t);
    el.style.setProperty('--m-rang', String(rang + 1));
    el.classList.toggle('m-cache', !visibles.includes(t));
  });
}

async function _enregistrer(etat) {
  _pref = etat;
  _appliquer();
  _rendre();
  try { await api('PUT', '/api/preferences/barre-mobile', etat); }
  catch { toast('Barre du bas non enregistrée', 'error'); }
}

/** L'editeur, dans les preferences : poignee a glisser (ou fleches du
 *  clavier), case « dans la barre ». */
export function rendreEditeurBarre() { _rendre(); }

function _rendre() {
  const hote = document.getElementById('pref-barre');
  if (!hote) return;
  const { ordre, visibles } = _etat();
  const noms = Object.fromEntries(items().map(e => [e.dataset.tab, nom(e)]));
  // Les onglets de la barre en tete, dans leur ordre ; puis ceux sous « Plus ».
  const liste = [...visibles, ...ordre.filter(t => !visibles.includes(t))];
  hote.innerHTML = `
    <ul class="barre-liste" aria-label="Onglets de la barre du bas">
      ${liste.map((t, i) => `<li class="barre-ligne${visibles.includes(t) ? ' dans-barre' : ''}" data-tab="${t}">
        <button type="button" class="w-poignee" aria-label="Déplacer « ${esc(noms[t])} », position ${i + 1} : glisser, ou flèches">
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><g fill="currentColor"><circle cx="5" cy="3" r="1.3"/><circle cx="11" cy="3" r="1.3"/><circle cx="5" cy="8" r="1.3"/><circle cx="11" cy="8" r="1.3"/><circle cx="5" cy="13" r="1.3"/><circle cx="11" cy="13" r="1.3"/></g></svg>
        </button>
        <span class="barre-nom">${esc(noms[t])}</span>
        <label class="barre-case"><input type="checkbox" ${visibles.includes(t) ? 'checked' : ''}
          ${!visibles.includes(t) && visibles.length >= MAX ? 'disabled' : ''}> dans la barre</label>
      </li>`).join('')}
    </ul>
    <p class="form-aide">${visibles.length} sur ${MAX} : la cinquième case est « Plus », qui ouvre les autres onglets.
      <button type="button" class="btn-link" id="barre-defaut">Barre d’origine</button></p>`;
  hote.querySelectorAll('.barre-ligne').forEach(li => {
    const t = li.dataset.tab;
    li.querySelector('input').addEventListener('change', e => {
      const v = e.target.checked ? [...visibles, t] : visibles.filter(x => x !== t);
      if (!v.length) { e.target.checked = true; toast('Au moins un onglet dans la barre', 'error'); return; }
      _enregistrer({ ordre: liste, visibles: liste.filter(x => v.includes(x)) });
    });
    const p = li.querySelector('.w-poignee');
    p.addEventListener('keydown', e => {
      const pas = { ArrowUp: -1, ArrowDown: 1 }[e.key];
      if (!pas) return;
      e.preventDefault();
      const l = [...liste], i = l.indexOf(t), j = Math.max(0, Math.min(l.length - 1, i + pas));
      l.splice(i, 1); l.splice(j, 0, t);
      _enregistrer({ ordre: l, visibles: l.filter(x => visibles.includes(x)) });
      hote.querySelector(`.barre-ligne[data-tab="${t}"] .w-poignee`)?.focus();
    });
    p.addEventListener('pointerdown', e => _glisser(e, li, liste, visibles));
  });
  hote.querySelector('#barre-defaut')?.addEventListener('click', async () => {
    _pref = {};
    _appliquer(); _rendre();
    try { await api('PUT', '/api/preferences/barre-mobile', {}); } catch { /* toast deja affiche */ }
  });
}

function _glisser(e, li, liste, visibles) {
  e.preventDefault();
  const p = e.currentTarget, ul = li.parentElement;
  p.setPointerCapture(e.pointerId);
  li.classList.add('w-glisse');
  const bouger = ev => {
    // Glisser verticalement : la ligne passe devant celle dont le centre est
    // franchi.
    const autres = [...ul.children].filter(x => x !== li);
    const apres = autres.find(x => ev.clientY < x.getBoundingClientRect().top + x.offsetHeight / 2);
    ul.insertBefore(li, apres || null);
  };
  const lacher = () => {
    p.removeEventListener('pointermove', bouger);
    p.removeEventListener('pointerup', lacher);
    p.removeEventListener('pointercancel', lacher);
    li.classList.remove('w-glisse');
    const l = [...ul.children].map(x => x.dataset.tab);
    // L'ordre de la liste decide aussi de qui est dans la barre : les
    // cochees, dans l'ordre ou elles se trouvent.
    if (l.join() !== liste.join()) _enregistrer({ ordre: l, visibles: l.filter(x => visibles.includes(x)) });
  };
  p.addEventListener('pointermove', bouger);
  p.addEventListener('pointerup', lacher);
  p.addEventListener('pointercancel', lacher);
}
