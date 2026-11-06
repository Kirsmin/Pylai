<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { ArrowLeft } from '@vicons/tabler'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/utils/http'
import AppBadge from '@/components/AppBadge.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import DateTimeText from '@/components/DateTimeText.vue'
import StateBlock from '@/components/StateBlock.vue'
import AppPagination from '@/components/AppPagination.vue'
import type {
  AdminAuditLogItem,
  AdminUserDetail,
  AdminUserDetailResponse,
  AdminUserSessionsResponse,
  AdminUserSession,
  AdminUserTokenInfo,
  AdminUserTokenUsageItem
} from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()
const route = useRoute()
const router = useRouter()

const uid = computed(() => String(route.params.uid ?? ''))

const cap = computed(() => authStore.capability('users'))
const canEditGroup = computed(() => cap.value?.canEditGroup ?? false)
const canEditStatus = computed(() => cap.value?.canEditStatus ?? false)
const canAccessControl = computed(() => canEditGroup.value || canEditStatus.value)
const targetGroups = computed(() => cap.value?.targetGroups ?? [])

function endpointAllowed(method: string, path: string) {
  return cap.value?.endpoints.some(e => e.method === method && e.path === path) ?? false
}
function groupTone(g: string) {
  if (g.toLowerCase() === 'normal') return 'success'
  if (g.toLowerCase() === 'admin') return 'info'
  if (g.toLowerCase() === 'max') return 'purple'
  return 'neutral'
}

// ============ 详情主数据 ============
const detail = ref<AdminUserDetail | null>(null)
const state = ref<'loading' | 'ready' | 'error' | 'forbidden' | 'missing'>('loading')
const errorText = ref('')
const refreshing = ref(false)

const isSelf = computed(() => detail.value?.uid === authStore.user?.uid)

async function load() {
  if (!detail.value) state.value = 'loading'
  else refreshing.value = true
  errorText.value = ''
  try {
    const data = await authStore.request<AdminUserDetailResponse>(`/api/admin/users/${encodeURIComponent(uid.value)}`)
    if (!data?.user) { state.value = 'missing'; return }
    detail.value = data.user
    state.value = 'ready'
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) { state.value = 'forbidden'; return }
    if (err instanceof ApiError && err.status === 404) { state.value = 'missing'; return }
    errorText.value = err instanceof Error ? err.message : '加载失败'
    if (!detail.value) state.value = 'error'
  } finally {
    refreshing.value = false
  }
}
watch(uid, () => { detail.value = null; void load() })
void load()

async function copyUid() {
  if (!detail.value) return
  try {
    await navigator.clipboard.writeText(detail.value.uid)
    message.success('UID 已复制')
  } catch {
    message.error('复制失败，请手动复制')
  }
}

// ============ 标签页（同步 URL query，可深链） ============
type TabKey = 'overview' | 'sessions' | 'token' | 'activity'
const TAB_KEYS: TabKey[] = ['overview', 'sessions', 'token', 'activity']
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'overview', label: '概览' },
  { key: 'sessions', label: '会话' },
  { key: 'token', label: 'UserToken' },
  { key: 'activity', label: '活动记录' }
]
const tab = ref<TabKey>(TAB_KEYS.includes(route.query.tab as TabKey) ? route.query.tab as TabKey : 'overview')
const visited = ref<Set<TabKey>>(new Set([tab.value]))

async function activateTab(next: TabKey) {
  visited.value.add(next)
  await router.replace({ query: { ...route.query, tab: next === 'overview' ? undefined : next } })
  if (next === 'sessions') await loadSessions()
  else if (next === 'token') await loadToken(0)
  else if (next === 'activity') await loadActivity(1)
}

watch(() => route.query.tab, v => {
  const next = TAB_KEYS.includes(v as TabKey) ? v as TabKey : 'overview'
  if (next !== tab.value) {
    tab.value = next
    void activateTab(next)
  }
})
// 深链直达非概览标签时主动加载（watch 不会因初值触发）
if (tab.value !== 'overview') void activateTab(tab.value)

// ============ 概览：访问控制 ============
const groupDraft = ref('normal')
watch(detail, (d) => { if (d) groupDraft.value = d.group }, { immediate: true })

