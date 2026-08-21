# Consignes permanentes Financy

## Workflow
- Branche de dev active : `claude/asset-import-tracking-8psft`
- 1 commit par phase fonctionnelle, message clair en français
- Ne push jamais sans feu vert explicite de l'utilisateur
- Ne crée jamais de PR sans demande explicite
- Après chaque phase : rappeler la checklist de test local et attendre le feedback

## Interface
- **Jamais d'attribut `title` natif pour une information necessaire.** Il ne
  s'affiche pas de facon fiable (Firefox, mobile, lecteurs d'ecran), et une
  liste de plusieurs elements y est illisible. Une information indispensable
  s'affiche : ligne visible, panneau depliable (`aria-expanded` + bouton), ou
  popover maison. Le `title` reste acceptable pour une precision purement
  facultative sur un element deja explicite.
- Un element ecarte d'un calcul ne disparait jamais sans explication : il figure
  dans un decompte, et le detail est consultable (statut, valeur, date).
- Colonnes de liste triables au clic, avec `aria-sort` et acces clavier.
- Chart.js : jamais d'echelle `category` pour une serie temporelle — les points
  seraient equidistants et la pente faussee. Echelle numerique sur l'epoch, et
  toutes les series alignees sur la meme liste d'abscisses (les trous a `null`),
  sans quoi le mode d'interaction `index` regroupe les points par position dans
  le tableau et melange les dates.

## Donnees financieres
- **Flux provisoires** : un mouvement connu mais pas encore atteste par un
  document se saisit avec la mention `[provisoire]` dans ses notes (constante
  `PROVISIONAL`, `routes/movements_import.py`). L'import du document de
  reference le REDATE et lui retire la mention, sans creer de doublon. Sans
  cette mention, un flux equivalent est traite comme doublon et laisse intact.
- Le rapprochement de deux flux se fait sur `(personne, enveloppe,
  etablissement, type, montant)` a `TOLERANCE_JOURS` pres, jamais sur la date
  exacte : deux documents ne datent pas le meme mouvement pareil — prelevement
  en debut de mois sur le compte courant, investissement une dizaine de jours
  plus tard chez l'assureur.
- **Un arbitrage de valorisation ne se fait jamais en silence.** Quand le modele
  prefere la valeur enregistree au cours du jour (divergence, devise etrangere,
  titre non cote), il le signale : `holding_price_warning()` dans `models.py`,
  remonte par `/api/performance` et affiche dans le panneau depliable. Ce choix
  muet a masque des mois durant deux titres du Nasdaq cotes en dollars et
  declares EUR — la valorisation n'etait juste que parce que l'ecart depassait
  le seuil de divergence.
- Aucune conversion de devise dans `models.py` : un cours libelle hors euro ne
  doit donc JAMAIS servir a valoriser une ligne. La devise vient du provider
  (`fetch_currency`), pas du defaut du schema.
- Ne comptent comme flux EXTERNES ni les dividendes ni les frais : les premiers
  sont produits par les actifs detenus, les seconds preleves a l'interieur du
  contrat. Tous deux appartiennent au rendement, pas aux apports.

## Code
- Pas d'emojis dans le code
- Dark mode cohérent dans toutes les nouvelles modales et popovers
- Toutes les migrations DB sont idempotentes (`CREATE IF NOT EXISTS`, `ALTER` dans try/except)
- Jamais de `DROP` ou `ALTER` destructif
- Endpoints : `@login_required` + CSRF systématique
- Inputs validés côté serveur (validate_date, validate_number, validate_pct, validate_string)

## Sécurité
- Pas de clé API en dur : variables d'environnement uniquement
- Mode démo (`is_demo_mode()`) : aucun appel réseau (providers et LLM mockés)
- Uploads : limite de taille, vérif MIME, stockage temporaire purgé

## Architecture
- Stack : Python 3.12 / Flask 3 / SQLite, vanilla JS + Chart.js, templates serveur
- Modèles et migrations : `models.py` (`MIGRATIONS` ligne 313)
- Routes : blueprints dans `routes/`
- Frontend modulaire : `static/modules/`
- SPA unique : `templates/index.html`

## Environnement
- Dev local : venv Python + SQLite locale (`financy_dev.db`)
- Prod : Docker sur dclab
- Pas de préprod Docker intermédiaire

## Roadmap en cours
- Feature actifs & conseil patrimonial : voir `docs/plan-actifs-conseil.md`
- État d'avancement : voir `TODO.md` section « Actifs & conseil patrimonial »
