<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { Component } from 'vue'
import { Apps, FileSearch, ShieldCheck, Ticket, Users } from '@vicons/tabler'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const router = useRouter()

const cards = computed(() => authStore.capabilities)

const icons: Record<string, Component> = {
  users: Users,
  inviteCodes: Ticket,
  bans: ShieldCheck,
  auditLogs: FileSearch,
  clients: Apps
}

function groupTone(group: string): 'success' | 'info' | 'purple' | 'neutral' {
  if (group === 'normal') return 'success'
  if (group === 'admin') return 'info'
  if (group === 'max') return 'purple'
  return 'neutral'
}
</script>

<template>
  <section class="admin-page home-page">
    <div class="admin-card hero-card">
      <div class="hero-head">
        <div>
          <h1 class="hero-title"># Pylai</h1>
          <p class="hero-subtitle">管理 Pylai 平台</p>
        </div>
        <span class="app-badge" :class="`tone-${groupTone(authStore.group)}`">
          <i class="app-badge-dot" />
          {{ authStore.group }}
        </span>
      </div>

      <p class="hero-user">
        当前登录：<strong>{{ authStore.displayName }}</strong>
        <span v-if="authStore.user?.name" class="mono muted">{{ authStore.user.name }}</span>
      </p>
    </div>

    <div v-if="cards.length > 0" class="capability-grid">
      <button
        v-for="item in cards"
        :key="item.key"
        type="button"
        class="capability-card"
        @click="router.push(item.route)"
      >
        <span class="capability-icon">
          <NIcon :component="icons[item.key]" />
        </span>
        <span class="capability-copy">
          <span class="capability-name">{{ item.name }}</span>
          <span class="capability-desc">{{ item.description }}</span>
        </span>
        <span class="capability-arrow mono">-&gt;</span>
      </button>
    </div>

    <div v-else class="admin-card empty-wrap">
      <NEmpty description="当前用户组没有可用的管理功能">
        <template #extra>
          <NButton type="success" ghost @click="authStore.logout()">退出登录</NButton>
        </template>
      </NEmpty>
    </div>
  </section>
</template>

<style scoped>
.home-page {
  gap: 14px;
}

.hero-card {
  padding: 24px;
}

.hero-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.hero-title {
  margin: 0;
  font-weight: 600;
  font-size: 32px;
  color: var(--text-primary);
}

.hero-subtitle {
  margin: 6px 0 0;
  font-size: 16px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.hero-user {
  margin: 18px 0 0;
  padding-top: 16px;
  border-top: 1px solid var(--input-border);
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 14px;
  color: var(--text-secondary);
}

.hero-user strong {
  color: var(--text-primary);
  font-weight: 600;
}

.capability-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.capability-card {
  min-height: 118px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px;
  border: 1px dashed var(--success-color);
  border-radius: 14px;
  background: var(--card-bg);
  backdrop-filter: blur(24px) saturate(1.1);
  -webkit-backdrop-filter: blur(24px) saturate(1.1);
  box-shadow: var(--card-shadow);
  color: var(--text-primary);
  cursor: pointer;
  font: inherit;
  text-align: left;
  box-sizing: border-box;
  transition: border-color 0.2s ease, background 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
}

.capability-card:hover {
  border-color: var(--success-color);
  background: var(--badge-bg);
  box-shadow: var(--card-shadow-hover);
  transform: translateY(-1px);
}

.capability-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  border-radius: 10px;
  background: var(--success-color-soft);
  color: var(--success-color);
  font-size: 20px;
}

.capability-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.capability-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.capability-desc {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.capability-arrow {
  margin-left: auto;
  align-self: center;
  color: var(--text-tertiary);
}

.empty-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 220px;
}

@media (max-width: 640px) {
  .hero-card {
    padding: 20px 16px;
  }

  .hero-title {
    font-size: 24px;
  }

  .hero-subtitle {
    font-size: 14px;
  }

  .capability-grid {
    grid-template-columns: 1fr;
  }
}
</style>
