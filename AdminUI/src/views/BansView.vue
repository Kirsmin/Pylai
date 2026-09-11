<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import DateTimeText from '@/components/DateTimeText.vue'
import type { AdminBanHistoryItem, AdminBanInfo } from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()

const tab = ref<'active' | 'history'>('active')
const active = ref<AdminBanInfo[]>([])
const history = ref<AdminBanHistoryItem[]>([])
const total = ref(0)
const loading = ref(false)
const type = ref<string | null>(null)
const page = ref(1)
const pageSize = 20

const cap = computed(() => authStore.capability('bans'))
const typeOptions = [
  { label: '登录失败 · login', value: 'login' },
  { label: '邀请码 · invite', value: 'invite' },
  { label: '邮箱验证 · email', value: 'email' },
  { label: '管理 API · admin', value: 'admin' },
  { label: '敏感确认 · confirm', value: 'confirm' }
]
const historyTypeOptions = typeOptions.filter(i => i.value !== 'confirm')

function endpointAllowed(method: string, path: string) {
  return cap.value?.endpoints.some(e => e.method === method && e.path === path) ?? false
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({ skip: String((page.value - 1) * pageSize), take: String(pageSize) })
    if (type.value) params.set('type', type.value)
    if (tab.value === 'active') {
      const data = await authStore.request<{ success: boolean; total: number; bans: AdminBanInfo[] }>(`/api/admin/bans?${params.toString()}`)
      active.value = data?.bans ?? []; total.value = data?.total ?? 0
    } else {
      const data = await authStore.request<{ success: boolean; total: number; bans: AdminBanHistoryItem[] }>(`/api/admin/bans/history?${params.toString()}`)
      history.value = data?.bans ?? []; total.value = data?.total ?? 0
    }
  } catch (err) { message.error(err instanceof Error ? err.message : '加载失败') }
  finally { loading.value = false }
}
function switchTab(v: 'active' | 'history') { tab.value = v; if (v === 'history' && type.value === 'confirm') type.value = null; page.value = 1; load() }
function search() { page.value = 1; load() }
function resetFilters() { type.value = null; page.value = 1; load() }
onMounted(load)

const ipVisible = ref(false)
const unbanIp = ref('')
const unbanIpType = ref<string | null>(null)
const unbanning = ref(false)
function openUnbanByIp() { unbanIp.value = ''; unbanIpType.value = null; ipVisible.value = true }
async function unbanByIp() {
  if (!unbanIp.value.trim()) return
  unbanning.value = true
  try {
    const params = new URLSearchParams()
    if (unbanIpType.value) params.set('type', unbanIpType.value)
    await authStore.request(`/api/admin/bans/ip/${encodeURIComponent(unbanIp.value.trim())}?${params.toString()}`, { method: 'DELETE' })
    message.success('已按 IP 执行解封'); ipVisible.value = false; load()
  } catch (err) { message.error(err instanceof Error ? err.message : '解封失败') }
  finally { unbanning.value = false }
}
async function unbanById(banId: string) {
  try {
    await authStore.request(`/api/admin/bans/${encodeURIComponent(banId)}`, { method: 'DELETE' })
    message.success('封禁已解除'); load()
  } catch (err) { message.error(err instanceof Error ? err.message : '解封失败') }
}
</script>

