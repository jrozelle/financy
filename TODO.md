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
- [x] 🟡 Flux liés à une catégorie (croiser flux et positions : "versé X sur PEA, vaut Y aujourd'hui") → colonne catégorie ajoutée aux flux, filtre, formulaire
- [x] 🔵 Alertes configurables ("prévenir si Actions < 30%", "si cash > 20 000 €") → localStorage, évaluation dans Synthèse, config dans Référentiel


--- UX contextuelle ---

- [x] 🟠 Bouton "Ajouter une position" sur chaque ligne d'entité → modal pré-rempli (entité, établissement) + bascule sur l'onglet Positions
- [x] 🟠 Bouton "+" contextuel dans l'arborescence Positions : au niveau owner → pré-remplit propriétaire ; au niveau établissement → pré-remplit owner + établissement + entité si applicable ; au niveau enveloppe → pré-remplit owner + établissement + enveloppe
- [x] 🟡 Toast de confirmation après sauvegarde position / flux / entité
- [x] 🟡 Vérification orphelins à la suppression d'enveloppe ou de catégorie dans le Référentiel → confirmDialog avec nombre de positions/flux affectés
- [x] 🟡 Performance filtrée par personne (cohérence avec vue personne dans Synthèse) — flux et gains filtrés par owner


--- Sécurité ---

- [x] 🔴 Auth basique : mot de passe via variable d'env (FINANCY_PASSWORD) + session Flask, page de login, bouton déconnexion
- [x] 🔴 Protection CSRF sur les POST/PUT/DELETE (Flask-WTF ou token custom)
- [x] 🟠 Validation des inputs côté serveur (types numériques, dates ISO, longueur max, pourcentages)


--- Code backend ---

- [x] 🟠 Découper app.py (~950 lignes) en modules : models.py, routes/ (blueprints), referential.py
- [x] 🟡 Supprimer le référentiel hardcodé — le transformer en seed d'init, ne garder que la lecture DB → REFERENTIAL_TEMPLATES, seed à l'init, sélecteur de modèle dans Paramètres
- [x] 🟡 Utiliser flask.g + teardown_appcontext pour une connexion DB par requête (pattern Flask standard) → get_request_db() dans app.py, teardown auto
- [x] 🟡 Endpoint /api/backup : copie de patrimoine.db avec timestamp → POST /api/backup, dossier backups/, bouton dans Import/Export
- [x] 🟡 Externaliser config dans des variables d'env (DB_PATH, port, mot de passe) via .env → python-dotenv, .env.example, DB_PATH/PORT/SECRET_KEY/FINANCY_PASSWORD
- [x] 🟡 Ajouter du logging minimal (import, reset, erreurs) → logging Python, import/reset/login/backup/errors loggés


--- Code frontend ---

