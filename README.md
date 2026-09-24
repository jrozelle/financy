# Financy

Suivi du patrimoine familial, auto-hébergé : ce que vous possédez, ce que vous
devez, d'où vient ce qui a bougé, et ce que deviendra le tout — à partir des
documents que vos banques vous envoient déjà.

Financy ne se connecte à aucune banque. Il lit les documents (relevés, avis
d'opéré, tableaux d'amortissement), les vérifie, et range chaque mouvement.
Les données restent chez vous, dans un fichier SQLite.

## Ce que fait l'application

| Page | Ce qu'on y lit |
|------|----------------|
| **Synthèse** | Des widgets que l'on déplace, redimensionne ou masque, disposition mémorisée d'un appareil à l'autre : patrimoine net, brut, dettes et mobilisable ; ce qui a bougé depuis l'arrêté précédent ; d'où vient la hausse (épargne nouvelle, capital remboursé, performance des marchés) ; évolution par catégorie ; projection à 5–20 ans ; impôt latent « si vous vendiez tout » |
| **Positions** | Chaque compte dans une arborescence triable : par nature, par titulaire, par établissement ou à plat, avec recherche, filtre par établissement et par enveloppe, part du brut et du net (le levier se lit à la barre), lignes de titres dépliables ; mise à jour d'un arrêté en une passe |
| **Actifs** | Les titres détenus, leurs cours, leur devise, et tout arbitrage de valorisation signalé |
| **Entités** | SCI, holdings, indivisions : valeur, dette, parts de chaque titulaire ; trésorerie et levier d'une société lus sur ses relevés bancaires ; parts de SCPI au prix de retrait ; impôt sur les sociétés estimé |
| **Crédits** | Tableaux d'amortissement importés ou saisis, différé total ou partiel, prêts in fine, indemnités de remboursement anticipé, échéances à venir |
| **Performance** | Rendement de votre argent (TRI) et rendement comparable à un indice (TWR), par compte ou par enveloppe, face à un indice de référence |
| **Flux** | Versements, retraits, dividendes et frais ; flux provisoires rapprochés du document qui les atteste |
| **Conseil** | Constats tirés des chiffres (plafonds, espèces qui dorment, ancienneté des contrats, garder ou rembourser un crédit) et propositions d'arbitrage sur la part libre du patrimoine financier |

Et aussi : un mode discrétion qui ne laisse lisibles que les trois derniers
chiffres de chaque montant (pour montrer l'écran sans montrer le patrimoine),
un thème sombre, un mode démo sur des données fictives, et l'installation sur
l'écran d'accueil d'un téléphone.

## Principes

- **Un document se vérifie avant d'être cru.** Un relevé doit redonner son solde
  final, un tableau d'amortissement tomber à zéro. Sinon il est refusé, plutôt
  que de fausser les chiffres en silence.
- **Rien n'est écarté sans le dire.** Un compte hors d'un calcul figure dans un
  décompte, avec sa raison.
- **Une valorisation au plus près de la sortie.** Une part de SCPI vaut son prix
  de retrait, pas son prix d'achat ; un contrat d'assurance-vie se taxe selon son
  ancienneté réelle.
- **Pas de conseil générique.** Un constat s'appuie sur vos chiffres ; il ne
  cite aucun taux de marché, seulement ceux de vos contrats.

## Démarrage

### Docker Compose (recommandé)

```bash
cp .env.example .env            # adapter les valeurs
docker compose up -d
```

L'application écoute sur [http://localhost:5017](http://localhost:5017). La base
est persistée dans `./data/`. Après une mise à jour : `docker compose up -d --build`.

### En local

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python app.py
```

Pour découvrir l'application sans rien saisir, activez le **mode démo** depuis
les réglages : il bascule sur une base fictive et coupe tout appel réseau.

## Configuration

Dans `.env` (voir `.env.example`) :

| Variable | Défaut | Rôle |
|----------|--------|------|
| `FINANCY_PASSWORD` | *(vide : pas d'authentification)* | Mot de passe d'accès |
| `SECRET_KEY` | *(générée au démarrage)* | Clé des sessions (32 caractères minimum en production) |
| `DB_PATH` | `patrimoine.db` | Base SQLite |
| `HOST` / `PORT` | `0.0.0.0` / `5017` | Adresse d'écoute |
| `SESSION_TIMEOUT_MINUTES` | `60` | Inactivité avant déconnexion |
| `FINANCY_PROXIES_DE_CONFIANCE` | *(vide)* | Derrière un reverse proxy : ses adresses ou son réseau (`10.0.0.0/24`, séparés par des virgules). L'adresse du client est alors lue dans `X-Forwarded-For`, pour que la limite des tentatives de connexion compte par client et non pour le proxy entier |
| `FLASK_ENV` | `development` | `production` coupe le débogage et exige des cookies sécurisés |
| `PRICE_PROVIDER` | `yahoo` | Source des cours ; `mock` n'appelle aucun réseau |
| `SCHEDULER_ENABLED` | `false` | Rafraîchissement quotidien des cours (`SCHEDULER_HOUR`, `SCHEDULER_MINUTE`, `SCHEDULER_TZ`) |
| `ANTHROPIC_API_KEY` | *(vide)* | Synthèse macroéconomique rédigée par un modèle, facultative (`ADVISOR_MODEL`, `ADVISOR_LLM_PROVIDER`, `ADVISOR_BUDGET_USD`). Saisie dans les réglages, la clé va dans `secrets.json`, à côté de la base : ignoré par git, absent des sauvegardes et des exports, lisible du seul propriétaire. La variable d'environnement l'emporte toujours. |

## Importer ses données

- **Documents** : avis d'opéré, relevés de comptes, tableaux d'amortissement et
  avis de réalisation de prêt (PDF), copier-coller d'un tableau de positions
  depuis le site de la banque.
- **Tableur** : le modèle vierge `Patrimoine_Familial_blank.xlsx` (positions,
  flux, entités), à remplir puis importer depuis **Import / Export**.
- **Sauvegarde** : export et import JSON complets. Chaque import est précédé
  d'une copie de la base, et les copies suivent une rotation (tout sur 30 jours,
  puis une par mois).

## Sécurité

- Mot de passe comparé en temps constant, tentatives de connexion limitées par client, y compris derrière un reverse proxy
- Sessions à durée limitée, régénérées à la connexion
- Protection CSRF sur toute écriture, entrées validées côté serveur
- En-têtes de sécurité (CSP, X-Frame-Options, Referrer-Policy), cookies HttpOnly et SameSite
- Aucune clé en dur : tout passe par l'environnement

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Stack

Python 3.12 et Flask 3, SQLite, JavaScript sans framework (modules ES),
graphiques en SVG et Chart.js, Docker.
