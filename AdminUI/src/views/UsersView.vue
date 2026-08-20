<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import DateTimeText from '@/components/DateTimeText.vue'
import type {
  AdminUserDetail,
  AdminUserListItem,
  AdminUserSession,
  AdminUserTokenUsageItem
} from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()
const dialog = useDialog()

const users = ref<AdminUserListItem[]>([])
const total = ref(0)
const loading = ref(false)
const search = ref('')
const group = ref<string | null>(null)
const status = ref<string | null>(null)
const page = ref(1)
const pageSize = 20

const cap = computed(() => authStore.capability('users'))
const targetGroups = computed(() => cap.value?.targetGroups ?? [])
const canEditGroup = computed(() => cap.value?.canEditGroup ?? false)
const canEditStatus = computed(() => cap.value?.canEditStatus ?? false)

const groupOptions = computed(() => targetGroups.value.map((g) => ({ label: g, value: g })))
const statusOptions = [
  { label: 'Active', value: 'Active' },
  { label: 'Banned', value: 'Banned' },
  { label: 'Locked', value: 'Locked' },
  { label: 'Deleted', value: 'Deleted' }
]

const statusLabels: Record<string, string> = {
  Active: 'Active',
  Banned: 'Banned',
  Locked: 'Locked',
  Deleted: 'Deleted'
}

function groupTone(group: string): 'success' | 'info' | 'purple' | 'neutral' {
  if (group.toLowerCase() === 'normal') return 'success'
  if (group.toLowerCase() === 'admin') return 'info'
  if (group.toLowerCase() === 'max') return 'purple'
  return 'neutral'
}

function statusTone(status: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status.toLowerCase() === 'active') return 'success'
  if (status.toLowerCase() === 'banned') return 'danger'
  if (status.toLowerCase() === 'locked') return 'warning'
  return 'neutral'
}

function endpointAllowed(method: string, path: string): boolean {
  return cap.value?.endpoints.some((e) => e.method === method && e.path === path) ?? false
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      skip: String((page.value - 1) * pageSize),
      take: String(pageSize)
    })
    if (search.value.trim()) params.set('search', search.value.trim())
    if (group.value) params.set('group', group.value)
    if (status.value) params.set('status', status.value)

    const data = await authStore.request<{ success: boolean; total: number; users: AdminUserListItem[] }>(
      `/api/admin/users?${params.toString()}`
    )
    users.value = data?.users ?? []
    total.value = data?.total ?? 0
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载用户失败')
  } finally {
    loading.value = false
  }
}

function searchUsers() {
  page.value = 1
  load()
}

function resetFilters() {
  search.value = ''
  group.value = null
  status.value = null
  page.value = 1
  load()
}

onMounted(load)

// ===== 详情 =====
const detailVisible = ref(false)
const detail = ref<AdminUserDetail | null>(null)
const detailLoading = ref(false)

async function openDetail(uid: string) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const data = await authStore.request<{ success: boolean; user: AdminUserDetail | null }>(
      `/api/admin/users/${encodeURIComponent(uid)}`
    )
    detail.value = data?.user ?? null
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载用户详情失败')
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

// ===== 编辑 =====
const editVisible = ref(false)
const editUid = ref('')
const editSaving = ref(false)
const editForm = ref({
  displayName: '',
  email: '',
  status: 'Active',
  group: 'normal'
})

function openEdit(user: AdminUserListItem) {
  editUid.value = user.uid
  editForm.value = {
    displayName: user.displayName ?? '',
    email: user.email ?? '',
    status: user.status,
    group: user.group
  }
  editVisible.value = true
}