- [x] 🔴 Découper app.js (~2 660 lignes) en modules ES (state.js, api.js, tabs/*.js, charts.js, utils.js) avec <script type="module">
- [x] 🟠 Audit XSS : vérifier que esc() est utilisé partout dans innerHTML / insertAdjacentHTML
- [x] 🟠 Migrer allocation cible de localStorage vers DB (table config) — API /api/targets GET/PUT, migration automatique au boot
- [x] 🟡 Migrer alertes de localStorage vers DB — API /api/alerts GET/PUT, migration automatique au boot
- [x] 🟡 Wrapper apiFetch() centralisé : gestion d'erreurs réseau, toast d'erreur, retry → api() avec retry GET (2×), toast erreur auto, gestion TypeError réseau
- [x] 🟡 Copier Chart.js en local dans /static/vendor/ pour fonctionnement offline → chart.umd.min.js 4.4.0 en local


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
- [x] 🟠 Synthèse : harmoniser les couleurs du tableau entités (retirer le rouge sur la dette ou ajouter du vert sur les totaux positifs)
- [x] 🟠 Raccourcis clavier : Ctrl+N nouvelle position, Échap fermer modals, flèches naviguer entre snapshots
- [x] 🟡 Spinner / skeleton pendant les appels API (surtout synthèse) → spinner overlay dans switchTab + changement de date
- [x] 🟡 Colonne % du total dans le tableau "Par personne"
- [x] 🟡 Recherche globale : filtre positions + flux + entités simultanément → champ dans la navbar, recherche client-side, résultats groupés, raccourci /
- [x] 🟡 Date picker amélioré : saisie libre sur desktop, picker natif sur mobile → input[type=date] natif, placeholder, font-size 16px tactile


--- Features ---

- [x] 🟠 Variation entre snapshots : delta affiché sous chaque KPI (net avec %, gross, dette, mobilisable) via /api/synthese
- [x] 🟠 Export PDF / impression : bouton "Imprimer" dans Synthèse + CSS @media print (masque nav, boutons, onglets inactifs)
- [x] 🟠 TRI (Taux de Rendement Interne) par enveloppe en croisant flux et valorisations
- [x] 🟡 Objectif patrimoine : jauge de progression vers un montant cible dans la synthèse → barre de progression, API /api/wealth-target, prompt pour saisir/modifier
- [x] 🟡 Notes sur les snapshots : annoter un snapshot ("achat RP", "krach mars 2025") → table snapshot_notes, API, bandeau dans Synthèse, bouton "+ Note"
- [x] 🟡 Comparaison N / N-1 : variation YoY automatique dans la synthèse → label "N-1" sous chaque KPI avec delta et %
- [x] 🔵 Vue timeline : frise chronologique des événements patrimoniaux → onglet Outils, /api/timeline, graphe + frise
- [x] 🟡 Vue timeline de la valorisation d'une entité (graphe historique des snapshots entité) → graphe Chart.js dans le drilldown entité
- [x] 🔵 Projection / simulation ("500 €/mois sur PEA pendant 10 ans") → onglet Outils, /api/simulate, graphe capital vs investi
- [x] 🔵 Snapshot automatique programmé (dupliquer le dernier snapshot chaque mois) → POST /api/auto-snapshot, bouton dans Outils
- [x] 🔵 Multi-devises — retiré du scope


--- Qualité / DevOps ---

- [x] 🟠 Tests unitaires Python (pytest) sur compute_position() et get_entity_map()
- [x] 🟠 Tester et finaliser le Dockerfile
- [x] 🟡 DB de démo : fichier demo.db pré-rempli dans le repo (données 100% fictives et anonymisées, prénoms inventés, montants réalistes, multi-personnes, entités, flux, plusieurs snapshots) + bouton dans les Paramètres pour basculer entre DB réelle et DB démo à chaud
- [x] 🟡 Migrations DB : table schema_version + scripts de migration séquentiels → MIGRATIONS[], _get_schema_version, init_db idempotent
- [x] import : tester avec le vrai fichier rempli et valider les chiffres


--- Backlog / docs ---

- [x] faire la doc du projet (README)
- [x] tri croissant / décroissant au clic sur les en-têtes de colonnes (Positions, Flux, Entités)


--- Audit technique (avril 2026) ---

Quick wins :
- [x] 🔴 SECRET_KEY : supprimer le fallback hardcodé, crash si absent en prod → clé aléatoire + warning
- [x] 🔴 Upload XLSX : limiter la taille (MAX_CONTENT_LENGTH = 10 MB)
- [x] 🔴 Date YoY : remplacer la manipulation de string par datetime.date (crash sur 02-29)
- [x] 🟠 Dead code : supprimer get_request_db() / close_request_db() inutilisés dans app.py
- [x] 🟠 XSS confirmDialog : les appelants échappent déjà — message est intentionnellement HTML, pattern safe (N/A)
- [x] 🟡 CSS dark mode : .wealth-progress-bar.complete → var(--success) au lieu de #22c55e
- [x] 🟠 Empty catch blocks : remplacer par toast d'erreur (tools.js) ou commenter (synthese.js, referentiel.js)
- [x] 🟠 Exceptions internes exposées au client : messages génériques dans les réponses API d'erreur

Moyen terme :
- [x] 🔴 Validation imports XLSX/JSON : bornes %, dates ISO, longueurs, limites de lignes
- [x] 🟠 Tests d'intégration API : 90 tests (auth, positions, flux, entités, synthèse, tools, import/export, migrations)
- [x] 🟠 Dockerfile : USER non-root, HEALTHCHECK, EXPOSE 5017
- [x] 🟠 CSRF sur le formulaire login
- [x] 🟠 Race condition snapshot_update : BEGIN IMMEDIATE (transaction atomique)
- [x] 🟡 Validation bornes pourcentages : clamp 0–1 dans imports, validate_pct dans routes
- [x] 🟡 Validation annual_rate dans /api/simulate (bornes -50% à 100%)
- [x] 🟡 Notes max length côté serveur (2000 car. — positions, flux, entités)
- [x] 🟡 Gestion d'erreurs frontend cohérente : tout en toast, plus de alert()

Backlog :
- [x] 🟠 Rate limiting sur /login (10 tentatives / 5 min par IP)
- [x] 🟠 Session timeout (PERMANENT_SESSION_LIFETIME, configurable via SESSION_TIMEOUT_MINUTES)
- [x] 🟡 Version pinning requirements.txt (major version ranges)
- [x] 🟡 Global _demo_mode thread-safe → Flask g (request-local) avec fallback global
- [x] 🟡 Factoriser chart.destroy() → destroyChart() dans utils.js


--- Audit #2 (avril 2026) ---

Critiques :
- [x] 🔴 debug=True en production — conditionné sur FLASK_ENV != 'production'
- [x] 🔴 Comparaison mot de passe timing-safe — hmac.compare_digest
- [x] 🔴 Security headers — X-Frame-Options DENY, CSP, X-Content-Type-Options nosniff, Referrer-Policy
- [x] 🔴 Renommage entité → cascade sur entity_snapshots + positions.entity
- [x] 🔴 Suppression entité → 409 si positions liées, force=1 pour cascader (nullify entity)

Moyens :
- [x] 🟠 Cookies session : HttpOnly, SameSite=Lax, Secure (si FLASK_ENV=production)
- [x] 🟠 Backup API : filename au lieu du chemin serveur complet
- [x] 🟠 Session fixation : session.clear() + nouveau CSRF token après login
- [x] 🟠 Race condition auto-snapshot : BEGIN IMMEDIATE avant le check d'existence
- [x] 🟠 snapshot_update : validation new_values (validate_pct, validate_string, validate_date)
- [x] 🟠 snapshot_update : bloquer si source_date == target_date
- [x] 🟠 Index manquants : migration_004 — positions(owner), (entity), (date,owner)
- [x] 🟠 UX : prompt()/confirm() natifs → promptDialog + confirmDialog custom (6 occurrences)
- [x] 🟠 UX : loading state sur import XLSX/JSON (bouton disabled + texte "Import en cours…")
- [x] 🟠 UX : debounce 150ms sur la recherche arbo positions
- [x] 🟠 Config : validation type/bornes des variables d'env (_env_int helper) + SECRET_KEY length warning

Backlog :
- [x] 🟡 SECRET_KEY : warning si longueur < 32 caractères
- [x] 🟡 Flux hors plage snapshots inclus dans le TRI — filtrer ou avertir
- [x] 🟡 Catch silencieux dans alerts.js et targets.js — logger ou toast
- [x] 🟡 Focus trap dans les modales (accessibilité)
- [x] 🟡 ARIA labels manquants sur boutons icônes et recherche
- [x] 🟡 Cache getComputedStyle() pour les couleurs de graphes
- [x] 🟡 @media print : styles d'impression manquants
- [x] 🟡 Migration sans rollback si crash midway
- [x] 🟡 Pagination GET positions/flux/entities pour gros volumes


--- Actifs & conseil patrimonial ---

Spec détaillée : docs/plan-actifs-conseil.md
Branche : claude/asset-import-tracking-8psft

Setup :
- [x] Dev local : venv + .env.example + DB isolée financy_dev.db
- [x] Script scripts/seed_dev.py (owner, position PEA, 3 ISIN réels)
- [x] README.dev.md avec checklist de tests par phase

Phase 1 — Schéma holdings + CRUD manuel :
- [x] Migration _migration_005 (securities, holdings, price_history, holdings_snapshots)
- [x] routes/holdings.py — GET/PUT/POST/PATCH/DELETE (auth + CSRF)
- [x] compute_position adapté (holdings + is_priceable → Σ qty×last_price)
- [x] static/modules/holdings.js + modale « Gérer les lignes »
- [x] Validation ISIN (regex + checksum Luhn) + pseudo-ISIN fonds euros
- [x] Snapshots étendus pour holdings_snapshots (auto-snapshot, snapshot_update, endpoint manuel)
- [x] Import/export JSON round-trip securities + holdings + holdings_snapshots
- [x] Import XLSX onglets Securities + Holdings
- [x] Tests d'intégration (22 tests holdings, 132 au total)

Phase 2 — Provider cours + refresh manuel + popover :
- [x] requirements : yfinance + requests
- [x] services/prices.py (PriceProvider abstrait, YahooProvider, MockProvider)
- [x] Batching 10 + délai, try/except robuste, jamais de crash global
- [x] POST /api/prices/refresh (+ flag only_stale)
- [x] GET /api/prices/history/<isin>?period= avec backfill heuristique
- [x] POST /api/securities/<isin>/resolve-ticker
- [x] Bouton « Rafraîchir les cours » dans Outils (+ variante only_stale)
- [x] Badge fraîcheur dans la modale holdings (vert <1j, orange <7j, rouge sinon)
- [x] Résolution ISIN→ticker Yahoo lazy, cache dans securities.ticker, editable
- [x] Popover au clic ISIN : graphe 7J/30J/90J/1A + PRU + P&L + édition ticker
- [x] Tests : 14 nouveaux tests prices (mock provider), 146 au total

Phase 3 — Scheduler :
- [x] requirements : apscheduler
- [x] services/scheduler.py : BackgroundScheduler + cron trigger quotidien
- [x] Initialisation conditionnelle dans app.py (SCHEDULER_ENABLED=true)
- [x] max_instances=1 (anti-double-exécution) + coalesce + misfire grace
- [x] Shutdown propre via atexit
- [x] GET /api/scheduler/status pour diagnostic UI
- [x] Indicateur dans l'onglet Outils (état + prochain passage)
- [x] Configuration via env : SCHEDULER_HOUR / SCHEDULER_MINUTE / SCHEDULER_TZ
- [x] Tests : 5 nouveaux tests (job en isolation, status, init idempotent), 151 au total

Phase 4 — Import PDF :
- [x] requirements : pdfplumber
- [x] services/pdf_parser.py : extraction 2 couches (tableaux + lignes texte)
- [x] Heuristique auto : ISIN regex + Luhn + mapping qty/prix/valo par coherence
- [x] Fingerprint 15+ formats (Boursorama PEA/CTO, Fortuneo, Linxea, Spirica,
      Suravenir, Generali, Yomoni, Nalo, SwissLife, CA, BNP, SG, Bourse Direct...)
- [x] Score de confiance par ligne (0-1)
- [x] Upload securise (5 Mo, MIME, CSRF)
- [x] POST /api/envelope/<id>/import-pdf (step=preview + step=commit)
- [x] Frontend : bouton « Importer PDF… » dans la modale holdings,
      preview editable, statut format detecte + warnings
- [x] Full replace avec confirmation implicite (l'Enregistrer remplace tout)
- [x] Tests : 19 nouveaux tests (helpers + parser + route), 170 au total

Phase 5 — Onglet Actifs (optionnel) :
- [ ] Vue consolidée holdings (tri ISIN/poids/perf/fraîcheur)
- [ ] Graphes répartition (asset_class, devise)

Phase 6 — Advisor 1 : profil & objectifs :
- [x] Migration _migration_006 (owner_profiles, owner_objectives, macro_snapshots, allocation_targets, rebalance_proposals, llm_usage)
- [x] services/advisor/allocation.py : matrice 5 horizons × 5 niveaux de risque
- [x] Ajustements contextuels (LBO, TNS, horizon court, RP)
- [x] routes/advisor.py : CRUD profil + objectifs + GET allocation
- [x] Onglet « Conseil » dans index.html + static/modules/tabs/advisor.js
- [x] Vue comparative cible vs actuelle (graphe barres Chart.js + tableau écarts €/%)
- [x] Bannière disclaimer persistante en haut de l'onglet
- [x] Tests : 18 nouveaux (moteur + CRUD + allocation end-to-end), 188 au total

Phase 7 — Advisor 2 : macro LLM + arbitrages :
- [ ] requirements : anthropic
- [ ] services/advisor/macro.py (Claude API + prompt caching)
- [ ] Bouton « Actualiser la vue macro »
- [ ] services/advisor/rebalance.py (bucket + security + fiscal)
- [ ] Génération narrative LLM par proposition
- [ ] UI propositions (list, filtres, Appliquer/Écarter)
- [ ] Logging llm_usage + vue consommation dans Outils
- [ ] Garde-fou ADVISOR_BUDGET_USD

Déploiement prod dclab (après validation locale complète) :
- [ ] Backup DB prod
- [ ] Variables d'env (ANTHROPIC_API_KEY, SCHEDULER_ENABLED=true)
- [ ] Vérif migrations au démarrage
- [ ] Tests post-déploiement (refresh cours, positions existantes)
