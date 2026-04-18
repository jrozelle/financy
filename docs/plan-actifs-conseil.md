# Plan — Actifs & conseil patrimonial

Branche : `claude/asset-import-tracking-8psft`

## Objectif global
Ajouter trois fonctionnalités à Financy :
1. Injecter une liste d'actifs sur une enveloppe (PDF export PEA/AV ou saisie manuelle ISIN/qté/PRU/valo).
2. Suivi automatique des cours des actifs.
3. Fonction de conseil patrimonial : profil par personne, objectifs, allocation cible, arbitrages fiscaux.

## Contexte technique
- Stack : Python 3.12 / Flask 3 / SQLite, frontend vanilla JS + Chart.js, templates serveur.
- Modèles clés dans `models.py` (table `positions` lignes 221-235, migrations ligne 313, `compute_position` ligne 351).
- Routes : blueprints dans `routes/`. Modules JS : `static/modules/`. SPA : `templates/index.html`.
- Auth + CSRF déjà en place dans `app.py` — à réutiliser sur TOUS les nouveaux endpoints.
- Mode démo (`models.py:14`) : pas d'appel réseau — mocker providers et LLM.
- Aucun existant : PDF parsing, API marché, scheduler, LLM.
- Positions actuelles « plates » (value/debt) : on les enrichit d'un niveau holdings sans casser l'existant.

## Environnement dev local (à mettre en place AVANT la phase 1)
- venv Python 3.12 : `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- `requirements-dev.txt` pour les nouvelles deps (yfinance, pdfplumber, APScheduler, anthropic)
- Fichier `.env.local` (gitignoré) :
  ```
  DB_PATH=./financy_dev.db
  FLASK_ENV=development
  SCHEDULER_ENABLED=false
  ANTHROPIC_API_KEY=...  # optionnel, advisor désactivé sans
  ```
- Démarrage : `flask run --port 5001` (ou `python app.py`)
- DB de dev isolée (`financy_dev.db`), jamais commitée
- Script `scripts/seed_dev.py` : 1 owner, 1 position PEA avec 3 ISIN réels (FR0010315770 CW8, IE00B4L5Y983 IWDA, FR0011550185 PAASI), 1 profil advisor test
- Checklist de tests locaux par phase : dans `README.dev.md`

## Déploiement prod dclab (après validation locale complète)
- `docker-compose.yml` existant adapté : variables d'env (ANTHROPIC_API_KEY, SCHEDULER_ENABLED=true, DB_PATH sur volume persistant)
- **Backup obligatoire de la DB prod** avant déploiement (migrations idempotentes mais backup obligatoire)
- Migrations 005 et 006 appliquées automatiquement au démarrage
- Post-déploiement : vérifier logs de migration, tester refresh cours, vérifier que les positions existantes sont intactes

## Arbitrages tranchés (ne pas re-questionner)
- **Mini-graphe** : popover au CLIC sur ISIN, panneau latéral graphe 1J/7J/30J + dernier cours, variation %, volume, PRU vs cours, P&L latent
- **Fonds euros** : pseudo-ISIN `FONDS_EUROS_<slug>`, `asset_class='fonds_euros'`, `is_priceable=false`, valorisation manuelle
- **Snapshots** : value agrégée + historique holdings (table `holdings_snapshots`)
- **Ré-import PDF** : full replace avec confirmation
- **Devises** : devise native stockée sur securities, conversion EUR à l'affichage
- **Moteur conseil** : hybride — matrice déterministe pour allocation cible, Claude API pour narration + macro + explication des arbitrages
- **Granularité conseil** : allégements par poche/montants + titres nominatifs + optimisation fiscale (PEA/CTO/AV)
- **Contexte macro** : synthèse LLM à la demande (bouton), éditable par l'utilisateur
- **Positionnement** : outil perso + bannière disclaimer permanente
  > « Outil personnel à vocation pédagogique, ne constitue pas un conseil en investissement réglementé. »

## Schéma cible

### Migration `_migration_005` (holdings)
```sql
securities(
  isin PK, name, ticker,
  currency DEFAULT 'EUR',
  asset_class,             -- 'action', 'etf', 'opcvm', 'obligation', 'fonds_euros', 'autre'
  is_priceable BOOLEAN DEFAULT 1,
  last_price, last_price_date,
  data_source              -- 'yahoo', 'manual', 'boursorama'
)

