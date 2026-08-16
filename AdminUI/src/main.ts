import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import { useThemeStore } from './stores/theme'
import './assets/fonts.css'
import './assets/theme.css'
import './assets/admin.css'

async function bootstrap() {
  const app = createApp(App)
  app.use(createPinia())

  const themeStore = useThemeStore()
  themeStore.init()

  const authStore = useAuthStore()
  try {
    await authStore.init()
  } catch {
    // 登录初始化失败也继续挂载，登录页会展示错误。
  }

  app.use(router)
  app.use(naive)
  app.mount('#app')
}

bootstrap()
