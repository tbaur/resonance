/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Dev server for the UI. It proxies /api to the backend and
 * runs the Vitest jsdom tests.
 */

import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = path.dirname(fileURLToPath(import.meta.url));

/**
 * Vite inlines every VITE_ variable that the code reads, and anyone who can load
 * the page can read the bundle. The UI no longer reads a token, but a leftover
 * frontend/.env from older docs is refused so it is cleaned up, not forgotten.
 */
function refuseBundledToken(mode: string): void {
  if (loadEnv(mode, rootDir, 'VITE_').VITE_API_TOKEN) {
    throw new Error(
      'VITE_API_TOKEN is set (frontend/.env or the environment). Remove it: the UI ' +
        'asks for the token in the browser instead of building it into the page.',
    );
  }
}

export default defineConfig(({ mode }) => {
  refuseBundledToken(mode);
  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(rootDir, './src'),
      },
    },
    server: {
      host: '127.0.0.1',
      // Fixed project port (not Vite's 5173 default)
      port: 8765,
      strictPort: true,
      proxy: {
        '/api': {
          // Follows RESONANCE_PORT so a non-default API port still works under `make run`.
          target: `http://127.0.0.1:${process.env.RESONANCE_PORT ?? '8000'}`,
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: 'jsdom',
      // One jsdom import per worker; each file still gets a fresh window.
      pool: 'vmThreads',
      setupFiles: ['./tests/setup.ts'],
      globals: true,
      coverage: {
        provider: 'v8',
        reporter: ['text', 'lcov'],
        include: ['src/**/*.{ts,tsx}'],
        exclude: ['src/main.tsx', 'src/vite-env.d.ts', 'src/version.ts'],
        thresholds: {
          lines: 95,
          functions: 94,
          statements: 93,
          branches: 83,
          // The store holds the optimistic-update and hold-window logic, which is
          // where the subtle races live. Gate it on its own so a global average
          // cannot hide a regression here.
          'src/store/fleetStore.ts': {
            lines: 95,
            functions: 95,
            statements: 95,
            branches: 88,
          },
          // Every method is pinned by the route table in tests/apiClient.test.ts.
          'src/api/client.ts': {
            lines: 90,
            functions: 100,
            statements: 90,
            branches: 80,
          },
        },
      },
    },
  };
});
