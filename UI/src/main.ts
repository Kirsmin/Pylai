import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import { useThemeStore } from './stores/theme'
import { loadPublicConfig } from './utils/publicConfig'
import './assets/fonts.css'
import './assets/theme.css'

async function bootstrap() {
  const app = createApp(App)
  app.use(createPinia())

  const themeStore = useThemeStore()
  themeStore.init()
  const authStore = useAuthStore()

  // Load cookie-backed identity and public runtime configuration before first render.
  await Promise.allSettled([
    authStore.init(),
    loadPublicConfig()
  ])

  app.use(router)
  app.use(naive)
  app.mount('#app')
}

bootstrap()
