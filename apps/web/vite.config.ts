import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 24173, strictPort: true, proxy: { '/api': { target: process.env.CLOSEGRAPH_API_URL ?? 'http://127.0.0.1:24180', changeOrigin: false } } },
  test: { environment: 'jsdom', setupFiles: ['./src/test/setup.ts'], include: ['src/**/*.test.{ts,tsx}'], restoreMocks: true },
});
