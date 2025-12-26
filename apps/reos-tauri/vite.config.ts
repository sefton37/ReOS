import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    strictPort: true,
    port: 1420,
    headers: {
      'Cache-Control': 'no-store'
    }
  },
  clearScreen: false
});
