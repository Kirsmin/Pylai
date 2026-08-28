import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [
    vue({
      template: {
        compilerOptions: {
          isCustomElement: (tag) => tag === 'altcha-widget'
        }
      }
    }),
    // 仅开发模式启用 vue-devtools，生产构建不包含
    ...(mode === 'development' ? [vueDevTools()] : []),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
  server: {
    // 同域开发：将后端请求代理到 Pylaios，避免跨域 Cookie 问题
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