<template>
  <section class="admin-page">
    <PageHeader title="封禁管理" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary @click="load">刷新</NButton>
        <NButton v-if="endpointAllowed('DELETE','/api/admin/bans/ip/{ip}')" type="primary" @click="openUnbanByIp">按 IP 解封</NButton>
      </template>
    </PageHeader>

    <div class="admin-filter-panel">
      <div class="ban-filter-grid">
        <div class="admin-filter-field">
          <label>记录范围</label>
          <div class="segmented ban-tabs">
            <button type="button" :class="{active:tab==='active'}" @click="switchTab('active')">当前封禁</button>
            <button type="button" :class="{active:tab==='history'}" @click="switchTab('history')">封禁历史</button>
          </div>
        </div>
        <div class="admin-filter-field">
          <label>封禁来源</label>
          <NSelect v-model:value="type" placeholder="全部类型" clearable :options="tab==='active'?typeOptions:historyTypeOptions" />
        </div>
      </div>
      <div class="admin-filter-actions">
        <NButton quaternary @click="resetFilters">清空筛选</NButton>
        <NButton type="primary" :loading="loading" @click="search">查询</NButton>
      </div>
    </div>

    <div class="admin-context-strip">
      <span>{{ tab === 'active' ? '当前封禁' : '历史记录' }}共 <strong>{{ total }}</strong> 条</span>
      <span class="muted">解封操作会直接影响后端运行时封禁状态。</span>
    </div>

    <div>
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="tab==='active' && active.length">
        <div class="ban-list">
          <div v-for="ban in active" :key="ban.banId" class="admin-line-card active-ban-row">
            <div class="ban-copy">
              <div class="ban-heading">
                <AppBadge tone="warning">{{ ban.type }}</AppBadge>
                <strong class="mono small">{{ ban.banId }}</strong>
              </div>
              <p class="muted small ban-description">
                {{ ban.type==='confirm' ? `${ban.userName||'未知用户'}（${ban.userUid}）` : ban.ip||'未知 IP' }}
                · 失败 {{ ban.failureCount }} 次
                · 到期 <DateTimeText :value="ban.banExpires" empty="永久" />
              </p>
            </div>
            <NPopconfirm v-if="endpointAllowed('DELETE','/api/admin/bans/{banId}')" @positive-click="unbanById(ban.banId)">
              <template #trigger><NButton size="small" quaternary type="error">解封</NButton></template>
              <span style="white-space:nowrap">解除该封禁？</span>
            </NPopconfirm>
          </div>
        </div>
      </template>
      <template v-else-if="tab==='history' && history.length">
        <div class="ban-list">
          <div v-for="item in history" :key="item.id" class="admin-line-card">
            <div class="ban-copy">
              <div class="ban-heading">
                <AppBadge tone="neutral">{{ item.type }}</AppBadge>
                <strong class="mono small">#{{ item.id }} {{ item.banId }}</strong>
              </div>
              <p class="muted small ban-description">
                IP {{ item.ip }}
                · <DateTimeText :value="item.bannedAt" /> → <DateTimeText :value="item.banExpiresAt" />
                · <template v-if="item.unbannedAt">解封于 <DateTimeText :value="item.unbannedAt" /></template>
                <template v-else>未解封</template>
              </p>
            </div>
          </div>
        </div>
      </template>
      <NEmpty v-else description="没有封禁记录" class="admin-empty" />
      <AppPagination v-if="total>0" v-model:page="page" :page-size="pageSize" :total="total" @update:page="load" />
    </div>

    <NModal v-model:show="ipVisible" preset="card" style="width:min(calc(100vw - 24px),460px)" title="按 IP 解封">
      <div class="admin-form-stack">
        <label class="admin-field">
          <span class="admin-field-label">IP 地址</span>
          <NInput v-model:value="unbanIp" class="mono" placeholder="例如 203.0.113.10" />
        </label>
        <label class="admin-field">
          <span class="admin-field-label">封禁来源</span>
          <NSelect v-model:value="unbanIpType" :options="typeOptions.filter(o=>o.value!=='confirm')" clearable placeholder="留空则尝试 login / invite / admin" />
          <span class="field-hint">不确定来源时可留空，由后端按支持的 IP 封禁类型尝试解除。</span>
        </label>
        <div class="modal-actions">
          <NButton quaternary @click="ipVisible = false">取消</NButton>
          <NButton type="primary" :loading="unbanning" :disabled="!unbanIp.trim()" @click="unbanByIp">执行解封</NButton>
        </div>
      </div>
    </NModal>
  </section>
</template>

<style scoped>
.ban-filter-grid { display: grid; grid-template-columns: minmax(240px, auto) minmax(220px, 320px); gap: 10px 12px; align-items: end; }
.ban-tabs { width: max-content; }
.ban-list { display: flex; flex-direction: column; gap: 8px; }
.active-ban-row { border-left: 3px solid var(--warning); }
.ban-copy { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.ban-heading { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ban-description { margin: 0; line-height: 1.6; }
.modal-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
@media (max-width: 620px) { .ban-filter-grid { grid-template-columns: 1fr; } .ban-tabs { width: 100%; } .ban-tabs button { flex: 1; } }
</style>
