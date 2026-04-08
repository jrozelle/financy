# Financy

Application web de suivi patrimonial familial — visualisez, analysez et pilotez votre patrimoine en famille.

## Fonctionnalités

| Onglet | Description |
|--------|-------------|
| **Synthèse** | KPI (actif brut, dette, net, mobilisable), graphiques par catégorie / enveloppe, historique du patrimoine, allocation cible vs réelle, performance, alertes configurables |
| **Positions** | Vue tableau (tri, filtre, recherche) et vue arborescente (propriétaire → établissement → enveloppe → catégorie) avec édition inline, snapshots datés et duplication |
| **Flux** | Versements, retraits, dividendes — filtrés et totalisés par type et par personne |
| **Entités** | SCI, indivisions — versionnées avec historique de valorisation et parts détenues |
| **Référentiel** | Propriétaires, catégories, enveloppes, mobilisabilité — tout configurable |
| **Import / Export** | Import XLSX ou JSON, export JSON, sauvegarde et restauration complète |
| **Outils** | Simulation d'épargne, auto-snapshot |

## Démarrage rapide

### Installation locale

```bash
python3 -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # optionnel — adapter les valeurs
python3 app.py
```

Ouvrir [http://localhost:5017](http://localhost:5017).

### Docker Compose (recommandé)

```bash
cp .env.example .env            # adapter les valeurs
docker compose up -d
```

L'application est accessible sur [http://localhost:5017](http://localhost:5017).

Pour reconstruire après une mise à jour :

```bash
docker compose up -d --build
```

La base de données est persistée dans `./data/` grâce au volume monté.

## Configuration

Toutes les variables se définissent dans un fichier `.env` (voir `.env.example`) :

| Variable | Défaut | Description |
|----------|--------|-------------|
| `FINANCY_PASSWORD` | *(vide — pas d'auth)* | Mot de passe d'accès à l'application |
| `SECRET_KEY` | *(générée au démarrage)* | Clé secrète Flask pour les sessions (min. 32 caractères en production) |
| `DB_PATH` | `patrimoine.db` | Chemin vers la base SQLite |
| `PORT` | `5017` | Port d'écoute |
| `SESSION_TIMEOUT_MINUTES` | `60` | Durée d'inactivité avant déconnexion |
| `FLASK_ENV` | `development` | `production` désactive le debug et active les cookies Secure |

## Import de données

Un fichier Excel modèle vierge est inclus dans le dépôt : **`Patrimoine_Familial_blank.xlsx`**.

Il contient 7 onglets pré-formatés :

| Onglet | Contenu |
|--------|---------|
| README | Mode d'emploi |
| Listes | Valeurs de référence (catégories, enveloppes…) |
| Positions | Lignes de patrimoine |
| Flux | Versements, retraits, dividendes |
| Entites | SCI, indivisions |
| Synthese | Snapshots patrimoniaux |
| TCD | Tableau croisé dynamique |

1. Téléchargez `Patrimoine_Familial_blank.xlsx`
2. Remplissez les onglets avec vos données
3. Dans l'application → **Import / Export** → **Import XLSX**

L'import JSON est également disponible pour les sauvegardes existantes.

## Sécurité

- Authentification par mot de passe avec comparaison timing-safe
- Rate limiting sur la page de login (10 tentatives / 5 min)
- Sessions avec timeout configurable et régénération après login
- En-têtes de sécurité (CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy)
- Cookies HttpOnly / SameSite=Lax (+ Secure en production)
- Validation et assainissement de toutes les entrées

## Tests

```bash
pip install pytest
python3 -m pytest tests/ -v
```

## Stack technique

- **Backend** : Python 3.12 / Flask 3 / SQLite
- **Frontend** : HTML + CSS + JavaScript vanilla (aucun framework)
- **Graphiques** : Chart.js 4
- **Conteneurisation** : Docker + Docker Compose
