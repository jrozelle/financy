# Dev local — Financy

Environnement de developpement local pour la feature **actifs & conseil patrimonial**.
Spec complete : [`docs/plan-actifs-conseil.md`](docs/plan-actifs-conseil.md).

## Setup initial

```bash
# Cloner puis se placer sur la branche
git checkout claude/asset-import-tracking-8psft

# Creer le venv
python -m venv .venv
source .venv/bin/activate

# Installer les dependances
pip install -r requirements.txt

# Copier la config
cp .env.example .env
# Editer .env :
#   DB_PATH=financy_dev.db
#   FLASK_ENV=development
#   FINANCY_PASSWORD=dev  (optionnel)
```

## Demarrage

```bash
source .venv/bin/activate
python app.py
# ou : flask run --port 5017
```

Ouvrir http://localhost:5017 (ou le port defini dans `.env`).

## Seed de test

Apres chaque migration, reseeder la DB de dev :

```bash
DB_PATH=financy_dev.db python scripts/seed_dev.py
```

Cree une position PEA de test avec 3 ETF reels (CW8, IWDA, PAASI).
Le script est idempotent : il purge les donnees precedentes (marqueur `[seed_dev]`
dans `notes`) avant reinsertion.

## Checklist de tests par phase

A executer avant chaque commit de phase.

### Phase 1 — Holdings + CRUD manuel

- [ ] Migration 005 appliquee au demarrage sans erreur (voir logs)
- [ ] `scripts/seed_dev.py` insere 1 position + 3 holdings
- [ ] Onglet Positions : la position PEA s'affiche avec sa valeur recalculee (somme des `market_value`)
- [ ] Ouvrir la modale "Gerer les lignes" sur la position : les 3 ISIN s'affichent
- [ ] Ajouter une ligne manuellement (ISIN valide : `FR0000131104` BNP Paribas)
- [ ] Ajouter une ligne avec ISIN invalide : erreur affichee
- [ ] Modifier une quantite : la `value` de la position se met a jour
- [ ] Supprimer une ligne : la `value` diminue en consequence
- [ ] Les positions SANS holdings continuent de fonctionner a l'identique (synthese, drilldown)
- [ ] Snapshot du patrimoine : les holdings sont captures dans `holdings_snapshots`
- [ ] Export XLSX : un onglet `Holdings` est present, avec les lignes seedees
- [ ] Re-import du XLSX exporte : round-trip sans perte ni duplication
- [ ] Fonds euros : creer un holding avec ISIN `FONDS_EUROS_LINXEA_SPIRIT_2`, verifier que `is_priceable=false` et que la valo manuelle est conservee

### Phase 2 — Provider cours + popover

- [ ] Bouton "Rafraichir les cours" dans l'onglet Outils fonctionnel
- [ ] Apres refresh : `last_price` peuple pour CW8, IWDA, PAASI
- [ ] Badge fraicheur vert/orange/rouge selon la date
- [ ] Clic sur un ISIN : popover avec graphe 1J/7J/30J + PRU + P&L
- [ ] ISIN sans ticker Yahoo : message clair, saisie manuelle possible
- [ ] Mode demo : bouton refresh utilise le mock, pas d'appel reseau
- [ ] Pas de crash si Yahoo renvoie 429 ou timeout

### Phase 3 — Scheduler

- [ ] Avec `SCHEDULER_ENABLED=true` dans `.env` : job quotidien se lance au boot
- [ ] Logs : nb ISIN rafraichis, nb erreurs, duree
- [ ] Double-demarrage : lock empeche l'execution concurrente

### Phase 4 — Import PDF

- [ ] Upload d'un PDF PEA Boursorama : preview des lignes detectees
- [ ] Validation : full replace avec modale de confirmation
- [ ] Upload d'un PDF illisible : fallback modale manuelle pre-remplie
- [ ] Upload > 5 Mo : erreur
- [ ] Upload non-PDF : erreur MIME

### Phase 6 — Profil & objectifs

- [ ] Onglet "Conseil" visible
- [ ] Saisie profil (horizon, risque, employment_type, etc.) : persiste
- [ ] Saisie objectifs multiples : liste editable
- [ ] Vue "allocation cible vs actuelle" : graphe et ecarts corrects
- [ ] Banniere disclaimer visible en permanence

### Phase 7 — Macro LLM + arbitrages

- [ ] Sans `ANTHROPIC_API_KEY` : bouton macro desactive + message
- [ ] Avec cle : "Actualiser la vue macro" cree un snapshot, editable ensuite
- [ ] Generation des propositions : liste populated (bucket + security + fiscal)
- [ ] Clic sur "Appliquer" : status passe a `applied`
- [ ] Consommation API visible dans l'onglet Outils
- [ ] Mode demo : LLM mocke, aucune requete reseau

## Deploiement prod dclab

A ne faire qu'apres validation locale complete de toutes les phases livrees.

```bash
# Sur la machine dclab
# 1. Backup DB prod OBLIGATOIRE
cp patrimoine.db backups/patrimoine_$(date +%Y%m%d_%H%M%S).db

# 2. Pull + variables d'env
git pull origin main  # ou la branche merge
# Verifier dans docker-compose.yml :
#   ANTHROPIC_API_KEY=...
#   SCHEDULER_ENABLED=true

# 3. Redeployer
docker compose up -d --build

# 4. Verifications post-deploiement
docker compose logs | grep -i migration
# Tester dans le navigateur : refresh cours, positions existantes intactes
```
