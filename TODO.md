Todo :
- [x] prendre en compte les entités dans le dashboard (tableau entités dans Synthèse)
- [x] créer une vision par catégorie, par enveloppe et par mobilisabilité, pour chaque personne (onglet Analyse)
- [x] dans l'onglet positions, ajouter un bouton pour filtrer par personne, enveloppe ou établissement
- [x] trouver des pistes d'amélioration "finary like" (allocation cible vs réelle, performance)
- [x] les entités sont à 0 dans les positions (fix : valeur lue depuis l'entité au calcul)
- [x] donner du contenu interactif en cliquant sur les sommes de synthèse (drill-down panel)
- [x] % détention et % dette indépendants sur les entités
- [x] double-comptage entités : alerte si total % > 100%, silencieux si < 100% (indivision avec tiers)
- [x] bouton "Tous" doublon dans l'onglet Analyse → supprimé
- [x] responsive : scroll horizontal sur les tableaux trop larges
- [x] lorsque je mets à jour une position, créer automatiquement un nouveau snapshot à la date du jour en copiant toutes les positions inchangées
- [x] vue arborescente dans Positions et Analyse (personne → établissement → enveloppe → catégorie)
- [x] expand / collapse global et par niveau (établissements / enveloppes), récursif
- [x] versionnement des entités (table entity_snapshots, historique valorisation consultable)
- [x] suppression onglet Analyse (contenu redistribué dans Synthèse : graphe par enveloppe + historique par groupe)
- [x] nettoyage dead code Analyse dans app.js


--- Bugs (audit technique) ---

- [x] 🔴 Historique entités non versionné → table entity_snapshots, get_entity_map(date) avec subquery MAX
- [x] 🔴 Import sans déduplication → vérification avant INSERT
- [x] 🔴 Export JSON sans entités → entités incluses dans /api/export
- [x] 🔴 Dead code import : entity_values supprimé
- [x] 🟠 Snapshot coché par défaut → décochée par défaut
- [x] 🟠 Snapshot du jour écrasé silencieusement → confirmation si date cible existante
- [x] 🟡 renderPerf() re-fetche /api/flux → flux filtrés par plage de dates
- [x] 🟡 duplicateSnapshot : boucle await séquentielle → Promise.all
- [x] 🟡 /api/historique : une connexion SQLite par snapshot → une seule connexion
- [x] 🟡 Pas d'index sur positions.date → index ajouté dans init_db
- [x] 🔴 Listener délégué dans renderPositionsTree s'accumule → déplacé dans wireEvents sur le wrapper permanent
- [x] 🟠 Champ date snapshot reste visible quand la checkbox est décochée → masqué par défaut, visible si cochée
- [x] 🟠 Allocation cible (localStorage) non exportée → incluse dans l'export JSON, restaurée à l'import JSON


--- Cohérence données / UX ---

Formulaire position :
- [x] 🟠 Masquer % propriété et % dette si aucune entité sélectionnée
- [x] 🟠 Valeur brute et Dette en lecture seule quand entité sélectionnée
- [x] 🟡 Enveloppe "Dette" → à supprimer via l'onglet Référentiel (accessible maintenant)
- [x] 🟡 Guider le champ "Établissement" pour les positions-entité → placeholder + auto-fill si entité sélectionnée
- [x] 🟡 Ordre des champs : Entité remonté avant Valeur/Dette dans le formulaire

Tableau des positions :
- [x] 🟠 Afficher gross_attributed / debt_attributed (valeurs attribuées)
- [x] 🟠 Badge % détention / % dette si ≠ 100%
- [x] 🟡 Entité visible sous l'établissement
- [x] 🟡 Indicateur visuel si notes

Vue arborescente positions :
- [x] 🟠 Boutons Éditer/Suppr. en hover uniquement → toujours visibles sur touch (media query)
- [x] 🟡 Pas de filtre/recherche dans la vue arborescente (contrairement au tableau)

Synthèse :
- [x] 🟠 Libellés KPI adaptatifs en vue personne
- [x] 🟠 Ligne personne highlightée dans le tableau "Par personne"
- [x] 🟠 Allocation cible recalculée sur le patrimoine de la personne
- [x] 🟠 Performance : label avec dates, flux filtrés sur la plage
- [x] 🟠 Tableau "Par personne" sorti des charts-row → pleine largeur, plus de troncature

Analyse :
- [x] 🟠 Colonne Propriétaire dans le tableau Détail
- [x] 🟡 Clarifier la valeur ajoutée d'Analyse vs Synthèse → onglet Analyse supprimé
- [x] 🟡 Vue arborescente : aucun message si la personne n'a aucune position → message affiché

Flux :
- [x] 🟡 Filtres (personne, type, année)
- [x] 🟡 Total et sous-totaux par type
- [x] 🟡 Pas de sous-total par personne dans Flux → ligne ajoutée dans le tfoot si plusieurs personnes

Entités :
- [x] 🟡 Avertissement rétroactivité dans le modal d'édition
- [x] 🟡 Mode de valorisation : libellé "documentaire uniquement" dans le référentiel

Référentiel :
- [x] 🔵 Onglet Référentiel : propriétaires, catégories + % mobilisabilité, enveloppes + liquidité + friction, listes types entités / valo / flux — tout éditable et persisté en DB
- [x] 🔵 Owners configurables (plus hardcodés dans app.py)
- [x] 🔵 Mobilisabilité par catégorie configurable (remplace CATEGORY_MOBILIZABLE hardcodé)
- [x] 🔵 Mobilisabilité surchargeable par position individuelle (colonne mobilizable_pct_override, badge ⚠)
- [x] 🟡 Suppression d'un propriétaire : avertir si des positions lui sont rattachées (avec le nombre)


--- Fonctionnel manquant ---

- [x] 🟠 Import JSON (symétrique de l'export) → route /api/import-json + UI ; allocation cibles restaurées
- [x] 🟡 Historique par enveloppe / catégorie (graphe "évolution de mon PEA" ou "évolution Actions") → carte "Évolution par" dans Synthèse
- [x] 🟡 Édition inline dans la vue arborescente (modifier la valeur sans ouvrir le modal complet)
- [ ] 🟡 Flux liés à une catégorie (croiser flux et positions : "versé X sur PEA, vaut Y aujourd'hui")
- [x] 🔵 Alertes configurables ("prévenir si Actions < 30%", "si cash > 20 000 €") → localStorage, évaluation dans Synthèse, config dans Référentiel


--- UX contextuelle ---

- [x] 🟠 Bouton "Ajouter une position" sur chaque ligne d'entité → modal pré-rempli (entité, établissement) + bascule sur l'onglet Positions
- [x] 🟠 Bouton "+" contextuel dans l'arborescence Positions : au niveau owner → pré-remplit propriétaire ; au niveau établissement → pré-remplit owner + établissement + entité si applicable ; au niveau enveloppe → pré-remplit owner + établissement + enveloppe
- [x] 🟡 Toast de confirmation après sauvegarde position / flux / entité
- [ ] 🟡 Vérification orphelins à la suppression d'enveloppe ou de catégorie dans le Référentiel
- [x] 🟡 Performance filtrée par personne (cohérence avec vue personne dans Synthèse) — flux et gains filtrés par owner


--- Sécurité ---

- [x] 🔴 Auth basique : mot de passe via variable d'env (FINANCY_PASSWORD) + session Flask, page de login, bouton déconnexion
- [x] 🔴 Protection CSRF sur les POST/PUT/DELETE (Flask-WTF ou token custom)
- [x] 🟠 Validation des inputs côté serveur (types numériques, dates ISO, longueur max, pourcentages)


--- Code backend ---

- [x] 🟠 Découper app.py (~950 lignes) en modules : models.py, routes/ (blueprints), referential.py
- [ ] 🟡 Supprimer le référentiel hardcodé — le transformer en seed d'init, ne garder que la lecture DB
- [ ] 🟡 Utiliser flask.g + teardown_appcontext pour une connexion DB par requête (pattern Flask standard)
- [ ] 🟡 Endpoint /api/backup : copie de patrimoine.db avec timestamp
- [ ] 🟡 Externaliser config dans des variables d'env (DB_PATH, port, mot de passe) via .env
- [ ] 🟡 Ajouter du logging minimal (import, reset, erreurs)


--- Code frontend ---

- [x] 🔴 Découper app.js (~2 660 lignes) en modules ES (state.js, api.js, tabs/*.js, charts.js, utils.js) avec <script type="module">
- [ ] 🟠 Audit XSS : vérifier que esc() est utilisé partout dans innerHTML / insertAdjacentHTML
- [x] 🟠 Migrer allocation cible de localStorage vers DB (table config) — API /api/targets GET/PUT, migration automatique au boot
- [x] 🟡 Migrer alertes de localStorage vers DB — API /api/alerts GET/PUT, migration automatique au boot
- [ ] 🟡 Wrapper apiFetch() centralisé : gestion d'erreurs réseau, toast d'erreur, retry
- [ ] 🟡 Copier Chart.js en local dans /static/vendor/ pour fonctionnement offline


--- UX ---

- [x] 🔴 Confirmation avant suppression (position, flux, entité, reset DB) : modal confirmDialog() custom avec détails de l'élément
- [x] 🟠 Dark mode avec toggle + support prefers-color-scheme — variables CSS, toggle dans navbar, persistance localStorage
- [x] 🟠 Navigation mobile : onglets scrollables horizontalement, navbar wrappée, touch-friendly
- [x] 🟠 Icône engrenage (⚙) dans la navbar : menu Paramètres regroupant Référentiel + Import/Export (libérer les onglets principaux)
- [x] 🟠 Expand/collapse arborescence : revoir l'UX (comportement, ergonomie, feedback visuel)
- [x] 🟠 Renommer l'app "Patrimoine Familial" en "Financy" (titre, navbar, login, README)
- [x] 🟠 CSS delta dette : couleurs inversées (hausse = rouge, baisse = vert)
- [x] 🟠 Barre de profondeur arborescence : remonter d'un niveau (Personne → Établ. → Env. → Position), ordre logique progressif
- [x] 🟠 Persister le choix vue arborescente / tableau en localStorage
- [x] 🟠 Revoir la palette de couleurs des graphes (surtout dark mode) — s'inspirer de Catppuccin Mocha
- [ ] 🟠 Synthèse : harmoniser les couleurs du tableau entités (retirer le rouge sur la dette ou ajouter du vert sur les totaux positifs)
- [ ] 🟠 Raccourcis clavier : Ctrl+N nouvelle position, Échap fermer modals, flèches naviguer entre snapshots
- [ ] 🟡 Spinner / skeleton pendant les appels API (surtout synthèse)
- [x] 🟡 Colonne % du total dans le tableau "Par personne"
- [ ] 🟡 Recherche globale : filtre positions + flux + entités simultanément
- [ ] 🟡 Date picker amélioré : saisie libre sur desktop, picker natif sur mobile


--- Features ---

- [x] 🟠 Variation entre snapshots : delta affiché sous chaque KPI (net avec %, gross, dette, mobilisable) via /api/synthese
- [x] 🟠 Export PDF / impression : bouton "Imprimer" dans Synthèse + CSS @media print (masque nav, boutons, onglets inactifs)
- [ ] 🟠 TRI (Taux de Rendement Interne) par enveloppe en croisant flux et valorisations
- [ ] 🟡 Objectif patrimoine : jauge de progression vers un montant cible dans la synthèse
- [ ] 🟡 Notes sur les snapshots : annoter un snapshot ("achat RP", "krach mars 2025")
- [ ] 🟡 Comparaison N / N-1 : variation YoY automatique dans la synthèse
- [ ] 🔵 Vue timeline : frise chronologique des événements patrimoniaux
- [ ] 🔵 Projection / simulation ("500 €/mois sur PEA pendant 10 ans")
- [ ] 🔵 Snapshot automatique programmé (dupliquer le dernier snapshot chaque mois)
- [ ] 🔵 Multi-devises (positions crypto / étrangères avec conversion manuelle ou automatique)


--- Qualité / DevOps ---

- [ ] 🟠 Tests unitaires Python (pytest) sur compute_position() et get_entity_map()
- [ ] 🟠 Tester et finaliser le Dockerfile
- [x] 🟡 DB de démo : fichier demo.db pré-rempli dans le repo (données 100% fictives et anonymisées, prénoms inventés, montants réalistes, multi-personnes, entités, flux, plusieurs snapshots) + bouton dans les Paramètres pour basculer entre DB réelle et DB démo à chaud
- [ ] 🟡 Migrations DB : table schema_version + scripts de migration séquentiels
- [ ] import : tester avec le vrai fichier rempli et valider les chiffres


--- Backlog / docs ---

- [x] faire la doc du projet (README)
- [x] tri croissant / décroissant au clic sur les en-têtes de colonnes (Positions, Flux, Entités)
