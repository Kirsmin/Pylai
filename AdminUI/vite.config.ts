import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// 生产部署在 /admin/ 子路径，与 OS/UI 同源、同容器。
export default defineConfig(({ mode }) => ({
  base: '/admin/',
  plugins: [
    vue(),
    ...(mode === 'development' ? [vueDevTools()] : []),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://localhost:5000',
      '/connect': 'http://localhost:5000',
      '/health': 'http://localhost:5000',
    },
  },
  build: {
    chunkSizeWarningLimit: 600,
  },
}))