holdings(
  id PK,
  position_id FK positions ON DELETE CASCADE,
  isin FK securities,
  quantity,
  cost_basis,              -- FIGÉ à l'import, JAMAIS recalculé
  market_value,            -- remplacé par qty*last_price si is_priceable
  as_of_date,
  created_at
)

price_history(isin, date, price, PK(isin, date))

holdings_snapshots(
  id PK, snapshot_date, position_id, isin,
  quantity, cost_basis, price, market_value
)
```

### Migration `_migration_006` (advisor)
```sql
owner_profiles(
  owner PK,
  horizon_years, risk_tolerance INT 1-5,
  employment_type,         -- 'salarié', 'TNS', 'fonction_publique', 'retraité', 'autre'
  has_lbo BOOLEAN, children_count INT,
  main_residence_owned BOOLEAN, pension_age,
  notes, updated_at
)

owner_objectives(
  id PK, owner FK,
  label, target_amount, horizon_years,
  priority INT, created_at
)

macro_snapshots(
  id PK, date,
  regime_rates, inflation_view, equities_bias,
  raw_summary TEXT,
  source,                  -- 'llm' | 'manual'
  created_at
)

allocation_targets(
  id PK, owner, snapshot_date,
  bucket_type,             -- 'liquidity' | 'category'
  bucket_name, target_pct
)

rebalance_proposals(
  id PK, owner, snapshot_date,
  kind,                    -- 'bucket' | 'security' | 'fiscal'
  label, from_ref, to_ref, amount,
  rationale,
  status                   -- 'pending' | 'applied' | 'dismissed'
)

