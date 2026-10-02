import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// Offline-first: no CDN. Everything is bundled locally.
export default defineConfig({
  plugins: [react()],
  // Relative base so Electron file:// and packaged builds resolve assets.
  base: './',
  server: {
    port: 5173,
    strictPort: true,
    // Proxy API/WS to Python backend during Vite dev.
    proxy: {
      '/health': 'http://127.0.0.1:8765',
      '/ports': 'http://127.0.0.1:8765',
      '/status': 'http://127.0.0.1:8765',
      '/connect': 'http://127.0.0.1:8765',
      '/disconnect': 'http://127.0.0.1:8765',
      '/simulate': 'http://127.0.0.1:8765',
      '/recover': 'http://127.0.0.1:8765',
      '/command': 'http://127.0.0.1:8765',
      '/commands': 'http://127.0.0.1:8765',
      '/packets': 'http://127.0.0.1:8765',
      '/replay': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      '/tiles': 'http://127.0.0.1:8765',
      '/ws': {
        target: 'ws://127.0.0.1:8765',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
});
