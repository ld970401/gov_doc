import vue from '@vitejs/plugin-vue';
import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';

export default defineConfig({
  base: '/document-chat/',
  plugins: [vue()],
  optimizeDeps: {
    include: [
      'tinymce/tinymce',
      'tinymce/themes/silver/theme',
      'tinymce/icons/default/icons',
      'tinymce/models/dom/model',
    ],
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 8080,
    proxy: {
      '/ucenter': {
        target: 'https://10.108.8.116:18085',
        changeOrigin: true,
        ws: true,
        secure: false,
      },
      '/bsp': {
        target: 'https://10.108.8.116:18085',
        changeOrigin: true,
        ws: true,
        secure: false,
      },
      '/api/agentloop': {
        target: 'http://10.108.8.116:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
  build: {
    outDir: 'dist/document-chat',
  },
});
