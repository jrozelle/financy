# Patrimoine Familial

Application web de suivi patrimonial familial — Flask + SQLite + vanilla JS.

## Fonctionnalités

- **Synthèse** : KPI (actif brut, dette, net, mobilisable), graphiques par catégorie / enveloppe, historique, allocation cible vs réelle, performance, alertes configurables
- **Positions** : vue tableau (triable, filtrable) et vue arborescente (propriétaire → établissement → enveloppe → catégorie) avec édition inline et boutons contextuels
- **Flux** : versements, retraits, dividendes — filtrés et totalisés par type et personne
- **Entités** : SCI, indivisions — versionnées avec historique de valorisation
- **Référentiel** : propriétaires, catégories, enveloppes, mobilisabilité — tout configurable

## Installation

```bash
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Ouvrir [http://localhost:5000](http://localhost:5000)

## Docker

```bash
docker build -t patrimoine .
docker run -p 5000:5000 -v $(pwd)/data:/app/data patrimoine
```

> La base de données `patrimoine.db` est créée automatiquement au premier lancement. Elle n'est pas versionnée (`.gitignore`).

## Import

Un fichier Excel modèle (`Patrimoine_Familial_blank.xlsx`) est fourni. Il n'est pas inclus dans le repo — importez vos données via **Import / Export → Import XLSX** ou **Import JSON**.

## Stack

- Backend : Python 3.12 / Flask 3 / SQLite
- Frontend : HTML + CSS + JavaScript (vanilla, pas de framework)
- Graphiques : Chart.js 4
