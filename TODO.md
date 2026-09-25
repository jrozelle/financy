# Financy — état d'avancement

Seule référence de ce qui reste à faire. Le détail de ce qui est fait vit dans
l'historique git (`git log`), un commit par phase.

## Ouvert

Rien en cours.

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
- **Entités** : trésorerie et levier lus sur les relevés (un relevé se retire,
  avec le solde d'ouverture qui en venait), SCPI au prix de retrait, IS d'une
  SCI à l'IS.
- **Conseil** : constats vérifiables (plafonds, espèces dormantes, ancienneté
  des contrats, garder ou rembourser), propositions sur la part libre du
  financier, vue macro facultative.
- **Interface** : synthèse personnalisable (widgets), raccourcie au téléphone
  (sept écrans au lieu de onze : comptes, évolution et projection se déplient), barre du bas du téléphone
  au choix, mode discrétion, thème sombre, application installable, tris et
  accessibilité clavier.
- **Svelte** (septembre 2026) : tous les onglets et trois écrans des Réglages
  (Référentiel, Outils, Import / Export) portés un par un en Svelte 5 + TypeScript, chacun comparé à l'ancien sur une
  copie de la base, au bureau et sur téléphone, puis déployé ; restent en
  JavaScript les Préférences, les fenêtres (fiche d'une position, d'un flux,
  d'un titre) et les modules partagés.
- **CSS** (septembre 2026) : échelles de tailles de texte (`--fs-*`, onze
  paliers au lieu de 47 valeurs) et d'espacements (`--esp-*`, treize paliers).
- **Hygiène** (septembre 2026) : revue complète (calculs, cohérence, interface,
  CSS), dépôt public purgé des données réelles, clé d'API hors de la base,
  rotation des sauvegardes.
