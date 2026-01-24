import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    strictPort: true,
    port: 1420,
    headers: {
      'Cache-Control': 'no-store'
    }
  },
  clearScreen: false
});
