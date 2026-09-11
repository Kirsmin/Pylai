import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

const packageJson = JSON.parse(
  readFileSync(fileURLToPath(new URL('./package.json', import.meta.url)), 'utf-8')
) as { version: string }

// 生产部署在 /admin/ 子路径，与 OS/UI 同源、同容器。
export default defineConfig(({ mode }) => ({
  base: '/admin/',
  define: {
    __APP_VERSION__: JSON.stringify(packageJson.version),
  },
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
