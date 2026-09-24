import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Chaque ecran Svelte est une entree ; le bundle va dans ../frontend_dist,
// servi par Flask sous /dist/ (pas dans static/ : en prod, static/ est monte
// depuis le depot par-dessus l'image, et masquerait les fichiers compiles).
export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: '../frontend_dist',
    emptyOutDir: true,
    target: 'es2022',
    lib: {
      entry: { credits: 'src/credits/main.ts', positions: 'src/positions/main.svelte.ts',
               synthese: 'src/synthese/main.svelte.ts' },
      formats: ['es'],
      fileName: (_format, nom) => `${nom}.js`,
    },
    rollupOptions: {
      // Les modules existants (api, utils, etat) se chargent tels quels par
      // leur URL : l'ecran partage leurs instances avec le reste de l'app.
      external: [/^\/static\//],
    },
  },
});
