# Consignes permanentes Financy

## Workflow
- Branche de travail : `main`. La branche `claude/asset-import-tracking-8psft`
  est abandonnée à `2050474` — ne pas y revenir sans raison explicite.
- 1 commit par phase fonctionnelle, message clair en français
- Ne push jamais sans feu vert explicite de l'utilisateur
- Ne crée jamais de PR sans demande explicite
- Après chaque phase : rappeler la checklist de test local et attendre le feedback
- La documentation fait partie de chaque phase et de chaque revue : `TODO.md`
  (état d'avancement), `README.md` (ce que fait l'application), `README.dev.md`
  (mise en route) et `CLAUDE.md` se mettent à jour dans le même commit que la
  fonctionnalité. Une revue « complète » les relit aussi, pour la justesse et
  pas seulement pour les données personnelles.
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
- Un montant dit son perimetre. « Patrimoine financier » designe la poche de la
  synthese et elle seule ; un montant plus etroit porte son propre nom (« valeur
  mesuree », « lignes de titres », « arbitrable ») et se raccorde a elle quand
  l'ecran le permet.
- Colonnes de liste triables au clic, avec `aria-sort` et acces clavier.
- **Preferences de lecture en base** (colonnes, filtres, tris, vues, angle de
  la repartition, hypotheses de projection) : `lirePref` / `ecrirePref` de
  `static/modules/preferences.js`, cles `financy_*` listees dans `PARTAGEES`,
  lues au premier rendu et non au chargement du module. `localStorage` direct
  seulement pour ce qui depend de l'appareil : mode discretion, densite,
  noeuds ouverts de l'arbre.
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
  (`entity_snapshots.tresorerie`) pour ne jamais la recompter. Un releve se
  retire par son fichier (`supprimer_releves`) avec le solde d'ouverture qui
  en venait ; les arretes passes gardent leur tresorerie memorisee. Un compte dont le
  libelle ou la categorie porte le nom d'une entite est SA tresorerie : il entre
  dans son net, jamais dans l'epargne du titulaire.
- **Anciennete fiscale = date d'effet du contrat** (table `contrats`), jamais la
  date du premier arrete. Assurance-vie de moins de 8 ans ou PEA de moins de 5 :
  prelevement forfaitaire. Sans date, l'hypothese favorable reste, mais
  l'enveloppe dit combien de contrats la portent.
- **Epargne de precaution** (`services/precaution.py`, seule regle) : livrets et
  comptes d'epargne hors enveloppe de placement (PEL/CEL compris), et fonds
  euros ; jamais un compte courant, ni ce qui est bloque (liquidite « Bloqué »
  ou part mobilisable nulle : PER, contrat nanti), ni la tresorerie d'une
  societe. L'argent tenu au nom d'un titulaire est le sien. La cible est celle
  du profil, charges mensuelles x nombre de mois ; les propositions la gardent
  (livrets d'abord, fonds euros ensuite) et le DCA investit ce qui la depasse.
  Tant qu'elle n'est pas renseignee, la reserve libre du profil (`reserve_eur`,
  plus saisie) en tient lieu, et le constat le dit.
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
- Les propositions d'arbitrage portent sur le seul patrimoine FINANCIER, celui
  de la synthese — une seule definition, `services/categories.py` (miroir JS
  `static/modules/categories.js`) — moins la tresorerie d'entite (immobilier,
  objets, parts de societe, « Autre » et tresorerie hors calcul, decomptes),
  ranges dans les classes de la cible par `CLASSE_DE`, et ne
  puisent que dans la part libre : un contrat nanti, un PER, un produit
  structure comptent dans l'exposition sans etre proposes. Sans reserve
  declaree, les livrets reglementes sont gardes.
