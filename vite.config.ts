import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_');
  const backend = env.VITE_BACKEND_URL || 'http://127.0.0.1:8787';
  return {
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: {
        '/agent': backend,
        '/changes': backend,
        '/events': backend,
        '/snapshots': backend,
        '/samples': backend,
        '/state': backend,
        '/track': backend,
      },
    },
  };
});
