<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import DateTimeText from '@/components/DateTimeText.vue'
import type { AdminUserDetail, AdminUserListItem, AdminUserSession, AdminUserTokenUsageItem } from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()

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
function statusTone(s: string) {
  if (s.toLowerCase() === 'active') return 'success'
  if (s.toLowerCase() === 'banned') return 'danger'
  if (s.toLowerCase() === 'locked') return 'warning'
  return 'neutral'
}
function endpointAllowed(method: string, path: string) {
  return cap.value?.endpoints.some(e => e.method === method && e.path === path) ?? false
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      skip: String((page.value - 1) * pageSize), take: String(pageSize)
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
    message.error(err instanceof Error ? err.message : '加载失败')
  } finally { loading.value = false }
}
function searchUsers() { page.value = 1; load() }
function resetFilters() { search.value = ''; group.value = null; status.value = null; page.value = 1; load() }
onMounted(load)

// Detail
const detailVisible = ref(false)
const detail = ref<AdminUserDetail | null>(null)
const detailLoading = ref(false)
async function openDetail(uid: string) {
  detailVisible.value = true; detailLoading.value = true; detail.value = null
  try {
    const data = await authStore.request<{ success: boolean; user: AdminUserDetail | null }>(
      `/api/admin/users/${encodeURIComponent(uid)}`
    )
    detail.value = data?.user ?? null
  } catch (err) { message.error(err instanceof Error ? err.message : '加载详情失败'); detailVisible.value = false }
  finally { detailLoading.value = false }
}

// Edit
const editVisible = ref(false)
const editUid = ref('')
const editSaving = ref(false)
const editForm = ref({ displayName: '', email: '', status: 'Active', group: 'normal' })
function openEdit(user: AdminUserListItem) {
  editUid.value = user.uid
  editForm.value = { displayName: user.displayName ?? '', email: user.email ?? '', status: user.status, group: user.group }
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
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    })
    message.success('用户已更新')
    editVisible.value = false; load()
  } catch (err) { message.error(err instanceof Error ? err.message : '更新失败') }
  finally { editSaving.value = false }
}

// Status toggle
const statusSavingUid = ref('')
async function setStatus(user: AdminUserListItem, next: string) {
  statusSavingUid.value = user.uid
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(user.uid)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: next })
    })
    message.success('状态已更新'); load()
    if (detail.value?.uid === user.uid) openDetail(user.uid)
  } catch (err) { message.error(err instanceof Error ? err.message : '操作失败') }
  finally { statusSavingUid.value = '' }
}

