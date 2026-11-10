import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 开发期同源：Vite dev server 反代后端；生产同源由反向代理统一出口（design.md §2.1 / D-10）。
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8080',
      '/healthz': 'http://127.0.0.1:8080',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./test/setup.ts'],
    css: false,
    include: ['test/**/*.{test,spec}.{ts,tsx}'],
  },
});
