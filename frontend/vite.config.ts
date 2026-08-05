import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Flask serves /api and /auth on :5123. Vite proxies both during development;
// Flask serves the production bundle emitted to ./dist.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:5123',
      '/auth': 'http://localhost:5123',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