async function saveEdit() {
  editSaving.value = true
  try {
    const body: Record<string, unknown> = {
      displayName: editForm.value.displayName || null,
      email: editForm.value.email || null
    }
    if (canEditStatus.value) body.status = editForm.value.status
    if (canEditGroup.value) body.group = editForm.value.group
    await authStore.request(`/api/admin/users/${encodeURIComponent(editUid.value)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    message.success('用户已更新')
    editVisible.value = false
    load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '更新用户失败')
  } finally {
    editSaving.value = false
  }
}

// ===== 快捷状态切换（按钮，非编辑框） =====
const statusSavingUid = ref('')

async function setStatus(user: AdminUserListItem, nextStatus: string) {
  statusSavingUid.value = user.uid
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(user.uid)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: nextStatus })
    })
    message.success(`用户状态已切换为 ${statusLabels[nextStatus] ?? nextStatus}`)
    load()
    if (detail.value?.uid === user.uid) openDetail(user.uid)
  } catch (err) {
    message.error(err instanceof Error ? err.message : '切换用户状态失败')
  } finally {
    statusSavingUid.value = ''
  }
}

// ===== 重置密码 =====
const passwordVisible = ref(false)
const passwordUid = ref('')
const passwordSaving = ref(false)
const newPassword = ref('')

function openPassword(user: AdminUserListItem) {
  passwordUid.value = user.uid
  newPassword.value = ''
  passwordVisible.value = true
}

async function savePassword() {
  if (!newPassword.value) return
  if (newPassword.value.length < 12) {
    message.warning('新密码至少 12 个字符')
    return
  }
  passwordSaving.value = true
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(passwordUid.value)}/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ newPassword: newPassword.value })
    })
    message.success('密码已重置，该用户全部会话已吊销')
    passwordVisible.value = false
    newPassword.value = ''
  } catch (err) {
    message.error(err instanceof Error ? err.message : '重置密码失败')
  } finally {
    passwordSaving.value = false
  }
}

// ===== 会话 =====
const sessionsVisible = ref(false)
const sessionsUid = ref('')
const sessionsLoading = ref(false)
const sessions = ref<AdminUserSession[]>([])

async function loadSessions(uid: string) {
  sessionsLoading.value = true
  sessions.value = []
  try {
    const data = await authStore.request<{ success: boolean; sessions: AdminUserSession[] }>(
      `/api/admin/users/${encodeURIComponent(uid)}/sessions`
    )
    sessions.value = data?.sessions ?? []
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载会话失败')
  } finally {
    sessionsLoading.value = false
  }
}

function openSessions(user: AdminUserListItem) {
  sessionsUid.value = user.uid
  sessionsVisible.value = true
  loadSessions(user.uid)
}

async function revokeSession(sessionId: number) {
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(sessionsUid.value)}/sessions/${sessionId}`, {
      method: 'DELETE'
    })
    message.success('会话已吊销')
    loadSessions(sessionsUid.value)
  } catch (err) {
    message.error(err instanceof Error ? err.message : '吊销会话失败')
  }
}

