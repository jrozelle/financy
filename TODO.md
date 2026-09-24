# Financy — état d'avancement

Seule référence de ce qui reste à faire. Le détail de ce qui est fait vit dans
l'historique git (`git log`), un commit par phase.

## Ouvert

- [ ] Libellés du « patrimoine financier » : cinq valeurs selon l'onglet, chacune
      juste dans son périmètre, que le libellé doit dire
- [ ] Constats : versements PER face au plafond de déduction (revenus à saisir)
- [ ] Limitation des tentatives de connexion derrière le reverse proxy (lire
      l'adresse transmise par le proxy, et seulement la sienne)
- [ ] Suppression des opérations bancaires d'une entité (aucun écran aujourd'hui,
      ce qui empêche de supprimer une entité qui a des relevés)
- [ ] Soldes d'ouverture des comptes d'entité déjà importés : réimporter le premier
      relevé de chaque compte
- [ ] CSS : échelle de tailles de police et d'espacements
- [ ] Téléphone : synthèse longue (onze écrans) — cartes secondaires repliées
      par défaut ? La personnalisation est désormais dans le menu « ··· »

- [ ] Svelte : porter les écrans un par un, un déploiement par écran, chacun
      comparé à l'ancien sur une copie de la base ; d'abord les plus exposés
      aux bugs d'interface — Positions (arbre et tableau), Synthèse et ses
      widgets, Flux et l'import — puis les écrans simples. Crédits et Positions
      sont faits

## Fait, en bref

- **Socle** (avril 2026) : positions datées par arrêté, entités (SCI,
  indivisions) à parts de propriété et de dette distinctes, vue en arbre,
  import / export JSON et XLSX, mode démo, authentification et CSRF.
- **Actifs** : lignes de titres, import PDF et copier-coller, cours et devises
  (conversion par `fx_rates`), rafraîchissement planifié, fiche d'un titre.
- **Mesure** : TRI et TWR par compte et par enveloppe face à un indice,
  décomposition de la hausse (épargne nouvelle, capital remboursé, comptes
  ajoutés, performance), impôt latent, projection du patrimoine.
- **Crédits** : échéanciers importés ou saisis, différés, in fine, IRA, vue
  par titulaire.
- **Entités** : trésorerie et levier lus sur les relevés, SCPI au prix de
  retrait, IS d'une SCI à l'IS.
- **Conseil** : constats vérifiables (plafonds, espèces dormantes, ancienneté
  des contrats, garder ou rembourser), propositions sur la part libre du
  financier, vue macro facultative.
- **Interface** : synthèse personnalisable (widgets), barre du bas du téléphone
  au choix, mode discrétion, thème sombre, application installable, tris et
  accessibilité clavier.
- **Hygiène** (septembre 2026) : revue complète (calculs, cohérence, interface,
  CSS), dépôt public purgé des données réelles, clé d'API hors de la base,
  rotation des sauvegardes.
