import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import path from 'path';

export default defineConfig({
  plugins: [svelte()],
  define: {
    'import.meta.env.VITE_SICOOBITO_API_KEY': JSON.stringify(
      process.env.VITE_SICOOBITO_API_KEY || process.env.SICOOBITO_API_KEY || 'REDACTED_API_KEY'
    )
  },
  resolve: {
    alias: {
      '$lib': path.resolve(__dirname, './src/lib'),
      '@': path.resolve(__dirname, './src')
    }
  },
  server: {
    port: 5409,
    strictPort: true,
    host: true
  },
  preview: {
    port: 5409,
    strictPort: true,
    host: true
  }
});