async function revokeAllSessions(uid: string) {
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(uid)}/revoke-sessions`, {
      method: 'POST'
    })
    message.success('全部会话已吊销')
    if (sessionsVisible.value) loadSessions(uid)
  } catch (err) {
    message.error(err instanceof Error ? err.message : '吊销会话失败')
  }
}

// ===== Token =====
const tokenVisible = ref(false)
const tokenUid = ref('')
const tokenLoading = ref(false)
const tokenPrefix = ref('')
const tokenCreatedAt = ref<string | null>(null)
const tokenRefreshedAt = ref<string | null>(null)
const tokenExpiresAt = ref<string | null>(null)
const tokenLastUsedAt = ref<string | null>(null)
const tokenLastIp = ref<string | null>(null)
const tokenTotal = ref(0)
const tokenUsage = ref<AdminUserTokenUsageItem[]>([])
const tokenPage = ref(0)
const tokenPageSize = 20

async function loadToken(uid: string, skip: number) {
  tokenLoading.value = true
  try {
    const data = await authStore.request<{
      success: boolean
      exists: boolean
      tokenPrefix?: string | null
      createdAt?: string | null
      refreshedAt?: string | null
      expiresAt?: string | null
      lastUsedAt?: string | null
      lastIpAddress?: string | null
      totalUsage?: number
      usage?: AdminUserTokenUsageItem[]
    }>(`/api/admin/users/${encodeURIComponent(uid)}/token?skip=${skip}&take=${tokenPageSize}`)
    tokenPrefix.value = data?.exists ? data.tokenPrefix ?? '—' : '未创建'
    tokenCreatedAt.value = data?.createdAt ?? null
    tokenRefreshedAt.value = data?.refreshedAt ?? null
    tokenExpiresAt.value = data?.expiresAt ?? null
    tokenLastUsedAt.value = data?.lastUsedAt ?? null
    tokenLastIp.value = data?.lastIpAddress ?? null
    tokenTotal.value = data?.totalUsage ?? 0
    tokenUsage.value = data?.usage ?? []
    tokenPage.value = Math.floor(skip / tokenPageSize)
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载 UserToken 失败')
  } finally {
    tokenLoading.value = false
  }
}

function openToken(user: AdminUserListItem) {
  tokenUid.value = user.uid
  tokenVisible.value = true
  loadToken(user.uid, 0)
}

function tokenPrev() {
  if (tokenPage.value > 0) loadToken(tokenUid.value, (tokenPage.value - 1) * tokenPageSize)
}

function tokenNext() {
  if ((tokenPage.value + 1) * tokenPageSize < tokenTotal.value) {
    loadToken(tokenUid.value, (tokenPage.value + 1) * tokenPageSize)
  }
}

async function revokeToken(uid: string) {
  try {
    const data = await authStore.request<{ success: boolean; revoked: boolean }>(
      `/api/admin/users/${encodeURIComponent(uid)}/token`,
      { method: 'DELETE' }
    )
    message.success(data?.revoked === false ? '该用户没有 UserToken' : 'UserToken 已吊销')
    if (tokenVisible.value) loadToken(uid, 0)
    if (detailVisible.value && detail.value?.uid === uid) openDetail(uid)
  } catch (err) {
    message.error(err instanceof Error ? err.message : '吊销 UserToken 失败')
  }
}

// ===== 更多操作菜单 =====
function moreOptions(user: AdminUserListItem): Array<{ label: string; key: string }> {
  const options: Array<{ label: string; key: string }> = []
  if (endpointAllowed('POST', '/api/admin/users/{uid}/reset-password')) options.push({ label: '重置密码', key: 'password' })
  if (endpointAllowed('GET', '/api/admin/users/{uid}/sessions')) options.push({ label: '会话', key: 'sessions' })
  if (endpointAllowed('GET', '/api/admin/users/{uid}/token')) options.push({ label: 'Token', key: 'token' })
  if (endpointAllowed('DELETE', '/api/admin/users/{uid}')) options.push({ label: '删除用户', key: 'delete' })
  return options
}

function confirmDelete(user: AdminUserListItem) {
  dialog.warning({
    title: '删除用户',
    content: `软删除用户 ${user.name} 并吊销其会话 / Token，确定？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => deleteUser(user.uid)
  })
}

function handleMore(key: string | number, user: AdminUserListItem) {
  const action = String(key)
  if (action === 'password') openPassword(user)
  else if (action === 'sessions') openSessions(user)
  else if (action === 'token') openToken(user)
  else if (action === 'delete') confirmDelete(user)
}