const statusSaving = ref(false)
async function patchUser(body: Record<string, unknown>, okText: string) {
  if (!detail.value || statusSaving.value) return
  statusSaving.value = true
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(detail.value.uid)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    })
    message.success(okText)
    await load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    statusSaving.value = false
  }
}
const saveGroup = () => patchUser({ group: groupDraft.value }, '用户组已更新，该用户全部会话已被吊销')
const banUser = () => patchUser({ status: 'Banned' }, '用户已封禁，其全部会话已被吊销')
const lockUser = () => patchUser({ status: 'Locked' }, '用户已锁定')
const restoreUser = () => patchUser({ status: 'Active' }, '用户已恢复为正常状态')

// ============ 概览：危险区 ============
const softVisible = ref(false)
const softSaving = ref(false)
const isDeleted = computed(() => (detail.value?.status ?? '').toLowerCase() === 'deleted')
const canSoftDelete = computed(() => endpointAllowed('DELETE', '/api/admin/users/{uid}') && !isSelf.value)
const canHardDelete = computed(() => endpointAllowed('DELETE', '/api/admin/users/{uid}/hard') && !isSelf.value)

async function confirmSoftDelete() {
  if (!detail.value) return
  softSaving.value = true
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(detail.value.uid)}`, { method: 'DELETE' })
    message.success(`用户 ${detail.value.name} 已软删除，可随时重新启用`)
    softVisible.value = false
    await load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '删除失败')
  } finally {
    softSaving.value = false
  }
}

const hardVisible = ref(false)
const hardConfirmName = ref('')
const hardSaving = ref(false)
const hardNameMatched = computed(() => !!detail.value && hardConfirmName.value.trim() === detail.value.name)

function openHardDelete() {
  hardConfirmName.value = ''
  hardVisible.value = true
}
async function confirmHardDelete() {
  if (!detail.value || !hardNameMatched.value) return
  hardSaving.value = true
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(detail.value.uid)}/hard`, { method: 'DELETE' })
    message.success(`用户 ${detail.value.name} 已硬删除，用户名与邮箱已释放`)
    hardVisible.value = false
    void router.replace('/users')
  } catch (err) {
    message.error(err instanceof Error ? err.message : '删除失败')
  } finally {
    hardSaving.value = false
  }
}

// ============ 更多菜单：编辑资料 / 吊销 ============
const editVisible = ref(false)
const editSaving = ref(false)
const editForm = ref({ displayName: '', email: '' })
function openEdit() {
  if (!detail.value) return
  editForm.value = { displayName: detail.value.displayName ?? '', email: detail.value.email ?? '' }
  editVisible.value = true
}
async function saveEdit() {
  if (!detail.value) return
  editSaving.value = true
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(detail.value.uid)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ displayName: editForm.value.displayName || null, email: editForm.value.email || null })
    })
    message.success('资料已更新')
    editVisible.value = false
    await load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '更新失败')
  } finally {
    editSaving.value = false
  }
}

