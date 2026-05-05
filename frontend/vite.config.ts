// Vite config — tuned for Docker development.
// `host: 0.0.0.0` is required so the container exposes the dev server to the
// host. `usePolling` is required because filesystem events from a bind mount
// don't reach the container reliably on macOS.

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    watch: {
      usePolling: true,
      interval: 200,
    },
  },
});
