import { defineConfig } from 'vitest/config';
import path from 'node:path';

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      // next.config picks the licensed module at build time; tests always use the stand-in.
      '@gummi-font': path.resolve(__dirname, './src/app/fonts/gummi.fallback.ts'),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    globals: false,
    // jest-dom's matcher extensions; safe to load globally — they no-op
    // for tests that don't have a document, so node-env lib tests
    // (sse.test.ts, api.test.ts) aren't affected.
    setupFiles: ['./vitest.setup.ts'],
  },
});
