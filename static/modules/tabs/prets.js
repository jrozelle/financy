/**
 * Credits : l'onglet est ecrit en Svelte (frontend/src/credits/), compile
 * dans /dist/credits.js. Ce module garde les points d'entree que main.js
 * appelle, et charge l'ecran a la premiere visite.
 */
let _ecran = null;

async function _ecranCredits() {
  if (!_ecran) {
    const hote = document.getElementById('credits-app');
    if (!hote) return null;
    try {
      const { monter } = await import('/dist/credits.js');
      _ecran = monter(hote);
    } catch {
      // Clone sans compilation : dire quoi faire plutot qu'un onglet vide.
      hote.insertAdjacentHTML('beforeend', `<p class="card text-muted">L'écran Crédits n'est pas compilé :
        <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>, puis rechargez la page.</p>`);
      return null;
    }
  }
  return _ecran;
}

export async function loadPrets() {
  const ecran = await _ecranCredits();
  await ecran?.recharger();
}

/** Le formulaire de credit, depuis le bouton « Ajouter » de l'en-tete. */
export async function ouvrirFormulaireCredit() {
  const ecran = await _ecranCredits();
  await ecran?.ouvrirFormulaire();
}
