import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/events': 'http://127.0.0.1:8787',
      '/track': 'http://127.0.0.1:8787',
    },
  },
});