llm_usage(
  id PK, date, endpoint, model,
  input_tokens, cached_input_tokens, output_tokens,
  cost_usd, latency_ms
)
```

## Livraison par phases
1 commit par phase, test local entre chaque, feedback utilisateur obligatoire avant la suivante.

### Phase 1 — Schéma holdings + CRUD manuel
- Migration `_migration_005`
- `routes/holdings.py` : GET/PUT/DELETE holdings (auth + CSRF)
- `compute_position` : si holdings + `is_priceable` → `value = Σ(qty × last_price)`. Sinon `market_value` saisi. Fonds euros = manuel. Sans holdings = comportement inchangé.
- `static/modules/holdings.js` + modale « Gérer les lignes » depuis l'onglet Positions
- Validation ISIN (regex `[A-Z]{2}[A-Z0-9]{9}\d` + checksum Luhn mod 10)
- Snapshots étendus pour peupler `holdings_snapshots`
- Export XLSX : nouvel onglet « Holdings » + import correspondant

### Phase 2 — Provider de cours + refresh manuel + popover
- `requirements.txt` : yfinance
- `services/prices.py` : classe abstraite `PriceProvider`, `YahooProvider`, mock provider en démo
- Batching 10 ISIN + délai, try/except robuste, jamais de crash global
- `POST /api/prices/refresh` (auth + CSRF) : update `last_price` + insert `price_history`
- Bouton « Rafraîchir les cours » dans l'onglet Outils
- Badge fraîcheur : vert <1j, orange <7j, rouge sinon
- Résolution ISIN → ticker via Yahoo search, cache `securities.ticker`, éditable
- Popover au clic sur ISIN : Chart.js 1J/7J/30J depuis `price_history`, dernier cours, variation %, volume si dispo, PRU, P&L latent € et %

### Phase 3 — Scheduler
- APScheduler
- Job quotidien `refresh_prices()` si `SCHEDULER_ENABLED=true`
- Lock anti-double-exécution, logs structurés

### Phase 4 — Import PDF
- pdfplumber
- Upload : max 5 Mo, MIME `application/pdf`, stockage temporaire purgé, CSRF
- `POST /api/envelope/<position_id>/import-pdf` :
  - preview : extraction + parse heuristique → JSON lignes détectées
  - validate : full replace après confirmation
- Détection format par empreinte textuelle (PEA Boursorama, AV Linxea). Parser générique regex ISIN en fallback
- Fallback modale manuelle pré-remplie si parsing partiel

### Phase 5 — Onglet Actifs (optionnel)
- Vue consolidée holdings, tri par ISIN / poids / perf / fraîcheur
- Graphes Chart.js répartition (par `asset_class`, par devise)

### Phase 6 — Profil & objectifs (advisor partie 1)
- Migration `_migration_006`
- `routes/advisor.py` : CRUD profil + objectifs par owner (auth + CSRF)
- Onglet « Conseil » dans `templates/index.html`, module `static/modules/advisor.js`
- Formulaire profil : horizon, risk_tolerance 1-5, employment_type, has_lbo, children_count, main_residence_owned, pension_age, notes
- Formulaire objectifs multi-lignes : label, montant cible, horizon, priorité
- Moteur déterministe `services/advisor/allocation.py` :
  - matrice horizon × risque → allocation cible par poche liquidité (J0-J1 à Bloqué) et par catégorie
  - matrice publique et éditable via config (referential), pas en dur
  - ajustements contextuels : has_lbo → +liquidité / -action ; enfants → objectif études ; TNS → renforcer épargne retraite
- Vue comparative : allocation cible vs actuelle, graphe barres Chart.js, écarts en € et %
- Bannière disclaimer persistante sur l'onglet Conseil

### Phase 7 — Macro LLM + arbitrages (advisor partie 2)
- `requirements.txt` : anthropic
- `services/advisor/macro.py` : appel Claude API (modèle `claude-sonnet-4-6` par défaut, configurable via `ADVISOR_MODEL`)
- **Prompt caching Anthropic obligatoire** sur le bloc système (cadre d'analyse stable) et sur le contexte profil+positions (réutilisé entre propositions). `cache_control: {"type": "ephemeral"}` sur les blocs stables.
- Bouton « Actualiser la vue macro » → crée `macro_snapshot` (source='llm'), éditable ensuite (source devient 'manual' après édition)
- En mode démo ou sans `ANTHROPIC_API_KEY` : bouton désactivé + message explicite
- `services/advisor/rebalance.py` : 3 niveaux de propositions dans `rebalance_proposals` :
  - `bucket` : « Alléger poche Actions de 8 000 € vers Obligations »
  - `security` : « Vendre 20 parts de CW8, acheter 500 € de IEGA »
  - `fiscal` : plafond PEA non atteint, moins-values CTO purgeables, arbitrage CTO→PEA éligible, versements AV >8 ans, PER vs rémunération TNS
- Génération narrative : Claude API reçoit (profil + positions + allocation_cible + macro) et produit une explication par proposition (`rationale`). Contexte profil/positions mis en cache.
- UI onglet Conseil : liste propositions, status pending/applied/dismissed, filtres, boutons Appliquer (note l'action, ne modifie pas auto) / Écarter
- Logging tous les appels LLM dans `llm_usage` (tokens input/cached/output, coût USD calculé, latence). Vue simple dans l'onglet Outils : « Consommation API ce mois : X appels, Y $ »

## Coût API estimé (phase 7)
Tarifs `claude-sonnet-4-6` : input $3/MTok, output $15/MTok, cache read $0.30/MTok, cache write $3.75/MTok.

Hypothèse d'usage personnel (1-2 sessions/semaine) :
- Macro refresh : ~8 appels/mois, 3k input + 1k output → ~$0.20/mois
- Narration arbitrages : ~80 propositions/mois, 2k cached + 500 output → ~$0.70/mois (grâce au cache)
- Cache writes initiaux : ~$0.05/mois
- **Total attendu : < $1/mois** pour usage perso, < $10/mois même si 10× plus intensif

Garde-fou : alerte console si consommation mensuelle > 5 $ (configurable via `ADVISOR_BUDGET_USD`).

## Règles strictes
- Branche `claude/asset-import-tracking-8psft`. 1 commit par phase. Message clair.
- Ne push jamais sans feu vert explicite. Ne crée jamais de PR sans demande.
- Pas d'emojis dans le code.
- Dark mode cohérent partout.
- Ne modifie pas les tables existantes sans demander.
- Toutes migrations idempotentes, zéro destructif.
- Endpoints : auth + CSRF systématique. Mode démo : aucun réseau (Yahoo + Anthropic mockés).
- Pas de clé API en dur ; variables d'environnement uniquement.
- Disclaimer permanent dans l'onglet Conseil, et sur toute page affichant une proposition nominative ou fiscale.
- Chaque appel LLM tracé dans `llm_usage` (coût calculé).
- Après chaque phase : rappeler la checklist de test local puis attendre le feedback.