async function revokeAllSessions() {
  if (!detail.value) return
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(detail.value.uid)}/revoke-sessions`, { method: 'POST' })
    message.success('全部会话已吊销')
    if (visited.value.has('sessions')) await loadSessions(true)
    await load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '吊销失败')
  }
}
async function revokeToken() {
  if (!detail.value) return
  try {
    const data = await authStore.request<{ revoked?: boolean }>(
      `/api/admin/users/${encodeURIComponent(detail.value.uid)}/token`, { method: 'DELETE' }
    )
    message.success(data?.revoked === false ? '该用户没有 UserToken' : 'UserToken 已吊销')
    if (visited.value.has('token')) await loadToken(0)
    await load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '吊销失败')
  }
}

function moreOptions() {
  const opts: Array<{ label: string; key: string }> = []
  if (endpointAllowed('PATCH', '/api/admin/users/{uid}')) opts.push({ label: '编辑资料', key: 'edit' })
  if (endpointAllowed('POST', '/api/admin/users/{uid}/revoke-sessions')) opts.push({ label: '吊销全部会话', key: 'revoke-sessions' })
  if (endpointAllowed('DELETE', '/api/admin/users/{uid}/token')) opts.push({ label: '吊销 UserToken', key: 'revoke-token' })
  return opts
}
function handleMore(key: string | number) {
  const a = String(key)
  if (a === 'edit') openEdit()
  else if (a === 'revoke-sessions') void revokeAllSessions()
  else if (a === 'revoke-token') void revokeToken()
}

// ============ 重置密码（主操作；按动态策略本地预检） ============
const passwordVisible = ref(false)
const passwordSaving = ref(false)
const newPassword = ref('')
const policy = computed(() => authStore.passwordPolicy)
const pwMinLength = computed(() => {
  const g = (detail.value?.group ?? '').toLowerCase()
  const isHigh = g === 'admin' || g === 'max'
  return isHigh
    ? (policy.value?.adminRequiredLength ?? 14)
    : (policy.value?.requiredLength ?? 12)
})
const pwIssues = computed<string[]>(() => {
  const pw = newPassword.value
  if (!pw) return ['请输入新密码']
  const issues: string[] = []
  if (pw.length < pwMinLength.value) issues.push(`长度至少 ${pwMinLength.value} 位`)
  const p = policy.value
  if (p) {
    if (p.requireDigit && !/\d/.test(pw)) issues.push('需包含数字')
    if (p.requireLowercase && !/[a-z]/.test(pw)) issues.push('需包含小写字母')
    if (p.requireUppercase && !/[A-Z]/.test(pw)) issues.push('需包含大写字母')
    if (p.requireNonAlphanumeric && !/[^A-Za-z0-9]/.test(pw)) issues.push('需包含符号')
  }
  return issues
})
const passwordValid = computed(() => newPassword.value.length > 0 && pwIssues.value.length === 0)

function openPassword() {
  newPassword.value = ''
  passwordVisible.value = true
}
async function savePassword() {
  if (!detail.value || !passwordValid.value) return
  passwordSaving.value = true
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(detail.value.uid)}/reset-password`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ newPassword: newPassword.value })
    })
    message.success('密码已重置，该用户全部会话已被吊销')
    passwordVisible.value = false
    newPassword.value = ''
  } catch (err) {
    message.error(err instanceof Error ? err.message : '重置失败')
  } finally {
    passwordSaving.value = false
  }
}

// ============ 会话标签页 ============
const sessions = ref<AdminUserSession[]>([])
const sessionsState = ref<'idle' | 'loading' | 'ready' | 'error' | 'empty'>('idle')
const sessionsError = ref('')
const sessionRevoking = ref<number | null>(null)

