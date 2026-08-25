<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { Component } from 'vue'
import { Apps, FileSearch, ShieldCheck, Ticket, Users } from '@vicons/tabler'
import { useAuthStore } from '@/stores/auth'
import AppBadge from '@/components/AppBadge.vue'

const authStore = useAuthStore()
const router = useRouter()

const icons: Record<string, Component> = {
  users: Users, inviteCodes: Ticket,
  bans: ShieldCheck, auditLogs: FileSearch, clients: Apps
}

const cards = computed(() => authStore.capabilities)

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 18) return '下午好'
  return '晚上好'
})

function groupTone(g: string) {
  if (g === 'normal') return 'success'
  if (g === 'admin') return 'info'
  if (g === 'max') return 'purple'
  return 'neutral'
}
</script>

<template>
  <section class="admin-page">
    <div class="hero">
      <div class="hero-text">
        <h1 class="hero-title">{{ greeting }}，{{ authStore.displayName }}</h1>
        <p class="hero-subtitle">这里是 Pylai 管理控制台，选择一个功能开始工作。</p>
      </div>
      <AppBadge :tone="groupTone(authStore.group)">{{ authStore.group }}</AppBadge>
    </div>

    <div class="stat-row">
      <div class="stat-card">
        <span class="stat-label">当前用户</span>
        <span class="stat-value truncate">{{ authStore.displayName }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">用户组</span>
        <span class="stat-value mono">{{ authStore.group }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">可用功能</span>
        <span class="stat-value">{{ cards.length }} 项</span>
      </div>
    </div>

    <div v-if="cards.length > 0" class="capability-grid">
      <button
        v-for="item in cards"
        :key="item.key"
        type="button"
        class="capability-card"
        @click="router.push(item.route)"
      >
        <span class="capability-icon"><NIcon :component="icons[item.key]" /></span>
        <span class="capability-body">
          <span class="capability-name">{{ item.name }}</span>
          <span class="capability-desc">{{ item.description }}</span>
        </span>
        <span class="capability-arrow">→</span>
      </button>
    </div>

    <div v-else class="admin-empty">
      <NEmpty description="当前用户组没有可用的管理功能">
        <template #extra>
          <NButton type="primary" ghost @click="authStore.logout()">退出登录</NButton>
        </template>
      </NEmpty>
    </div>
  </section>
</template>

<style scoped>
.hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 4px 2px 0;
}
.hero-text { min-width: 0; }
.hero-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}
.hero-subtitle {
  margin: 6px 0 0;
  font-size: 14px;
  color: var(--text-tertiary);
}

.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 14px;
}
.stat-card {
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: border-color var(--transition-base);
}
.stat-card:hover { border-color: var(--border-strong); }
.stat-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.stat-value {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
}

.capability-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 14px;
}
.capability-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  text-align: left;
  font: inherit;
  transition: border-color var(--transition-base), box-shadow var(--transition-base), transform var(--transition-base);
}
.capability-card:hover {
  border-color: var(--accent);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}
.capability-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 20px;
  flex-shrink: 0;
  transition: background var(--transition-base), color var(--transition-base);
}
.capability-card:hover .capability-icon {
  background: var(--accent);
  color: #fff;
}
.capability-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.capability-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.capability-desc {
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.capability-arrow {
  margin-left: auto;
  color: var(--text-tertiary);
  font-size: 15px;
  opacity: 0;
  transform: translateX(-4px);
  transition: opacity var(--transition-base), transform var(--transition-base), color var(--transition-base);
  flex-shrink: 0;
}
.capability-card:hover .capability-arrow {
  opacity: 1;
  transform: translateX(0);
  color: var(--accent);
}

@media (max-width: 768px) {
  .hero { flex-direction: column; }
  .capability-arrow { display: none; }
}
</style>
