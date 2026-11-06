<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/utils/http'
import { useUrlFilters } from '@/composables/useUrlFilters'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import DateTimeText from '@/components/DateTimeText.vue'
import StateBlock from '@/components/StateBlock.vue'
import type { AdminUserListItem, AdminUserListResponse } from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()
const router = useRouter()

const pageSize = 20

const users = ref<AdminUserListItem[]>([])
const total = ref(0)
const state = ref<'loading' | 'ready' | 'empty' | 'error' | 'forbidden'>('loading')
const errorText = ref('')
const refreshing = ref(false)

const { filters, page, apply } = useUrlFilters(['q', 'group', 'status'], load)

const cap = computed(() => authStore.capability('users'))
const targetGroups = computed(() => cap.value?.targetGroups ?? [])
const canEditStatus = computed(() => cap.value?.canEditStatus ?? false)

const groupOptions = computed(() => targetGroups.value.map(g => ({ label: g, value: g })))
const statusOptions = [
  { label: '正常 · Active', value: 'Active' },
  { label: '封禁 · Banned', value: 'Banned' },
  { label: '锁定 · Locked', value: 'Locked' },
  { label: '已删除 · Deleted', value: 'Deleted' }
]

function groupTone(g: string) {
  if (g.toLowerCase() === 'normal') return 'success'
  if (g.toLowerCase() === 'admin') return 'info'
  if (g.toLowerCase() === 'max') return 'purple'
  return 'neutral'
}

// 搜索框本地草稿；URL 变化（后退/分享打开）时回填
const qInput = ref(filters.value.q ?? '')
watch(() => filters.value.q, v => { qInput.value = v ?? '' })

async function load(f = filters.value, p = page.value) {
  // 已有数据时保留旧表格，仅按钮局部 loading；无数据时整页骨架
  if (users.value.length === 0) state.value = 'loading'
  else refreshing.value = true
  errorText.value = ''
  try {
    const params = new URLSearchParams({ skip: String((p - 1) * pageSize), take: String(pageSize) })
    if (f.q?.trim()) params.set('search', f.q.trim())
    if (f.group) params.set('group', f.group)
    if (f.status) params.set('status', f.status)
    const data = await authStore.request<AdminUserListResponse>(`/api/admin/users?${params.toString()}`)
    users.value = data?.users ?? []
    total.value = data?.total ?? 0
    state.value = users.value.length > 0 ? 'ready' : 'empty'
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) {
      state.value = 'forbidden'
      users.value = []
      return
    }
    errorText.value = err instanceof Error ? err.message : '加载失败'
    // 加载失败绝不等同于"没有符合条件"；有旧数据时保留表格并显示错误横幅
    if (users.value.length === 0) state.value = 'error'
  } finally {
    refreshing.value = false
  }
}
function reload() { return load(filters.value, page.value) }
function search() { apply({ q: qInput.value.trim() || null }) }
function resetFilters() { qInput.value = ''; apply({ q: null, group: null, status: null }) }

function openUser(uid: string) {
  void router.push(`/users/${encodeURIComponent(uid)}`)
}

function moreOptions(u: AdminUserListItem) {
  const opts: Array<{ label: string; key: string }> = [{ label: '复制 UID', key: 'copy-uid' }]
  if (u.email) opts.push({ label: '复制邮箱', key: 'copy-email' })
  return opts
}
async function copyText(text: string, okText: string) {
  try {
    await navigator.clipboard.writeText(text)
    message.success(okText)
  } catch {
    message.error('复制失败，请手动复制')
  }
}
function handleMore(key: string | number, u: AdminUserListItem) {
  const a = String(key)
  if (a === 'copy-uid') void copyText(u.uid, 'UID 已复制')
  else if (a === 'copy-email' && u.email) void copyText(u.email, '邮箱已复制')
}

// 首次加载
void load()
</script>