- Un credit se garde par defaut : le constat chiffre ce que serait le
  remboursement (placer l'argent au taux du contrat, indemnites deduites) ; pour
  une SCI ou une holding, la dette est le levier du montage.

## Code
- Pas d'emojis dans le code
- Dark mode cohérent dans toutes les nouvelles modales et popovers
- Tailles de texte : les paliers `--fs-*` de `:root` (`static/style.css`), jamais
  une valeur brute — y compris dans un `style=` en ligne ou un ecran Svelte. Une
  taille manquante prend le palier le plus proche. Seule exception : les 16 px
  `!important` des champs sur telephone, qui empechent le zoom d'iOS.
- Espacements (padding, margin, gap) : les paliers `--esp-*` (4 a 64 px), de
  meme ; restent en valeur brute les ajustements fins sous 3 px, les marges
  negatives et ce qui n'est pas un espacement (`scroll-padding`, positions).
- Toutes les migrations DB sont idempotentes (`CREATE IF NOT EXISTS`, `ALTER` dans try/except)
- Jamais de `DROP` ou `ALTER` destructif. Seule exception, levee par
  l'utilisateur pour le passage aux centimes : `_reconstruire_en_centimes`
  (`models.py`), qui copie, verifie ligne a ligne et n'efface l'ancienne table
  qu'une fois la copie prouvee, le tout annule au moindre ecart.
- **Montants en centimes entiers** : tout montant en euros stocke en base
  (liste : `services/montants.py`, `COLONNES` ; migrations 21 a 26), tables
  `STRICT`. Une nouvelle colonne de montant s'y ajoute, en `INTEGER`. Le reste du code parle
  en euros ; on convertit a la lecture et a l'ecriture (`centimes()`,
  `euros()`, `ligne_en_euros()`), jamais ailleurs. Cours unitaires, quantites,
  taux, parts et cout en dollars des appels au modele restent en `REAL`. Un test qui ecrit en SQL brut ecrit des
  centimes : un entier en euros passerait sans erreur, cent fois trop petit.
  Controle d'une migration : rejouer toutes les routes GET sur une copie de la
  base de prod, avant et apres, et comparer au centime.
- Endpoints : `@login_required` + CSRF systématique
- Inputs validés côté serveur (validate_date, validate_number, validate_pct, validate_string)

## Sécurité
- Pas de clé API en dur ni en base : variable d'environnement, sinon fichier
  `secrets.json` à côté de la base (hors git, hors sauvegardes et exports, droits
  600), via `services/settings.py`
- Mode démo (`is_demo_mode()`) : aucun appel réseau (providers et LLM mockés)
- Uploads : limite de taille, vérif MIME, stockage temporaire purgé
- Adresse du client : `adresse_client()` (`auth.py`), jamais `request.remote_addr`
  directement — derrière un proxy, c'est celle du proxy. `X-Forwarded-For` ne
  se lit que depuis les proxies de `FINANCY_PROXIES_DE_CONFIANCE`, de droite à
  gauche

## Architecture
- Stack : Python 3.12 / Flask 3 / SQLite, vanilla JS + Chart.js, templates serveur ;
  Svelte 5 + TypeScript pour les ecrans reecrits (`frontend/`)
- Modèles et migrations : `models.py` (liste `MIGRATIONS`, une fonction
  `_migration_NNN` par version ; ne jamais modifier une migration deja executee
  en prod, en ajouter une)
- Routes : blueprints dans `routes/`
- Frontend modulaire : `static/modules/` (un module par onglet dans `tabs/`)
- Ecrans Svelte 5 + TypeScript dans `frontend/` : tous les onglets et les
  ecrans des Reglages (Referentiel, Outils, Import / Export) ; les Preferences,
  les fenetres (fiches d'une position, d'un flux, d'un titre) et les modules partages
  restent en JavaScript dans `static/modules/`. Chaque ecran est
  une entree de `vite.config.ts`, monte par le module de son onglet
  (`afficher(cible, props)`),
  compiles par Vite dans `frontend_dist/` (hors git), servis sous `/dist/`,
  construits dans l'image (etape `node` du Dockerfile) : un changement d'ecran
  Svelte demande un rebuild, comme du Python. Un ecran reprend le balisage et
  les classes de celui qu'il remplace (style.css s'applique tel quel) et
  importe les modules existants par leur URL (`/static/modules/api.js`...) ;
  un montant ecrit par `fmt()` ne suit pas seul le mode discretion : la carte
  recoit `masque` et redessine sous `{#key masque}`. Svelte retire l'espace
  en tete d'un bloc `{#if}`, entre deux cellules et entre les elements d'une
  boucle — l'ecart de deux etiquettes `inline-flex` en dependait : une espace
  voulue s'ecrit `{' '}`. Chart.js reste la variable globale du gabarit
  (`types-app/chart-global.d.ts`). Types des modules existants
  dans `frontend/src/types-app/`. Avant de remplacer un ecran : texte
  et structure compares a l'ancien, sur une copie de la base, au caractere
  pres.
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
- État d'avancement : `TODO.md` (seule référence) ; l'historique des phases est dans `git log`
