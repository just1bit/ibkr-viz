import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Flask backend serves the JSON API on :5123. During dev we proxy /api there;
// the production build is emitted to ./dist and served directly by Flask.
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