<template>
  <section class="admin-page">
    <PageHeader title="用户管理" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary :loading="refreshing" @click="reload">刷新</NButton>
      </template>
    </PageHeader>

    <div class="admin-filter-panel">
      <div class="user-filter-grid">
        <div class="admin-filter-field user-search-filter">
          <label>用户</label>
          <NInput v-model:value="qInput" placeholder="用户名、邮箱或显示名" clearable @keyup.enter="search" />
        </div>
        <div v-if="targetGroups.length" class="admin-filter-field">
          <label>用户组</label>
          <NSelect
            :value="filters.group"
            placeholder="全部用户组"
            clearable
            :options="groupOptions"
            @update:value="(v: string | null) => apply({ group: v })"
          />
        </div>
        <div v-if="canEditStatus" class="admin-filter-field">
          <label>状态</label>
          <NSelect
            :value="filters.status"
            placeholder="全部状态"
            clearable
            :options="statusOptions"
            @update:value="(v: string | null) => apply({ status: v })"
          />
        </div>
      </div>
      <div class="admin-filter-actions">
        <NButton quaternary @click="resetFilters">清空筛选</NButton>
        <NButton type="primary" @click="search">查询</NButton>
      </div>
    </div>

    <div v-if="state === 'ready'" class="admin-context-strip">
      <span>当前条件下共 <strong>{{ total }}</strong> 个用户</span>
      <span class="muted">点击行进入详情；封禁、锁定等操作已移至详情页。</span>
    </div>

    <div class="admin-table-wrap">
      <StateBlock v-if="state === 'loading'" state="loading" variant="skeleton" loading-text="正在加载用户列表…" />
      <StateBlock
        v-else-if="state === 'forbidden'"
        state="forbidden"
        forbidden-text="没有权限查看用户列表"
        description="该能力仅对 admin / max 用户组开放。"
      />
      <StateBlock
        v-else-if="state === 'error'"
        state="error"
        error-text="用户列表加载失败"
        :description="errorText"
        retryable
        @retry="reload"
      />
      <StateBlock
        v-else-if="state === 'empty'"
        state="empty"
        empty-text="没有符合条件的用户"
        description="试试调整搜索关键词或筛选条件。"
      />
      <template v-else>
        <NAlert v-if="errorText" type="error" class="list-error-banner">
          刷新失败：{{ errorText }}（已保留旧数据）
          <NButton size="tiny" quaternary @click="reload">重试</NButton>
        </NAlert>
        <table class="admin-table user-table">
          <thead>
            <tr>
              <th>用户</th><th>邮箱</th><th>组</th><th>状态</th><th>最近登录</th><th style="text-align:right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="u in users"
              :key="u.uid"
              class="user-row"
              tabindex="0"
              @click="openUser(u.uid)"
              @keydown.enter="openUser(u.uid)"
            >
              <td>
                <div class="user-cell">
                  <span class="truncate cell-primary">{{ u.displayName || u.name }}</span>
                  <span class="mono small muted">{{ u.name }}</span>
                </div>
              </td>
              <td><span class="truncate muted">{{ u.email || '—' }}</span></td>
              <td><AppBadge :tone="groupTone(u.group)">{{ u.group }}</AppBadge></td>
              <td><StatusBadge :status="u.status" /></td>
              <td><DateTimeText :value="u.lastLoginAt" /></td>
              <td style="text-align:right" @click.stop>
                <NDropdown trigger="click" :options="moreOptions(u)" @select="(k: string | number) => handleMore(k, u)">
                  <NButton size="tiny" quaternary>更多</NButton>
                </NDropdown>
              </td>
            </tr>
          </tbody>
        </table>
        <AppPagination :page="page" :page-size="pageSize" :total="total" unit="人" @update:page="(p: number) => apply({}, p)" />
      </template>
    </div>
  </section>
</template>

<style scoped>
.user-filter-grid { display: grid; grid-template-columns: minmax(260px, 2fr) minmax(150px, .7fr) minmax(170px, .8fr); gap: 10px 12px; align-items: end; }
.user-cell { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.user-row { cursor: pointer; }
.user-row:hover .cell-primary { color: var(--accent); }
.user-row:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.list-error-banner { margin-bottom: 10px; }
@media (max-width: 780px) { .user-filter-grid { grid-template-columns: 1fr 1fr; } .user-search-filter { grid-column: 1 / -1; } }
@media (max-width: 520px) { .user-filter-grid { grid-template-columns: 1fr; } .user-search-filter { grid-column: auto; } }
</style>
