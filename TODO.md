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
- [ ] 🔵 Projection / simulation ("500 €/mois sur PEA pendant 10 ans")
- [ ] 🔵 Snapshot automatique programmé (dupliquer le dernier snapshot chaque mois sans action manuelle)
- [ ] 🔵 Multi-devises (positions crypto / étrangères avec conversion manuelle ou automatique)


--- UX contextuelle ---

- [x] 🟠 Bouton "Ajouter une position" sur chaque ligne d'entité → modal pré-rempli (entité, établissement) + bascule sur l'onglet Positions
- [x] 🟠 Bouton "+" contextuel dans l'arborescence Positions : au niveau owner → pré-remplit propriétaire ; au niveau établissement → pré-remplit owner + établissement + entité si applicable ; au niveau enveloppe → pré-remplit owner + établissement + enveloppe
- [x] 🟡 Toast de confirmation après sauvegarde position / flux / entité
- [ ] 🟡 Vérification orphelins à la suppression d'enveloppe ou de catégorie dans le Référentiel
- [ ] 🟡 Performance filtrée par personne (cohérence avec vue personne dans Synthèse)


--- Backlog / docs ---

- [ ] faire la doc du projet (README)
- [ ] import : tester avec le vrai fichier rempli et valider les chiffres
- [ ] Dockerfile à tester
