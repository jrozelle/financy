// Largeur d'ecran partagee par les cartes : au telephone (meme point de
// rupture que style.css, 780 px), les plus longues se raccourcissent.
const requete = typeof matchMedia === 'function' ? matchMedia('(max-width: 780px)') : null;

export const ecran = $state({ telephone: !!requete?.matches });
requete?.addEventListener('change', e => { ecran.telephone = e.matches; });
