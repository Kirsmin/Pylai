<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { Component } from 'vue'
import { Apps, FileSearch, ShieldCheck, Ticket, Users } from '@vicons/tabler'
import { useAuthStore } from '@/stores/auth'
import { groupLabel } from '@/utils/labels'

const authStore = useAuthStore()
const router = useRouter()

const icons: Record<string, Component> = {
  users: Users, inviteCodes: Ticket,
  bans: ShieldCheck, auditLogs: FileSearch, clients: Apps
}

const cards = computed(() => authStore.capabilities)

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
      <div>
        <h1 class="hero-title">Pylai 管理后台</h1>
        <p class="hero-subtitle">管理控制台</p>
      </div>
      <span class="app-badge" :class="`tone-${groupTone(authStore.group)}`">
        {{ groupLabel(authStore.group) }}
      </span>
    </div>

    <div class="stat-row">
      <div class="stat-card">
        <span class="stat-label">当前用户</span>
        <span class="stat-value">{{ authStore.displayName }}</span>
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
        <span class="capability-name">{{ item.name }}</span>
        <span class="capability-desc">{{ item.description }}</span>
        <span class="capability-arrow mono">-></span>
      </button>
    </div>

    <div v-else class="admin-empty">
      <NEmpty description="当前用户组没有可用的管理功能">
        <template #extra>
          <NButton type="success" ghost @click="authStore.logout()">退出登录</NButton>
        </template>
      </NEmpty>
    </div>
  </section>
</template>

<style scoped>
.hero {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
}
.hero-title { margin: 0; font-size: 28px; font-weight: 700; letter-spacing: -0.02em; }
.hero-subtitle { margin: 6px 0 0; font-size: 14px; color: var(--text-tertiary); }

.stat-row { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
.stat-card {
  padding: 16px; border: 1px solid var(--border); border-radius: var(--radius-md);
  background: var(--surface); display: flex; flex-direction: column; gap: 6px;
  transition: border-color var(--transition-base);
}
.stat-card:hover { border-color: var(--border-strong); }
.stat-label { font-size: 12px; color: var(--text-tertiary); text-transform: uppercase; letter-spacing: 0.05em; }
.stat-value { font-size: 16px; font-weight: 600; color: var(--text-primary); }

.capability-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px;
}
.capability-card {
  display: flex; align-items: center; gap: 14px;
  padding: 18px; border: 1px solid var(--border); border-radius: var(--radius-md);
  background: var(--surface); cursor: pointer; text-align: left; font: inherit;
  transition: all var(--transition-base);
}
.capability-card:hover {
  border-color: var(--success);
  background: var(--success-soft);
  transform: translateY(-1px);
}
.capability-icon {
  width: 40px; height: 40px; border-radius: var(--radius-sm);
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--success-soft); color: var(--success); font-size: 20px;
  transition: background var(--transition-base);
}
.capability-card:hover .capability-icon { background: var(--success); color: #fff; }
.capability-name { font-size: 15px; font-weight: 600; color: var(--text-primary); }
.capability-desc { font-size: 12px; color: var(--text-tertiary); line-height: 1.4; }
.capability-arrow { margin-left: auto; color: var(--text-tertiary); font-size: 12px; transition: color var(--transition-base); }
.capability-card:hover .capability-arrow { color: var(--success); }
</style>