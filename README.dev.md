# Développer Financy

Les règles permanentes du projet (données financières, interface, code,
sécurité) sont dans [`CLAUDE.md`](CLAUDE.md) ; l'état d'avancement, dans
[`TODO.md`](TODO.md). Ce guide ne couvre que la mise en route et le travail au
quotidien.

## Mise en route

```bash
python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env            # DB_PATH=financy_dev.db, FINANCY_PASSWORD=...
./venv/bin/python app.py        # http://127.0.0.1:5017
```

Passer par `python -m pip` : le `pip` du venv peut pointer vers un interpréteur
disparu après une mise à jour de Python.

Les écrans réécrits en Svelte (Crédits, Positions, Synthèse, Flux) se compilent à
part, avec Node :

```bash
cd frontend
npm install
npm run build        # une fois ; `npm run dev` recompile a chaque modification
npm run check        # types (svelte-check)
```

Le bundle va dans `frontend_dist/` (ignoré par git), servi par Flask sous
`/dist/`. En prod, l'image le compile elle-même (étape `node` du Dockerfile).

Pour travailler sans données réelles, activer le **mode démo** dans les
réglages : base fictive `demo.db`, cours et modèle de langage simulés, aucun
appel réseau. Régénérer la base de démo : `./venv/bin/python generate_demo.py`.

## Tests

```bash
./venv/bin/python -m pytest -q
```

Chaque fichier de test travaille sur sa propre base temporaire. Les jeux
d'essai sont **fictifs** (le dépôt est public) : noms « Paul », « Claire »,
« SCI Exemple », montants ronds ou inventés, jamais un chiffre réel.

Pour vérifier une page dans un navigateur, lancer un serveur jetable sur une
**copie** de base, lié à la boucle locale :

```bash
cp demo.db /tmp/essai.db
DB_PATH=/tmp/essai.db PRICE_PROVIDER=mock FINANCY_PASSWORD=dev \
  HOST=127.0.0.1 PORT=5002 ./venv/bin/python app.py
```

Certaines routes GET écrivent (rafraîchissement de l'historique des cours) :
ne jamais pointer un serveur d'essai sur une base qu'on veut garder intacte.
Les gabarits ne se rechargent pas à chaud : redémarrer après un changement de
`templates/`.

## Organisation

| Dossier | Contenu |
|---------|---------|
| `models.py` | Schéma, migrations (`MIGRATIONS`, une fonction par version, jamais modifiée une fois exécutée), valorisation des positions |
| `routes/` | Un blueprint par domaine ; `@login_required` partout, `@csrf_protect` sur toute écriture |
| `services/` | Logique métier : prêts, trésorerie d'entité, contribution, fiscalité, contrats, conseil (`advisor/`), lecteurs de documents (`parsers/`) |
| `static/modules/` | Front en modules ES, un module par onglet dans `tabs/` |
| `frontend/` | Écrans en Svelte 5 + TypeScript (Vite) ; ils réutilisent les modules de `static/modules/` par leur URL |
| `templates/index.html` | L'application (page unique) ; `login.html` |
| `tests/` | Pytest, un fichier par domaine |

## Livrer

Une phase fonctionnelle = un commit, message en français. Rien n'est poussé ni
déployé sans feu vert. Le déploiement suit la procédure de `CLAUDE.md` ; les
détails propres à l'hébergement (hôte, chemins, accès) sont dans
`CLAUDE.local.md`, non versionné.
