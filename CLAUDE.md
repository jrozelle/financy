# Consignes permanentes Financy

## Workflow
- Branche de dev active : `claude/asset-import-tracking-8psft`
- 1 commit par phase fonctionnelle, message clair en français
- Ne push jamais sans feu vert explicite de l'utilisateur
- Ne crée jamais de PR sans demande explicite
- Après chaque phase : rappeler la checklist de test local et attendre le feedback

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
