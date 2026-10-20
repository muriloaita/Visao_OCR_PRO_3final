import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Em desenvolvimento: `python ocr_server.py` (porta 5002) + `npm run dev` (porta 3000).
// O Vite repassa /api para o servidor Python. Em produção o próprio Flask
// serve a pasta dist/ gerada por `npm run build`.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://127.0.0.1:5002',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 2000,
  },
});
