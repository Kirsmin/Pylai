<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { NIcon } from 'naive-ui'
import { Sun, MoonStars } from '@vicons/tabler'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

const authStore = useAuthStore()
const themeStore = useThemeStore()
const router = useRouter()

const userDisplayName = computed(() =>
  authStore.user?.displayName || authStore.user?.name || ''
)

const themeIcon = computed(() => (themeStore.isDark ? MoonStars : Sun))
const themeIconClass = computed(() =>
  themeStore.isDark ? 'theme-icon-moon' : 'theme-icon-sun'
)
</script>

<template>
  <div class="dock">
    <div class="dock-item dock-logo" @click="router.push('/')">
      <span class="logo-text">Pylai</span>
    </div>

    <div class="dock-item dock-theme" @click="themeStore.toggle()">
      <NIcon :class="['theme-icon', themeIconClass]" :component="themeIcon" />
    </div>

    <div class="dock-item dock-user">
      <template v-if="authStore.isAuthenticated">
        <span class="user-name" @click="router.push('/login')">{{ userDisplayName }}</span>
      </template>
      <template v-else>
        <span class="auth-link" @click="router.push('/login')">登录</span>
        <span class="auth-separator">·</span>
        <span class="auth-link" @click="router.push('/register')">注册</span>
      </template>
    </div>

    
    <div class="dock-spacer">
      <slot name="spacer" />
    </div>
  </div>
</template>

<style scoped>
.dock {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 8px 10px;
  border-radius: 16px;
  background: var(--card-bg);
  backdrop-filter: blur(24px) saturate(1.1);
  -webkit-backdrop-filter: blur(24px) saturate(1.1);
  border: 1px solid var(--card-border);
  box-shadow: var(--card-shadow);
  box-sizing: border-box;
}

.dock-item {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 10px;
  cursor: pointer;
  color: var(--text-secondary);
  transition: background 0.2s ease, color 0.2s ease;
  user-select: none;
  white-space: nowrap;
}

.dock-item:hover {
  background: var(--dock-item-hover);
  color: var(--text-primary);
}

.dock-logo .logo-text {
  font-family: var(--font-family-mono);
  font-weight: 700;
  font-size: 16px;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.theme-icon {
  font-size: 20px;
  transition: transform 0.2s ease, color 0.2s ease;
}

.theme-icon-sun {
  color: #fbbf24;
}

.theme-icon-moon {
  color: #93c5fd;
}

.dock-user {
  font-size: 14px;
  font-weight: 500;
}

.user-name {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.auth-link {
  color: inherit;
}

.auth-separator {
  margin: 0 2px;
  color: var(--text-tertiary);
}

.dock-spacer {
  flex: 1;
  min-width: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
}

.dock-spacer:empty {
  display: block;
}

@media (max-width: 640px) {
  .dock {
    padding: 6px 8px;
    border-radius: 14px;
  }

  .dock-item {
    padding: 6px 10px;
  }

  .logo-text {
    font-size: 15px;
  }

  .theme-icon {
    font-size: 18px;
  }

  .dock-user {
    font-size: 13px;
  }
}
</style>
