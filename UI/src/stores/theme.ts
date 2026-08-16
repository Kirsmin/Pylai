import { ref } from 'vue'
import { defineStore } from 'pinia'

const STORAGE_KEY = 'pylai_theme'

export const useThemeStore = defineStore('theme', () => {
  const isDark = ref(false)

  function init() {

    const saved = localStorage.getItem(STORAGE_KEY)
    isDark.value = saved === 'dark'
    apply()
  }

  function apply() {
    if (isDark.value) {
      document.documentElement.classList.add('dark')
      localStorage.setItem(STORAGE_KEY, 'dark')
    } else {
      document.documentElement.classList.remove('dark')
      localStorage.setItem(STORAGE_KEY, 'light')
    }
  }

  function toggle() {
    isDark.value = !isDark.value
    apply()
  }

  return { isDark, init, toggle }
})