// ===== 删除 =====
async function deleteUser(uid: string) {
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(uid)}`, { method: 'DELETE' })
    message.success('用户已删除（软删除）')
    if (detailVisible.value) detailVisible.value = false
    load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '删除用户失败')
  }
}
</script>

<template>
  <section class="admin-page">
    <PageHeader title="用户管理" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary type="success" @click="load">刷新</NButton>
      </template>
    </PageHeader>

    <div class="admin-toolbar">
      <NInput v-model:value="search" class="search-input" placeholder="搜索用户名 / 邮箱 / 显示名" clearable @keyup.enter="searchUsers" />
      <NSelect
        v-if="targetGroups.length > 0"
        v-model:value="group"
        class="tool-select"
        placeholder="用户组"
        clearable
        :options="groupOptions"
        @update:value="searchUsers"
      />
      <NSelect
        v-if="canEditStatus"
        v-model:value="status"
        class="tool-select"
        placeholder="状态"
        clearable
        :options="statusOptions"
        @update:value="searchUsers"
      />
      <NButton type="success" ghost @click="searchUsers">查询</NButton>
      <NButton quaternary @click="resetFilters">重置</NButton>
    </div>

    <div class="admin-table-card">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="users.length > 0">
        <div class="admin-table-wrap">
          <table class="admin-table table-users">
            <colgroup>
              <col style="width: 21%" />
              <col style="width: 22%" />
              <col style="width: 9%" />
              <col style="width: 9%" />
              <col style="width: 17%" />
              <col style="width: 22%" />
            </colgroup>
            <thead>
              <tr>
                <th>用户</th>
                <th>邮箱</th>
                <th>组</th>
                <th>状态</th>
                <th>最近登录（UTC+8）</th>
                <th class="cell-actions">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="user in users" :key="user.uid">
                <td>
                  <div class="cell-stack">
                    <span class="cell-primary cell-ellipsis">{{ user.displayName || user.name }}</span>
                    <span class="mono cell-secondary cell-ellipsis">{{ user.name }}</span>
                  </div>
                </td>
                <td>
                  <span class="cell-secondary cell-ellipsis">{{ user.email || '—' }}</span>
                </td>
                <td><AppBadge :tone="groupTone(user.group)">{{ user.group }}</AppBadge></td>
                <td><AppBadge :tone="statusTone(user.status)">{{ statusLabels[user.status] ?? user.status }}</AppBadge></td>
                <td><DateTimeText :value="user.lastLoginAt" /></td>
                <td>
                  <div class="cell-actions">
                    <NButton v-if="endpointAllowed('GET', '/api/admin/users/{uid}')" size="tiny" quaternary type="success" @click="openDetail(user.uid)">详情</NButton>
                    <NButton v-if="endpointAllowed('PATCH', '/api/admin/users/{uid}')" size="tiny" quaternary type="success" @click="openEdit(user)">编辑</NButton>

                    <template v-if="canEditStatus && endpointAllowed('PATCH', '/api/admin/users/{uid}')">
                      <NPopconfirm
                        v-if="user.status.toLowerCase() === 'active'"
                        @positive-click="setStatus(user, 'Banned')"
                      >
                        <template #trigger>
                          <NButton size="tiny" quaternary type="warning" :loading="statusSavingUid === user.uid">封禁</NButton>
                        </template>
                        <span style="white-space: nowrap;">封禁用户 {{ user.name }}？</span>
                      </NPopconfirm>
                      <NPopconfirm
                        v-if="user.status.toLowerCase() === 'active'"
                        @positive-click="setStatus(user, 'Locked')"
                      >
                        <template #trigger>
                          <NButton size="tiny" quaternary type="warning" :loading="statusSavingUid === user.uid">锁定</NButton>
                        </template>
                        <span style="white-space: nowrap;">锁定用户 {{ user.name }}？</span>
                      </NPopconfirm>
                      <NPopconfirm
                        v-if="user.status.toLowerCase() !== 'active'"
                        @positive-click="setStatus(user, 'Active')"
                      >
                        <template #trigger>
                          <NButton size="tiny" quaternary type="success" :loading="statusSavingUid === user.uid">启用</NButton>
                        </template>
                        <span style="white-space: nowrap;">启用用户 {{ user.name }}？</span>
                      </NPopconfirm>
                    </template>

                    <NDropdown
                      v-if="moreOptions(user).length > 0"
                      trigger="click"
                      :options="moreOptions(user)"
                      @select="(key: string | number) => handleMore(key, user)"
                    >
                      <NButton size="tiny" quaternary>更多</NButton>
                    </NDropdown>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <AppPagination v-model:page="page" :page-size="pageSize" :total="total" unit="人" @update:page="load" />
      </template>
      <NEmpty v-else description="没有符合条件的用户" class="admin-empty" />
    </div>

    <!-- 详情 -->
    <NModal v-model:show="detailVisible" preset="card" style="width: min(92%, 760px);" title="用户详情">
      <div v-if="detailLoading" class="admin-modal-state"><NSpin /></div>
      <template v-else-if="detail">
        <dl class="admin-detail-grid">
          <div><dt>UID</dt><dd class="mono">{{ detail.uid }}</dd></div>
          <div><dt>登录名</dt><dd class="mono">{{ detail.name }}</dd></div>
          <div><dt>显示名</dt><dd>{{ detail.displayName || '—' }}</dd></div>
          <div><dt>邮箱</dt><dd>{{ detail.email || '—' }}</dd></div>
          <div><dt>用户组</dt><dd><AppBadge :tone="groupTone(detail.group)">{{ detail.group }}</AppBadge></dd></div>
          <div><dt>状态</dt><dd><AppBadge :tone="statusTone(detail.status)">{{ statusLabels[detail.status] ?? detail.status }}</AppBadge></dd></div>
          <div><dt>注册时间（UTC+8）</dt><dd><DateTimeText :value="detail.registerTime" /></dd></div>
          <div><dt>最近登录（UTC+8）</dt><dd><DateTimeText :value="detail.lastLoginAt" /></dd></div>
          <div><dt>锁定到期（UTC+8）</dt><dd><DateTimeText :value="detail.lockoutEnd" empty="未锁定" /></dd></div>
          <div><dt>失败次数</dt><dd>{{ detail.accessFailedCount }}</dd></div>
          <div><dt>活跃会话</dt><dd>{{ detail.activeSessions }}</dd></div>
          <div>
            <dt>外部登录</dt>
            <dd v-if="detail.externalLogins.length === 0">无</dd>
            <dd v-for="login in detail.externalLogins" :key="login.provider" class="mono">
              {{ login.providerDisplayName || login.provider }} · <DateTimeText :value="login.boundAt" />
            </dd>
          </div>
        </dl>
        <div class="admin-form-actions">
          <NButton v-if="endpointAllowed('POST', '/api/admin/users/{uid}/revoke-sessions')" quaternary type="warning" @click="revokeAllSessions(detail.uid)">吊销全部会话</NButton>
          <NButton v-if="endpointAllowed('DELETE', '/api/admin/users/{uid}/token')" quaternary type="error" @click="revokeToken(detail.uid)">吊销 UserToken</NButton>
        </div>
      </template>
    </NModal>

    <!-- 编辑 -->
    <NModal v-model:show="editVisible" preset="card" style="width: min(92%, 520px);" title="编辑用户">
      <div class="admin-form-stack">
        <label class="admin-field">
          <span class="admin-field-label">显示名</span>
          <input v-model="editForm.displayName" class="admin-input" placeholder="显示名称" />
        </label>
        <label class="admin-field">
          <span class="admin-field-label">邮箱</span>
          <input v-model="editForm.email" class="admin-input" placeholder="user@example.com" />
        </label>

        <div v-if="canEditStatus" class="admin-field">
          <span class="admin-field-label">状态</span>
          <div class="admin-segmented">
            <button
              v-for="option in statusOptions"
              :key="option.value"
              type="button"
              :class="{ active: editForm.status === option.value }"
              @click="editForm.status = option.value"
            >
              {{ option.label }}
            </button>
          </div>
        </div>

        <div v-if="canEditGroup" class="admin-field">
          <span class="admin-field-label">用户组</span>
          <div class="admin-segmented">
            <button
              v-for="option in groupOptions"
              :key="option.value"
              type="button"
              :class="{ active: editForm.group === option.value }"
              @click="editForm.group = option.value"
            >
              {{ option.label }}
            </button>
          </div>
        </div>

        <div class="admin-form-actions" style="margin-top: 0;">
          <NButton type="success" ghost :loading="editSaving" @click="saveEdit">保存</NButton>
        </div>
      </div>
    </NModal>

    <!-- 重置密码 -->
    <NModal v-model:show="passwordVisible" preset="card" style="width: min(92%, 420px);" title="重置密码">
      <div class="admin-form-stack">
        <label class="admin-field">
          <span class="admin-field-label">新密码</span>
          <input v-model="newPassword" type="password" class="admin-input" placeholder="输入新密码" />
        </label>
        <p class="muted">重置后该用户全部会话将被吊销。</p>
        <div class="admin-form-actions" style="margin-top: 0;">
          <NButton type="success" ghost :loading="passwordSaving" :disabled="!newPassword" @click="savePassword">重置密码</NButton>
        </div>
      </div>
    </NModal>

    <!-- 会话 -->
    <NModal v-model:show="sessionsVisible" preset="card" style="width: min(92%, 720px);" title="用户会话">
      <div v-if="sessionsLoading" class="admin-modal-state"><NSpin /></div>
      <template v-else>
        <div v-if="sessions.length > 0" class="admin-stack">
          <div v-for="s in sessions" :key="s.id" class="admin-line-card">
            <div class="admin-line-main">
              <strong :class="{ muted: !s.active }">#{{ s.id }} {{ s.active ? '活跃' : '已吊销' }}</strong>
              <span class="mono muted"><DateTimeText :value="s.createdAt" /> → <DateTimeText :value="s.expiresAt" /></span>
              <span class="muted">{{ s.ipAddress || '未知 IP' }} · {{ s.userAgent || '未知 UA' }}</span>
            </div>
            <NButton v-if="s.active && endpointAllowed('DELETE', '/api/admin/users/{uid}/sessions/{sessionId}')" size="small" quaternary type="error" @click="revokeSession(s.id)">吊销</NButton>
          </div>
        </div>
        <NEmpty v-else description="没有会话记录" />
        <div v-if="sessions.length > 0" class="admin-form-actions">
          <NButton v-if="endpointAllowed('POST', '/api/admin/users/{uid}/revoke-sessions')" quaternary type="error" @click="revokeAllSessions(sessionsUid)">吊销全部会话</NButton>
        </div>
      </template>
    </NModal>

    <!-- Token -->
    <NModal v-model:show="tokenVisible" preset="card" style="width: min(92%, 760px);" title="UserToken">
      <div v-if="tokenLoading" class="admin-modal-state"><NSpin /></div>
      <template v-else>
        <dl class="admin-detail-grid">
          <div><dt>状态</dt><dd>{{ tokenPrefix }}</dd></div>
          <div><dt>创建（UTC+8）</dt><dd><DateTimeText :value="tokenCreatedAt" /></dd></div>
          <div><dt>刷新（UTC+8）</dt><dd><DateTimeText :value="tokenRefreshedAt" /></dd></div>
          <div><dt>过期（UTC+8）</dt><dd><DateTimeText :value="tokenExpiresAt" empty="永不过期" /></dd></div>
          <div><dt>最近使用（UTC+8）</dt><dd><DateTimeText :value="tokenLastUsedAt" /></dd></div>
          <div><dt>最近 IP</dt><dd class="mono">{{ tokenLastIp || '—' }}</dd></div>
        </dl>
        <div class="admin-stack" style="margin-top: 12px;">
          <div v-for="u in tokenUsage" :key="u.id" class="admin-line-card">
            <div class="admin-line-main">
              <strong class="mono">{{ u.method }} {{ u.endpoint }}</strong>
              <span class="muted mono"><DateTimeText :value="u.occurredAt" /> · {{ u.ipAddress || '未知 IP' }}</span>
            </div>
          </div>
          <NEmpty v-if="tokenUsage.length === 0" description="暂无使用记录" />
        </div>
        <div class="admin-pagination">
          <span class="muted">共 {{ tokenTotal }} 条</span>
          <NButton size="small" quaternary :disabled="tokenPage <= 0" @click="tokenPrev">上一页</NButton>
          <span class="mono muted-2">{{ tokenPage + 1 }}</span>
          <NButton size="small" quaternary :disabled="(tokenPage + 1) * tokenPageSize >= tokenTotal" @click="tokenNext">下一页</NButton>
        </div>
        <div class="admin-form-actions">
          <NButton v-if="endpointAllowed('DELETE', '/api/admin/users/{uid}/token')" quaternary type="error" @click="revokeToken(tokenUid)">吊销 UserToken</NButton>
        </div>
      </template>
    </NModal>
  </section>
</template>

<style scoped>
.search-input {
  width: min(320px, 100%);
}

.tool-select {
  width: 140px;
}

.cell-stack {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.table-users .cell-ellipsis {
  display: block;
}
</style>