async function loadSessions(force = false) {
  if (!force && sessionsState.value === 'ready') return
  if (sessions.value.length === 0) sessionsState.value = 'loading'
  sessionsError.value = ''
  try {
    const data = await authStore.request<AdminUserSessionsResponse>(
      `/api/admin/users/${encodeURIComponent(uid.value)}/sessions`
    )
    sessions.value = data?.sessions ?? []
    sessionsState.value = sessions.value.length > 0 ? 'ready' : 'empty'
  } catch (err) {
    sessionsError.value = err instanceof Error ? err.message : '加载失败'
    if (sessions.value.length === 0) sessionsState.value = 'error'
  }
}
async function revokeSession(id: number) {
  sessionRevoking.value = id
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(uid.value)}/sessions/${id}`, { method: 'DELETE' })
    message.success('会话已吊销')
    await loadSessions(true)
  } catch (err) {
    message.error(err instanceof Error ? err.message : '吊销失败')
  } finally {
    sessionRevoking.value = null
  }
}

// ============ UserToken 标签页 ============
const tokenInfo = ref<AdminUserTokenInfo | null>(null)
const tokenState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const tokenError = ref('')
const tokenUsage = ref<AdminUserTokenUsageItem[]>([])
const tokenPageIdx = ref(0)
const tokenTotal = ref(0)
const tokenPageSize = 20

async function loadToken(skip: number, force = false) {
  if (!force && tokenState.value === 'ready' && skip === tokenPageIdx.value * tokenPageSize) return
  tokenState.value = tokenUsage.value.length === 0 ? 'loading' : 'ready'
  tokenError.value = ''
  try {
    const data = await authStore.request<Partial<AdminUserTokenInfo> & { exists?: boolean }>(
      `/api/admin/users/${encodeURIComponent(uid.value)}/token?skip=${skip}&take=${tokenPageSize}`
    )
    tokenInfo.value = data?.exists ? (data as AdminUserTokenInfo) : null
    tokenUsage.value = data?.usage ?? []
    tokenTotal.value = data?.totalUsage ?? 0
    tokenPageIdx.value = Math.floor(skip / tokenPageSize)
    tokenState.value = 'ready'
  } catch (err) {
    tokenError.value = err instanceof Error ? err.message : '加载失败'
    if (!tokenInfo.value) tokenState.value = 'error'
  }
}

// ============ 活动记录标签页（该用户的审计事件） ============
const actLogs = ref<AdminAuditLogItem[]>([])
const actState = ref<'idle' | 'loading' | 'ready' | 'error' | 'empty' | 'forbidden'>('idle')
const actError = ref('')
const actTotal = ref(0)
const actPage = ref(1)
const actPageSize = 20

async function loadActivity(p = actPage.value) {
  if (actState.value === 'forbidden') return
  if (actLogs.value.length === 0) actState.value = 'loading'
  actError.value = ''
  try {
    const data = await authStore.request<{ total?: number; logs?: AdminAuditLogItem[] }>(
      `/api/admin/audit-logs?user=${encodeURIComponent(uid.value)}&skip=${(p - 1) * actPageSize}&take=${actPageSize}`
    )
    actLogs.value = data?.logs ?? []
    actTotal.value = data?.total ?? 0
    actPage.value = p
    actState.value = actLogs.value.length > 0 ? 'ready' : 'empty'
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) {
      actState.value = 'forbidden'
      return
    }
    actError.value = err instanceof Error ? err.message : '加载失败'
    if (actLogs.value.length === 0) actState.value = 'error'
  }
}
</script>

<template>
  <section class="admin-page">
    <StateBlock v-if="state === 'loading'" state="loading" variant="skeleton" loading-text="正在加载用户详情…" />
    <StateBlock
      v-else-if="state === 'forbidden'"
      state="forbidden"
      forbidden-text="没有权限查看该用户"
      description="admin 用户组只能查看 normal 组用户。"
    />
    <StateBlock
      v-else-if="state === 'missing'"
      state="empty"
      empty-text="用户不存在或已被删除"
      description="该用户可能已被硬删除，或链接已失效。"
    />
    <StateBlock
      v-else-if="state === 'error'"
      state="error"
      error-text="用户详情加载失败"
      :description="errorText"
      retryable
      @retry="load"
    />

    <template v-else-if="detail">
      <!-- 头部：身份 + 主操作（重置密码），其余收进「更多」 -->
      <div class="detail-header">
        <div class="detail-heading">
          <NButton quaternary size="small" class="back-btn" @click="router.push('/users')">
            <template #icon><NIcon :component="ArrowLeft" /></template>
            用户列表
          </NButton>
          <div class="detail-title-row">
            <h1 class="detail-title">{{ detail.displayName || detail.name }}</h1>
            <AppBadge :tone="groupTone(detail.group)">{{ detail.group }}</AppBadge>
            <StatusBadge :status="detail.status" />
          </div>
          <p class="detail-sub mono">{{ detail.name }}</p>
        </div>
        <div class="detail-actions">
          <NDropdown trigger="click" :options="moreOptions()" @select="handleMore">
            <NButton quaternary :disabled="refreshing">更多</NButton>
          </NDropdown>
          <NButton
            v-if="endpointAllowed('POST', '/api/admin/users/{uid}/reset-password')"
            type="primary"
            @click="openPassword"
          >
            重置密码
          </NButton>
        </div>
      </div>

      <!-- 标签：概览 / 会话 / UserToken / 活动记录 -->
      <div class="detail-tabs segmented">
        <button v-for="t in TABS" :key="t.key" type="button" :class="{ active: tab === t.key }" @click="tab = t.key">
          {{ t.label }}
        </button>
      </div>

      <!-- 概览 -->
      <div v-if="tab === 'overview'" class="tab-body">
        <div class="admin-panel">
          <div class="admin-panel-header"><span class="admin-panel-title">基本信息</span></div>
          <div class="admin-panel-body">
            <dl class="admin-detail-grid">
              <div><dt>邮箱</dt><dd>{{ detail.email || '—' }}</dd></div>
              <div>
                <dt>UID</dt>
                <dd class="mono uid-row">
                  <span class="truncate">{{ detail.uid }}</span>
                  <NButton size="tiny" quaternary @click="copyUid">复制</NButton>
                </dd>
              </div>
              <div><dt>注册时间</dt><dd><DateTimeText :value="detail.registerTime" /></dd></div>
              <div><dt>最近登录</dt><dd><DateTimeText :value="detail.lastLoginAt" empty="从未登录" /></dd></div>
              <div><dt>锁定到期</dt><dd><DateTimeText :value="detail.lockoutEnd" empty="未锁定" /></dd></div>
              <div><dt>登录失败次数</dt><dd>{{ detail.accessFailedCount }}</dd></div>
              <div><dt>活跃会话</dt><dd>{{ detail.activeSessions }}</dd></div>
              <div>
                <dt>外部登录</dt>
                <dd v-if="!detail.externalLogins.length">无</dd>
                <dd v-for="login in detail.externalLogins" :key="login.provider" class="small">
                  {{ login.providerDisplayName || login.provider }} · <DateTimeText :value="login.boundAt" />
                </dd>
              </div>
            </dl>
          </div>
        </div>

        <div v-if="canAccessControl" class="admin-panel">
          <div class="admin-panel-header">
            <span class="admin-panel-title">访问控制</span>
            <span class="admin-panel-subtitle">变更用户组或状态将吊销该用户全部会话。</span>
          </div>
          <div class="admin-panel-body control-body">
            <div v-if="canEditGroup" class="control-row">
              <span class="control-label">用户组</span>
              <NSelect v-model:value="groupDraft" class="control-select" :options="targetGroups.map(g => ({ label: g, value: g }))" />
              <NPopconfirm :disabled="groupDraft === detail.group" @positive-click="saveGroup">
                <template #trigger>
                  <NButton size="small" type="primary" secondary :disabled="groupDraft === detail.group || statusSaving" :loading="statusSaving">
                    更新用户组
                  </NButton>
                </template>
                <span style="white-space:nowrap">将用户组改为 {{ groupDraft }}？其全部会话将被吊销。</span>
              </NPopconfirm>
            </div>
            <div v-if="canEditStatus" class="control-row">
              <span class="control-label">状态</span>
              <template v-if="detail.status.toLowerCase() === 'active'">
                <NPopconfirm :disabled="isSelf" @positive-click="banUser">
                  <template #trigger>
                    <NButton size="small" quaternary type="warning" :disabled="isSelf" :loading="statusSaving">封禁</NButton>
                  </template>
                  <span style="white-space:nowrap">封禁 {{ detail.name }}？其全部会话将被吊销。</span>
                </NPopconfirm>
                <NPopconfirm :disabled="isSelf" @positive-click="lockUser">
                  <template #trigger>
                    <NButton size="small" quaternary type="warning" :disabled="isSelf" :loading="statusSaving">锁定</NButton>
                  </template>
                  <span style="white-space:nowrap">锁定 {{ detail.name }}？锁定期内无法登录。</span>
                </NPopconfirm>
              </template>
              <NPopconfirm v-else :disabled="isSelf" @positive-click="restoreUser">
                <template #trigger>
                  <NButton size="small" quaternary type="primary" :disabled="isSelf" :loading="statusSaving">
                    {{ isDeleted ? '恢复账号' : '解除封禁/锁定' }}
                  </NButton>
                </template>
                <span style="white-space:nowrap">将 {{ detail.name }} 恢复为正常状态？</span>
              </NPopconfirm>
              <span v-if="isSelf" class="muted small">不能对自己执行封禁 / 锁定 / 删除。</span>
            </div>
          </div>
        </div>
        <div v-else class="admin-panel">
          <div class="admin-panel-header">
            <span class="admin-panel-title">访问控制</span>
            <span class="admin-panel-subtitle">当前用户组仅可查看；修改用户组 / 状态需要 max 组权限。</span>
          </div>
        </div>

        <div v-if="canSoftDelete || canHardDelete || isDeleted" class="admin-panel danger-panel">
          <div class="admin-panel-header">
            <span class="admin-panel-title">危险区</span>
            <span class="admin-panel-subtitle">删除操作会立即吊销该用户的全部会话与 Token。</span>
          </div>
          <div class="admin-panel-body danger-body">
            <template v-if="canSoftDelete">
              <NButton v-if="!isDeleted" quaternary type="warning" @click="softVisible = true">软删除</NButton>
              <NPopconfirm v-else @positive-click="restoreUser">
                <template #trigger>
                  <NButton quaternary type="primary" :loading="statusSaving">恢复账号</NButton>
                </template>
                <span style="white-space:nowrap">恢复 {{ detail.name }} 为正常状态？</span>
              </NPopconfirm>
            </template>
            <NButton v-if="canHardDelete" quaternary type="error" @click="openHardDelete">硬删除</NButton>
          </div>
        </div>
      </div>

      <!-- 会话 -->
      <div v-else-if="tab === 'sessions'" class="tab-body">
        <StateBlock v-if="sessionsState === 'loading'" state="loading" variant="skeleton" loading-text="正在加载会话…" />
        <StateBlock
          v-else-if="sessionsState === 'error'"
          state="error" error-text="会话加载失败" :description="sessionsError" retryable
          @retry="loadSessions(true)"
        />
        <StateBlock v-else-if="sessionsState === 'empty'" state="empty" empty-text="没有会话记录" />
        <template v-else>
          <div class="session-list">
            <div v-for="s in sessions" :key="s.id" class="admin-line-card">
              <div class="session-copy">
                <strong :class="{ muted: !s.active }">#{{ s.id }} {{ s.active ? '活跃' : '已吊销' }}</strong>
                <span class="mono small muted"><DateTimeText :value="s.createdAt" /> → <DateTimeText :value="s.expiresAt" /></span>
                <span class="small muted">{{ s.ipAddress || '未知 IP' }} · {{ s.userAgent || '未知 UA' }}</span>
              </div>
              <NPopconfirm v-if="s.active && endpointAllowed('DELETE', '/api/admin/users/{uid}/sessions/{sessionId}')" @positive-click="revokeSession(s.id)">
                <template #trigger>
                  <NButton size="small" quaternary type="error" :loading="sessionRevoking === s.id">吊销</NButton>
                </template>
                <span style="white-space:nowrap">吊销会话 #{{ s.id }}？</span>
              </NPopconfirm>
            </div>
          </div>
          <div v-if="sessions.length" class="tab-footer">
            <NButton v-if="endpointAllowed('POST', '/api/admin/users/{uid}/revoke-sessions')" quaternary type="error" @click="revokeAllSessions">
              吊销全部会话
            </NButton>
          </div>
        </template>
      </div>

      <!-- UserToken -->
      <div v-else-if="tab === 'token'" class="tab-body">
        <StateBlock v-if="tokenState === 'loading'" state="loading" variant="skeleton" loading-text="正在加载 UserToken…" />
        <StateBlock
          v-else-if="tokenState === 'error'"
          state="error" error-text="UserToken 加载失败" :description="tokenError" retryable
          @retry="loadToken(0, true)"
        />
        <StateBlock v-else-if="!tokenInfo" state="empty" empty-text="该用户尚未创建 UserToken" />
        <template v-else>
          <dl class="admin-detail-grid">
            <div><dt>Token</dt><dd class="mono">{{ tokenInfo.tokenPrefix || '—' }}</dd></div>
            <div><dt>创建</dt><dd><DateTimeText :value="tokenInfo.createdAt" /></dd></div>
            <div><dt>刷新</dt><dd><DateTimeText :value="tokenInfo.refreshedAt" /></dd></div>
            <div><dt>过期</dt><dd><DateTimeText :value="tokenInfo.expiresAt" empty="永不过期" /></dd></div>
            <div><dt>最近使用</dt><dd><DateTimeText :value="tokenInfo.lastUsedAt" /></dd></div>
            <div><dt>最近 IP</dt><dd class="mono">{{ tokenInfo.lastIpAddress || '—' }}</dd></div>
          </dl>
          <h4 class="usage-title">使用记录</h4>
          <div v-if="tokenUsage.length" class="session-list">
            <div v-for="u in tokenUsage" :key="u.id" class="admin-line-card">
              <div class="session-copy">
                <strong class="mono small">{{ u.method }} {{ u.endpoint }}</strong>
                <span class="mono small muted"><DateTimeText :value="u.occurredAt" /> · {{ u.ipAddress || '未知 IP' }}</span>
              </div>
            </div>
          </div>
          <p v-else class="muted small">暂无使用记录</p>
          <AppPagination
            :page="tokenPageIdx + 1"
            :page-size="tokenPageSize"
            :total="tokenTotal"
            unit="条"
            @update:page="(p: number) => loadToken((p - 1) * tokenPageSize, true)"
          />
          <div class="tab-footer">
            <NButton v-if="endpointAllowed('DELETE', '/api/admin/users/{uid}/token')" quaternary type="error" @click="revokeToken">
              吊销 UserToken
            </NButton>
          </div>
        </template>
      </div>

      <!-- 活动记录 -->
      <div v-else class="tab-body">
        <StateBlock v-if="actState === 'loading'" state="loading" variant="skeleton" loading-text="正在加载活动记录…" />
        <StateBlock
          v-else-if="actState === 'forbidden'"
          state="forbidden"
          forbidden-text="没有权限查看审计日志"
          description="审计日志仅对 max 用户组开放。"
        />
        <StateBlock
          v-else-if="actState === 'error'"
          state="error" error-text="活动记录加载失败" :description="actError" retryable
          @retry="loadActivity(actPage)"
        />
        <StateBlock v-else-if="actState === 'empty'" state="empty" empty-text="该用户暂无审计事件" />
        <template v-else>
          <div class="session-list">
            <div v-for="log in actLogs" :key="log.id" class="admin-line-card">
              <div class="session-copy">
                <div class="act-heading">
                  <StatusBadge :status="log.success ? 'success' : 'failed'" />
                  <strong class="small">{{ log.eventType }}</strong>
                </div>
                <span class="mono small muted">
                  <DateTimeText :value="log.timestamp" /> · {{ log.method || '—' }} {{ log.endpoint || '—' }} · {{ log.ipAddress || '未知 IP' }}
                </span>
                <span v-if="log.details" class="small muted">{{ log.details }}</span>
              </div>
            </div>
          </div>
          <AppPagination :page="actPage" :page-size="actPageSize" :total="actTotal" unit="条" @update:page="loadActivity" />
        </template>
      </div>
    </template>

    <!-- 编辑资料 -->
    <NModal v-model:show="editVisible" preset="card" style="width:min(calc(100vw - 24px),480px)" title="编辑资料">
      <div class="admin-form-stack">
        <label class="admin-field">
          <span class="admin-field-label">显示名</span>
          <NInput v-model:value="editForm.displayName" placeholder="显示名称" />
        </label>
        <label class="admin-field">
          <span class="admin-field-label">邮箱</span>
          <NInput v-model:value="editForm.email" placeholder="user@example.com" />
        </label>
        <div class="modal-actions">
          <NButton quaternary @click="editVisible = false">取消</NButton>
          <NButton type="primary" :loading="editSaving" @click="saveEdit">保存</NButton>
        </div>
      </div>
    </NModal>

    <!-- 重置密码：必须显示目标用户名，按 capabilities 密码策略本地预检 -->
    <NModal v-model:show="passwordVisible" preset="card" style="width:min(calc(100vw - 24px),460px)" title="重置密码">
      <div class="admin-form-stack">
        <NAlert type="info" :show-icon="false">
          目标用户：<strong class="mono">{{ detail?.name }}</strong>
          <template v-if="detail?.email">（{{ detail.email }}）</template>
        </NAlert>
        <label class="admin-field">
          <span class="admin-field-label">新密码</span>
          <NInput v-model:value="newPassword" type="password" show-password-on="click" placeholder="输入新密码" />
          <span v-if="policy" class="field-hint">
            策略：至少 {{ pwMinLength }} 位<template v-if="policy.requireDigit"> · 含数字</template><template v-if="policy.requireLowercase"> · 含小写</template><template v-if="policy.requireUppercase"> · 含大写</template><template v-if="policy.requireNonAlphanumeric"> · 含符号</template><template v-if="policy.checkBreachedPasswords">；服务端另做泄露密码检查</template>
          </span>
          <span v-for="issue in newPassword ? pwIssues : []" :key="issue" class="field-error">{{ issue }}</span>
        </label>
        <p class="muted small modal-note">重置成功后，该用户全部会话将被吊销。</p>
        <div class="modal-actions">
          <NButton quaternary @click="passwordVisible = false">取消</NButton>
          <NButton type="primary" :loading="passwordSaving" :disabled="!passwordValid" @click="savePassword">重置密码</NButton>
        </div>
      </div>
    </NModal>

    <!-- 软删除确认 -->
    <NModal v-model:show="softVisible" preset="card" style="width:min(calc(100vw - 24px),480px)" title="确认软删除">
      <div class="admin-form-stack">
        <p class="modal-note">
          确认软删除 <strong>{{ detail?.name }}</strong>？其全部会话与 Token 将被吊销；账号标记为已删除，之后可随时「恢复账号」。
        </p>
        <div class="modal-actions">
          <NButton quaternary @click="softVisible = false">取消</NButton>
          <NButton type="warning" :loading="softSaving" @click="confirmSoftDelete">确认软删除</NButton>
        </div>
      </div>
    </NModal>

    <!-- 硬删除：必须输入用户名确认 -->
    <NModal v-model:show="hardVisible" preset="card" style="width:min(calc(100vw - 24px),520px)" title="确认硬删除">
      <div class="admin-form-stack">
        <div class="delete-hard-warning">
          <p><strong>此操作不可恢复。</strong></p>
          <p>
            账号 <strong>{{ detail?.name }}</strong>（{{ detail?.email || '无邮箱' }}）的全部数据——会话、UserToken、MFA 设置、
            外部登录绑定与 OAuth 授权——将被物理删除，其用户名与邮箱会立即释放，可被其他人注册。
          </p>
          <p class="muted small">确认后还需要完成 MFA（TOTP / Passkey）验证。</p>
        </div>
        <label class="admin-field">
          <span class="admin-field-label">输入用户名 <strong class="mono">{{ detail?.name }}</strong> 以确认</span>
          <NInput v-model:value="hardConfirmName" class="mono" placeholder="输入完整用户名" />
        </label>
        <div class="modal-actions">
          <NButton quaternary :disabled="hardSaving" @click="hardVisible = false">取消</NButton>
          <NButton type="error" :loading="hardSaving" :disabled="!hardNameMatched" @click="confirmHardDelete">确认硬删除</NButton>
        </div>
      </div>
    </NModal>
  </section>
</template>

<style scoped>
.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.detail-heading { min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.back-btn { align-self: flex-start; }
.detail-title-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.detail-title {
  margin: 0;
  color: var(--text);
  font-size: var(--font-size-title);
  line-height: var(--line-height-title);
  font-weight: 650;
  letter-spacing: -0.01em;
}
.detail-sub { margin: 0; color: var(--text-secondary); font-size: var(--font-size-caption); }
.detail-actions { display: flex; align-items: center; gap: var(--space-2); flex-shrink: 0; }
.detail-tabs { margin-top: var(--space-4); }
.tab-body { margin-top: var(--space-4); display: flex; flex-direction: column; gap: var(--space-4); }
.uid-row { display: flex; align-items: center; gap: 6px; min-width: 0; }
.control-body { display: flex; flex-direction: column; gap: var(--space-3); }
.control-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.control-label { width: 64px; flex-shrink: 0; font-size: 13px; font-weight: 600; color: var(--text); }
.control-select { width: 180px; }
.danger-panel { border-color: color-mix(in srgb, var(--danger) 30%, transparent); }
.danger-body { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.session-list { display: flex; flex-direction: column; gap: 8px; }
.session-copy { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.act-heading { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.usage-title { margin: 6px 0 0; font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.tab-footer { display: flex; gap: 8px; margin-top: 4px; flex-wrap: wrap; }
.modal-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
.modal-note { margin: 0; }
.delete-hard-warning { border: 1px solid rgba(208, 48, 80, .35); background: rgba(208, 48, 80, .08); border-radius: 6px; padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; }
.delete-hard-warning p { margin: 0; }
</style>
