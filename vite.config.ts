import { defineConfig } from 'vite';
import { sveltekit } from '@sveltejs/kit/vite';

export default defineConfig({
  plugins: [sveltekit()],
  clearScreen: false,
  server: {
    strictPort: true,
    proxy: {
      '/api': process.env.ON_AIR_API_PROXY || 'http://127.0.0.1:8000',
      '/health': process.env.ON_AIR_API_PROXY || 'http://127.0.0.1:8000',
    },
  },
  envPrefix: ['VITE_', 'TAURI_'],
  build: { target: process.env.TAURI_ENV_PLATFORM === 'windows' ? 'chrome105' : 'safari13' },
});
