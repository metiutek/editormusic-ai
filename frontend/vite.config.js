import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In sviluppo (`npm run dev`) le chiamate vanno al backend su 8780;
// in produzione il backend serve direttamente la cartella dist.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    port: 5175,
    proxy: {
      '/api': 'http://127.0.0.1:8780',
      '/ws': { target: 'ws://127.0.0.1:8780', ws: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 900 },
})
