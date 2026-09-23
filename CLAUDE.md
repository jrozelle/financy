# Consignes permanentes Financy

## Workflow
- Branche de travail : `main`. La branche `claude/asset-import-tracking-8psft`
  est abandonnée à `d045e86` — ne pas y revenir sans raison explicite.
- 1 commit par phase fonctionnelle, message clair en français
- Ne push jamais sans feu vert explicite de l'utilisateur
- Ne crée jamais de PR sans demande explicite
- Après chaque phase : rappeler la checklist de test local et attendre le feedback
- Déploiement prod : `git pull` dans le dépôt déployé, puis
  `docker compose up -d --build financy` depuis le projet compose parent (le
  conteneur n'appartient pas au compose de `app/`). `static/` et `templates/`
  sont montés en lecture seule : un changement de `static/` ne demande qu'un
  `git pull`, un gabarit un `docker restart financy` (Jinja ne recharge pas),
  du Python un rebuild. Hôte, chemins et accès : `CLAUDE.local.md` (non
  versionné).
- Toute mutation de la base prod est précédée d'une copie datée
  `patrimoine.db.bak-AAAAMMJJ-HHMM-<motif>` dans le dossier de la base, faite
  conteneur arrêté quand une migration suit, et d'une simulation affichant les
  lignes visées avant écriture.
- Rotation des copies (`services/backups.py`, après chaque sauvegarde de
  l'application) : tout 30 jours, puis la dernière de chaque mois, jamais moins
  des 10 plus récentes. Simulation : `python -m services.backups`.

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
- **Devises** : la devise d'un titre vient du provider (`fetch_currency`), pas
  du defaut EUR du schema. Un cours hors euro est converti par le taux de
  `fx_rates` ; a defaut de taux il ne valorise RIEN — additionner des dollars a
  des euros surevalue la ligne du change. Les taux se rafraichissent dans le
  meme cycle que les cours (`refresh_fx_rates`), une requete par devise
  effectivement detenue, jamais en tache de fond.
- Ne comptent comme flux EXTERNES ni les dividendes ni les frais : les premiers
  sont produits par les actifs detenus, les seconds preleves a l'interieur du
  contrat. Tous deux appartiennent au rendement, pas aux apports.
- **Epargne nouvelle ≠ versements.** Pour la famille, un versement sur un PEA
  depuis un livret suivi (le DCA) est un transfert interne ; le salaire, lui,
  arrive sur un compte courant sans aucun flux. L'epargne nouvelle se mesure
  donc : variation des liquidites (comptes presents aux deux arretes) plus
  versements vers les placements (`services/contribution.py`, `PLACEMENT`).
  « D'ou vient la hausse » decompose en quatre parts dont la somme redonne la
  variation — epargne nouvelle, capital rembourse, comptes ajoutes ou retires,
  performance — et la projection du patrimoine utilise la meme mesure. Par
  compte (onglet Performance), un versement reste un apport.
- **Le capital rembourse est de l'epargne**, pas de la performance. Sauf pour
  un pret **in fine** (`prets.est_in_fine`) : rembourse d'un bloc sur des actifs
  deja comptes, il n'enrichit pas et sort du desendettement projete.
- **Entites** : une SCPI se valorise au prix de RETRAIT (`entite_parts` ; a
  defaut de prix publie, souscription moins 10 %), pas au prix d'achat qui
  cache les frais d'entree. Sa tresorerie vient de ses releves
  (`entite_operations`) et chaque arrete d'entite memorise la part incluse
  (`entity_snapshots.tresorerie`) pour ne jamais la recompter. Un compte dont le
  libelle ou la categorie porte le nom d'une entite est SA tresorerie : il entre
  dans son net, jamais dans l'epargne du titulaire.
- **Anciennete fiscale = date d'effet du contrat** (table `contrats`), jamais la
  date du premier arrete. Assurance-vie de moins de 8 ans ou PEA de moins de 5 :
  prelevement forfaitaire. Sans date, l'hypothese favorable reste, mais
  l'enveloppe dit combien de contrats la portent.
- **Plafonds de livrets reglementes : livret par livret**, jamais sur la somme
  d'un titulaire (un parent tient les Livret A des enfants a son nom), avec une
  marge pour les interets capitalises.

## Documents importes
- **Tout lecteur de document se verifie lui-meme et refuse plutot que de
  deviner** : releve bancaire (solde initial + operations = solde final, totaux
  retrouves), tableau d'amortissement (restant du precedent − capital = restant
  du, zero a la fin, premiere echeance partant du montant du credit). Une
  colonne debit/credit se lit a la POSITION des mots quand le texte ne la dit
  pas (Credit Agricole).
- Reimporter un document n'ajoute rien : unicite sur l'operation ou sur
  `(montant, debut, fin)` du pret.
- Un scan sans texte se lit en image ; un formulaire PDF porte ses valeurs dans
  ses champs (`page.annots`).
- **Depot public** : aucun nom de personne ou d'entite reelle, aucun montant
  reel, aucun chemin personnel ni detail d'infrastructure dans le code, les
  tests, la documentation ou les messages de commit. Les jeux d'essai et les
  exemples sont fictifs (« SCI Exemple », « Holding Exemple », montants ronds).

## Conseil
- Les constats ne s'appuient que sur des faits verifiables et ne citent aucun
  taux de marche : le seul taux cite est celui d'un contrat. Pas de conseil
  generique : un « verifiez » sans chiffre n'est pas une proposition.
- Les propositions d'arbitrage portent sur le seul patrimoine FINANCIER
  (immobilier, objets, parts de societe et tresorerie d'entite hors calcul,
  decomptes), ranges dans les classes de la cible par `CLASSE_DE`, et ne
  puisent que dans la part libre : un contrat nanti, un PER, un produit
  structure comptent dans l'exposition sans etre proposes. Sans reserve
  declaree, les livrets reglementes sont gardes.
- Un credit se garde par defaut : le constat chiffre ce que serait le
  remboursement (placer l'argent au taux du contrat, indemnites deduites) ; pour
  une SCI ou une holding, la dette est le levier du montage.

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
- Modèles et migrations : `models.py` (liste `MIGRATIONS`, une fonction
  `_migration_NNN` par version ; ne jamais modifier une migration deja executee
  en prod, en ajouter une)
- Routes : blueprints dans `routes/`
- Frontend modulaire : `static/modules/` (un module par onglet dans `tabs/`)
- Services metier : `services/` — `prets.py` (echeanciers, IRA, projection),
  `tresorerie_entite.py` (releves, levier, parts, IS d'une entite),
  `contribution.py` (d'ou vient la hausse, epargne nouvelle), `fiscalite.py`
  (impot latent), `contrats.py` (anciennete), `advisor/` (constats,
  allocation, propositions) ; lecteurs de documents dans `services/parsers/`
- Application installable (PWA) : `static/manifest.json`, icones dans
  `static/icons/`
- SPA unique : `templates/index.html`

## Environnement
- Dev local : venv Python + SQLite locale (`financy_dev.db`)
- Prod : Docker sur un NAS (détails dans `CLAUDE.local.md`)
- Pas de préprod Docker intermédiaire

## Roadmap en cours
- Feature actifs & conseil patrimonial : voir `docs/plan-actifs-conseil.md`
- État d'avancement : voir `TODO.md` section « Actifs & conseil patrimonial »
