import { defineConfig } from 'vitest/config';
import path from 'node:path';

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'node',
    // Root-level *.test.ts too: next.config.test.ts guards the rewrite
    // ordering that the /api proxy and the session BFF depend on.
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx', '*.test.ts'],
    globals: false,
    // jest-dom's matcher extensions; safe to load globally — they no-op
    // for tests that don't have a document, so node-env lib tests
    // (sse.test.ts, api.test.ts) aren't affected.
    setupFiles: ['./vitest.setup.ts'],
  },
});