// Password
const passwordVisible = ref(false)
const passwordUid = ref('')
const passwordSaving = ref(false)
const newPassword = ref('')
function openPassword(user: AdminUserListItem) { passwordUid.value = user.uid; newPassword.value = ''; passwordVisible.value = true }
async function savePassword() {
  if (!newPassword.value) return
  passwordSaving.value = true
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(passwordUid.value)}/reset-password`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ newPassword: newPassword.value })
    })
    message.success('密码已重置'); passwordVisible.value = false; newPassword.value = ''
  } catch (err) { message.error(err instanceof Error ? err.message : '重置失败') }
  finally { passwordSaving.value = false }
}

// Sessions
const sessionsVisible = ref(false)
const sessionsUid = ref('')
const sessionsLoading = ref(false)
const sessions = ref<AdminUserSession[]>([])
async function loadSessions(uid: string) {
  sessionsLoading.value = true; sessions.value = []
  try {
    const data = await authStore.request<{ success: boolean; sessions: AdminUserSession[] }>(
      `/api/admin/users/${encodeURIComponent(uid)}/sessions`
    )
    sessions.value = data?.sessions ?? []
  } catch (err) { message.error(err instanceof Error ? err.message : '加载会话失败') }
  finally { sessionsLoading.value = false }
}
function openSessions(user: AdminUserListItem) { sessionsUid.value = user.uid; sessionsVisible.value = true; loadSessions(user.uid) }
async function revokeSession(id: number) {
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(sessionsUid.value)}/sessions/${id}`, { method: 'DELETE' })
    message.success('会话已吊销'); loadSessions(sessionsUid.value)
  } catch (err) { message.error(err instanceof Error ? err.message : '吊销失败') }
}
async function revokeAllSessions(uid: string) {
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(uid)}/revoke-sessions`, { method: 'POST' })
    message.success('全部会话已吊销'); if (sessionsVisible.value) loadSessions(uid)
  } catch (err) { message.error(err instanceof Error ? err.message : '吊销失败') }
}

// Token
const tokenVisible = ref(false)
const tokenUid = ref('')
const tokenLoading = ref(false)
const tokenInfo = ref<Partial<NonNullable<AdminUserDetail['token']>>>({})
const tokenUsage = ref<AdminUserTokenUsageItem[]>([])
const tokenPage = ref(0)
const tokenPageSize = 20
const tokenTotal = ref(0)
async function loadToken(uid: string, skip: number) {
  tokenLoading.value = true
  try {
    const data = await authStore.request<{
      success: boolean; exists: boolean; tokenPrefix?: string | null;
      createdAt?: string | null; refreshedAt?: string | null; expiresAt?: string | null;
      lastUsedAt?: string | null; lastIpAddress?: string | null; totalUsage?: number; usage?: AdminUserTokenUsageItem[]
    }>(`/api/admin/users/${encodeURIComponent(uid)}/token?skip=${skip}&take=${tokenPageSize}`)
    tokenInfo.value = data ?? {}
    tokenUsage.value = data?.usage ?? []
    tokenTotal.value = data?.totalUsage ?? 0
    tokenPage.value = Math.floor(skip / tokenPageSize)
  } catch (err) { message.error(err instanceof Error ? err.message : '加载失败') }
  finally { tokenLoading.value = false }
}
function openToken(user: AdminUserListItem) { tokenUid.value = user.uid; tokenVisible.value = true; loadToken(user.uid, 0) }
async function revokeToken(uid: string) {
  try {
    const data = await authStore.request<{ success: boolean; revoked: boolean }>(
      `/api/admin/users/${encodeURIComponent(uid)}/token`, { method: 'DELETE' }
    )
    message.success(data?.revoked === false ? '无 Token' : 'Token 已吊销')
    if (tokenVisible.value) loadToken(uid, 0)
    if (detailVisible.value && detail.value?.uid === uid) openDetail(uid)
  } catch (err) { message.error(err instanceof Error ? err.message : '吊销失败') }
}

// Delete（二级界面：先选择软/硬删除，再确认执行）
const deleteVisible = ref(false)
const deleteStep = ref<1 | 2>(1)
const deleteTarget = ref<AdminUserListItem | null>(null)
const deleteMode = ref<'soft' | 'hard'>('soft')
const deleteSaving = ref(false)
const canHardDelete = computed(() => endpointAllowed('DELETE', '/api/admin/users/{uid}/hard'))
const targetDeleted = computed(() => (deleteTarget.value?.status ?? '').toLowerCase() === 'deleted')

function openDelete(user: AdminUserListItem) {
  deleteTarget.value = user
  deleteMode.value = 'soft'
  deleteStep.value = 1
  deleteVisible.value = true
}
async function confirmDelete() {
  const user = deleteTarget.value
  if (!user) return
  deleteSaving.value = true
  try {
    const path = deleteMode.value === 'hard'
      ? `/api/admin/users/${encodeURIComponent(user.uid)}/hard`
      : `/api/admin/users/${encodeURIComponent(user.uid)}`
    // 硬删除需要 MFA（TOTP/Passkey）：后端返回 mfa_step_up_required 时由全局 Step-up 弹窗接管并重放
    await authStore.request(path, { method: 'DELETE' })
    message.success(deleteMode.value === 'hard' ? `用户 ${user.name} 已硬删除，用户名与邮箱已释放` : `用户 ${user.name} 已软删除，可随时重新启用`)
    deleteVisible.value = false
    if (detailVisible.value) detailVisible.value = false
    load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '删除失败')
  } finally { deleteSaving.value = false }
}

function moreOptions(user: AdminUserListItem) {
  const opts: Array<{ label: string; key: string }> = []
  if (endpointAllowed('POST', '/api/admin/users/{uid}/reset-password')) opts.push({ label: '重置密码', key: 'password' })
  if (endpointAllowed('GET', '/api/admin/users/{uid}/sessions')) opts.push({ label: '会话', key: 'sessions' })
  if (endpointAllowed('GET', '/api/admin/users/{uid}/token')) opts.push({ label: 'Token', key: 'token' })
  if (endpointAllowed('DELETE', '/api/admin/users/{uid}')) opts.push({ label: '删除用户', key: 'delete' })
  return opts
}
function handleMore(key: string | number, user: AdminUserListItem) {
  const a = String(key)
  if (a === 'password') openPassword(user)
  else if (a === 'sessions') openSessions(user)
  else if (a === 'token') openToken(user)
  else if (a === 'delete') openDelete(user)
}
</script>

<template>
  <section class="admin-page">
    <PageHeader title="用户管理" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary @click="load">刷新</NButton>
      </template>
    </PageHeader>

    <div class="admin-filter-panel">
      <div class="user-filter-grid">
        <div class="admin-filter-field user-search-filter">
          <label>用户</label>
          <NInput v-model:value="search" placeholder="用户名、邮箱或显示名" clearable @keyup.enter="searchUsers" />
        </div>
        <div v-if="targetGroups.length" class="admin-filter-field">
          <label>用户组</label>
          <NSelect v-model:value="group" placeholder="全部用户组" clearable :options="groupOptions" />
        </div>
        <div v-if="canEditStatus" class="admin-filter-field">
          <label>状态</label>
          <NSelect v-model:value="status" placeholder="全部状态" clearable :options="statusOptions" />
        </div>
      </div>
      <div class="admin-filter-actions">
        <NButton quaternary @click="resetFilters">清空筛选</NButton>
        <NButton type="primary" :loading="loading" @click="searchUsers">查询</NButton>
      </div>
    </div>

    <div class="admin-context-strip">
      <span>当前条件下共 <strong>{{ total }}</strong> 个用户</span>
      <span class="muted">可操作用户组与字段以服务端 capability 为准。</span>
    </div>

    <div class="admin-table-wrap">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="users.length">
        <table class="admin-table">
          <thead>
            <tr>
              <th>用户</th><th>邮箱</th><th>组</th><th>状态</th><th>最近登录</th><th style="text-align:right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.uid">
              <td>
                <div class="user-cell">
                  <span class="truncate cell-primary">{{ u.displayName || u.name }}</span>
                  <span class="mono small muted">{{ u.name }}</span>
                </div>
              </td>
              <td><span class="truncate muted">{{ u.email || '—' }}</span></td>
              <td><AppBadge :tone="groupTone(u.group)">{{ u.group }}</AppBadge></td>
              <td><AppBadge :tone="statusTone(u.status)">{{ u.status }}</AppBadge></td>
              <td><DateTimeText :value="u.lastLoginAt" /></td>
              <td style="text-align:right">
                <div class="user-actions">
                  <NButton v-if="endpointAllowed('GET','/api/admin/users/{uid}')" size="tiny" quaternary @click="openDetail(u.uid)">详情</NButton>
                  <NButton v-if="endpointAllowed('PATCH','/api/admin/users/{uid}')" size="tiny" quaternary @click="openEdit(u)">编辑</NButton>
                  <template v-if="canEditStatus && endpointAllowed('PATCH','/api/admin/users/{uid}')">
                    <NPopconfirm v-if="u.status.toLowerCase()==='active'" @positive-click="setStatus(u,'Banned')">
                      <template #trigger><NButton size="tiny" quaternary type="warning" :loading="statusSavingUid===u.uid">封禁</NButton></template>
                      <span style="white-space:nowrap">封禁 {{ u.name }}？</span>
                    </NPopconfirm>
                    <NPopconfirm v-if="u.status.toLowerCase()==='active'" @positive-click="setStatus(u,'Locked')">
                      <template #trigger><NButton size="tiny" quaternary type="warning" :loading="statusSavingUid===u.uid">锁定</NButton></template>
                      <span style="white-space:nowrap">锁定 {{ u.name }}？</span>
                    </NPopconfirm>
                    <NPopconfirm v-if="u.status.toLowerCase()!=='active'" @positive-click="setStatus(u,'Active')">
                      <template #trigger><NButton size="tiny" quaternary type="primary" :loading="statusSavingUid===u.uid">启用</NButton></template>
                      <span style="white-space:nowrap">启用 {{ u.name }}？</span>
                    </NPopconfirm>
                  </template>
                  <NDropdown v-if="moreOptions(u).length" trigger="click" :options="moreOptions(u)" @select="(k: string | number) => handleMore(k,u)">
                    <NButton size="tiny" quaternary>更多</NButton>
                  </NDropdown>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <AppPagination v-model:page="page" :page-size="pageSize" :total="total" unit="人" @update:page="load" />
      </template>
      <NEmpty v-else description="没有符合条件的用户" class="admin-empty" />
    </div>

    <!-- Detail -->
    <NModal v-model:show="detailVisible" preset="card" style="width:min(92%,760px)" title="用户详情">
      <div v-if="detailLoading" class="admin-empty"><NSpin /></div>
      <template v-else-if="detail">
        <dl class="admin-detail-grid">
          <div><dt>UID</dt><dd class="mono">{{ detail.uid }}</dd></div>
          <div><dt>登录名</dt><dd class="mono">{{ detail.name }}</dd></div>
          <div><dt>显示名</dt><dd>{{ detail.displayName||'—' }}</dd></div>
          <div><dt>邮箱</dt><dd>{{ detail.email||'—' }}</dd></div>
          <div><dt>用户组</dt><dd><AppBadge :tone="groupTone(detail.group)">{{ detail.group }}</AppBadge></dd></div>
          <div><dt>状态</dt><dd><AppBadge :tone="statusTone(detail.status)">{{ detail.status }}</AppBadge></dd></div>
          <div><dt>注册时间</dt><dd><DateTimeText :value="detail.registerTime" /></dd></div>
          <div><dt>最近登录</dt><dd><DateTimeText :value="detail.lastLoginAt" /></dd></div>
          <div><dt>锁定到期</dt><dd><DateTimeText :value="detail.lockoutEnd" empty="未锁定" /></dd></div>
          <div><dt>失败次数</dt><dd>{{ detail.accessFailedCount }}</dd></div>
          <div><dt>活跃会话</dt><dd>{{ detail.activeSessions }}</dd></div>
          <div>
            <dt>外部登录</dt>
            <dd v-if="!detail.externalLogins.length">无</dd>
            <dd v-for="login in detail.externalLogins" :key="login.provider" class="mono small">
              {{ login.providerDisplayName||login.provider }} · <DateTimeText :value="login.boundAt" />
            </dd>
          </div>
        </dl>
        <div class="modal-action-row">
          <NButton v-if="endpointAllowed('POST','/api/admin/users/{uid}/revoke-sessions')" quaternary type="warning" @click="revokeAllSessions(detail.uid)">吊销全部会话</NButton>
          <NButton v-if="endpointAllowed('DELETE','/api/admin/users/{uid}/token')" quaternary type="error" @click="revokeToken(detail.uid)">吊销 UserToken</NButton>
        </div>
      </template>
    </NModal>

    <!-- Edit -->
    <NModal v-model:show="editVisible" preset="card" style="width:min(calc(100vw - 24px),500px)" title="编辑用户">
      <div class="admin-form-stack">
        <label class="admin-field">
          <span class="admin-field-label">显示名</span>
          <NInput v-model:value="editForm.displayName" placeholder="显示名称" />
        </label>
        <label class="admin-field">
          <span class="admin-field-label">邮箱</span>
          <NInput v-model:value="editForm.email" placeholder="user@example.com" />
        </label>
        <label v-if="canEditStatus" class="admin-field">
          <span class="admin-field-label">状态</span>
          <NSelect v-model:value="editForm.status" :options="statusOptions" />
        </label>
        <label v-if="canEditGroup" class="admin-field">
          <span class="admin-field-label">用户组</span>
          <NSelect v-model:value="editForm.group" :options="groupOptions" />
        </label>
        <div class="modal-actions">
          <NButton quaternary @click="editVisible = false">取消</NButton>
          <NButton type="primary" :loading="editSaving" @click="saveEdit">保存</NButton>
        </div>
      </div>
    </NModal>

    <!-- Password -->
    <NModal v-model:show="passwordVisible" preset="card" style="width:min(calc(100vw - 24px),420px)" title="重置密码">
      <div class="admin-form-stack">
        <label class="admin-field">
          <span class="admin-field-label">新密码</span>
          <NInput v-model:value="newPassword" type="password" show-password-on="click" placeholder="输入新密码" />
        </label>
        <p class="muted small modal-note">重置成功后，该用户全部会话将被吊销。</p>
        <div class="modal-actions">
          <NButton quaternary @click="passwordVisible = false">取消</NButton>
          <NButton type="primary" :loading="passwordSaving" :disabled="!newPassword" @click="savePassword">重置密码</NButton>
        </div>
      </div>
    </NModal>

    <!-- Sessions -->
    <NModal v-model:show="sessionsVisible" preset="card" style="width:min(92%,720px)" title="用户会话">
      <div v-if="sessionsLoading" class="admin-empty"><NSpin /></div>
      <template v-else>
        <div v-if="sessions.length" style="display:flex;flex-direction:column;gap:8px;">
          <div v-for="s in sessions" :key="s.id" class="admin-line-card">
            <div style="display:flex;flex-direction:column;gap:2px;min-width:0;">
              <strong :class="{muted:!s.active}">#{{ s.id }} {{ s.active?'活跃':'已吊销' }}</strong>
              <span class="mono small muted"><DateTimeText :value="s.createdAt" /> → <DateTimeText :value="s.expiresAt" /></span>
              <span class="small muted">{{ s.ipAddress||'未知 IP' }} · {{ s.userAgent||'未知 UA' }}</span>
            </div>
            <NButton v-if="s.active && endpointAllowed('DELETE','/api/admin/users/{uid}/sessions/{sessionId}')" size="small" quaternary type="error" @click="revokeSession(s.id)">吊销</NButton>
          </div>
        </div>
        <NEmpty v-else description="没有会话记录" />
        <div v-if="sessions.length" style="margin-top:12px;">
          <NButton v-if="endpointAllowed('POST','/api/admin/users/{uid}/revoke-sessions')" quaternary type="error" @click="revokeAllSessions(sessionsUid)">吊销全部会话</NButton>
        </div>
      </template>
    </NModal>

    <!-- Token -->
    <NModal v-model:show="tokenVisible" preset="card" style="width:min(92%,760px)" title="UserToken">
      <div v-if="tokenLoading" class="admin-empty"><NSpin /></div>
      <template v-else>
        <dl class="admin-detail-grid">
          <div><dt>状态</dt><dd class="mono">{{ tokenInfo.exists ? (tokenInfo.tokenPrefix||'—') : '未创建' }}</dd></div>
          <div><dt>创建</dt><dd><DateTimeText :value="tokenInfo.createdAt" /></dd></div>
          <div><dt>刷新</dt><dd><DateTimeText :value="tokenInfo.refreshedAt" /></dd></div>
          <div><dt>过期</dt><dd><DateTimeText :value="tokenInfo.expiresAt" empty="永不过期" /></dd></div>
          <div><dt>最近使用</dt><dd><DateTimeText :value="tokenInfo.lastUsedAt" /></dd></div>
          <div><dt>最近 IP</dt><dd class="mono">{{ tokenInfo.lastIpAddress||'—' }}</dd></div>
        </dl>
        <div v-if="tokenUsage.length" style="display:flex;flex-direction:column;gap:6px;margin-top:14px;">
          <div v-for="u in tokenUsage" :key="u.id" class="admin-line-card">
            <div style="display:flex;flex-direction:column;gap:2px;">
              <strong class="mono small">{{ u.method }} {{ u.endpoint }}</strong>
              <span class="mono small muted"><DateTimeText :value="u.occurredAt" /> · {{ u.ipAddress||'未知 IP' }}</span>
            </div>
          </div>
        </div>
        <NEmpty v-else-if="tokenInfo.exists" description="暂无使用记录" style="margin-top:12px;" />
        <div class="admin-pagination">
          <span class="muted small">共 {{ tokenTotal }} 条</span>
          <div style="display:flex;gap:4px;">
            <button class="pg-btn" :disabled="tokenPage<=0" @click="loadToken(tokenUid,(tokenPage-1)*tokenPageSize)">上一页</button>
            <button class="pg-btn" :disabled="(tokenPage+1)*tokenPageSize>=tokenTotal" @click="loadToken(tokenUid,(tokenPage+1)*tokenPageSize)">下一页</button>
          </div>
        </div>
        <div style="margin-top:12px;">
          <NButton v-if="endpointAllowed('DELETE','/api/admin/users/{uid}/token')" quaternary type="error" @click="revokeToken(tokenUid)">吊销 UserToken</NButton>
        </div>
      </template>
    </NModal>

    <!-- Delete（二级界面：选择删除方式 → 确认执行） -->
    <NModal
      v-model:show="deleteVisible"
      preset="card"
      style="width:min(calc(100vw - 24px),540px)"
      :title="deleteStep === 1 ? '删除用户' : (deleteMode === 'hard' ? '确认硬删除' : '确认软删除')"
    >
      <div v-if="deleteTarget" class="admin-form-stack">
        <div class="admin-line-card" style="display:flex;flex-direction:column;gap:2px;">
          <strong>{{ deleteTarget.displayName || deleteTarget.name }}</strong>
          <span class="mono small muted">{{ deleteTarget.name }}<template v-if="deleteTarget.email"> · {{ deleteTarget.email }}</template></span>
        </div>

        <template v-if="deleteStep === 1">
          <NRadioGroup v-model:value="deleteMode" style="display:flex;flex-direction:column;gap:12px;">
            <NRadio value="soft" :disabled="targetDeleted">
              <div><strong>软删除（可恢复）</strong></div>
              <div class="muted small">标记为 Deleted 并吊销全部会话与 Token；之后可随时「启用」恢复。无需 MFA 验证。</div>
            </NRadio>
            <NRadio v-if="canHardDelete" value="hard">
              <div><strong>硬删除（不可恢复）</strong></div>
              <div class="muted small">物理删除账号全部数据，无法恢复；用户名与邮箱立即释放，可被其他人注册。需要 MFA（TOTP/Passkey）验证。</div>
            </NRadio>
          </NRadioGroup>
          <p v-if="targetDeleted" class="muted small modal-note">该账号已处于软删除状态：可「启用」恢复，或直接硬删除以彻底释放用户名与邮箱。</p>
          <div class="modal-actions">
            <NButton quaternary @click="deleteVisible = false">取消</NButton>
            <NButton type="primary" :disabled="targetDeleted && deleteMode === 'soft'" @click="deleteStep = 2">下一步</NButton>
          </div>
        </template>

        <template v-else>
          <p v-if="deleteMode === 'soft'" class="modal-note">
            确认软删除 <strong>{{ deleteTarget.name }}</strong>？其全部会话与 Token 将被吊销，之后可随时重新「启用」。
          </p>
          <div v-else class="delete-hard-warning">
            <p><strong>此操作不可恢复。</strong></p>
            <p>账号 <strong>{{ deleteTarget.name }}</strong>（{{ deleteTarget.email || '无邮箱' }}）的全部数据——会话、UserToken、MFA 设置、外部登录绑定与 OAuth 授权——将被物理删除，其用户名与邮箱会立即释放，可被其他人注册。</p>
            <p class="muted small">点击确认后将要求完成 MFA（TOTP/Passkey）验证。</p>
          </div>
          <div class="modal-actions">
            <NButton quaternary :disabled="deleteSaving" @click="deleteStep = 1">返回</NButton>
            <NButton :type="deleteMode === 'hard' ? 'error' : 'warning'" :loading="deleteSaving" @click="confirmDelete">
              {{ deleteMode === 'hard' ? '确认硬删除' : '确认软删除' }}
            </NButton>
          </div>
        </template>
      </div>
    </NModal>
  </section>
</template>

<style scoped>
.user-filter-grid { display: grid; grid-template-columns: minmax(260px, 2fr) minmax(150px, .7fr) minmax(170px, .8fr); gap: 10px 12px; align-items: end; }
.user-cell { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.user-actions { display: inline-flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
.modal-action-row { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
.modal-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; margin-top: 2px; }
.modal-note { margin: 0; }
.delete-hard-warning { border: 1px solid rgba(208, 48, 80, .35); background: rgba(208, 48, 80, .08); border-radius: 6px; padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; }
.delete-hard-warning p { margin: 0; }
@media (max-width: 780px) { .user-filter-grid { grid-template-columns: 1fr 1fr; } .user-search-filter { grid-column: 1 / -1; } }
@media (max-width: 520px) { .user-filter-grid { grid-template-columns: 1fr; } .user-search-filter { grid-column: auto; } }
</style>
