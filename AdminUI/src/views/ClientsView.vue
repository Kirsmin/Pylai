<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import type { AdminClientItem } from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()
const dialog = useDialog()

const clients = ref<AdminClientItem[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 20

const cap = computed(() => authStore.capability('clients'))

function endpointAllowed(method: string, path: string) {
  return cap.value?.endpoints.some(e => e.method === method && e.path === path) ?? false
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({ skip: String((page.value - 1) * pageSize), take: String(pageSize) })
    const data = await authStore.request<{ success: boolean; total: number; items: AdminClientItem[] }>(
      `/api/clients?${params.toString()}`
    )
    clients.value = data?.items ?? []
    total.value = data?.total ?? 0
  } catch (err) { message.error(err instanceof Error ? err.message : '加载失败') }
  finally { loading.value = false }
}
onMounted(load)

// ── Client Type helpers ──────────────────────────────────────
const clientTypeOptions = [
  { label: 'Confidential', value: 'Confidential', desc: '服务端应用，需 Client Secret' },
  { label: 'Public', value: 'Public', desc: 'SPA/移动应用，使用 PKCE，无需 Secret' }
]

function typeTone(t: string) {
  if (t === 'Public') return 'warning'
  return 'info'
}

// ── Editor ───────────────────────────────────────────────────
const editorVisible = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)

interface ClientForm {
  clientId: string
  displayName: string
  clientSecret: string
  description: string
  homepageUrl: string
  isFajorCertified: boolean
  type: 'Confidential' | 'Public'
  scopes: string[]
  redirectUris: string[]
  postLogoutRedirectUris: string[]
  grantTypes: string[]
  permissions: string[]
}

const form = ref<ClientForm>({
  clientId: '', displayName: '', clientSecret: '', description: '', homepageUrl: '',
  isFajorCertified: false, type: 'Confidential',
  scopes: ['openid', 'profile:basic', 'profile:mail', 'profile:role', 'offline_access'],
  redirectUris: [], postLogoutRedirectUris: [],
  grantTypes: ['authorization_code', 'refresh_token'], permissions: []
})

// 根据类型自动调整 Secret 提示与校验
const secretPlaceholder = computed(() => {
  if (form.value.type === 'Public') return 'Public 类型无需 Secret'
  return '留空自动生成'
})
const secretDisabled = computed(() => form.value.type === 'Public' && editingId.value === null)

function openCreate() {
  editingId.value = null
  form.value = {
    clientId: '', displayName: '', clientSecret: '', description: '', homepageUrl: '',
    isFajorCertified: false, type: 'Confidential',
    scopes: ['openid', 'profile:basic', 'profile:mail', 'profile:role', 'offline_access'],
    redirectUris: [], postLogoutRedirectUris: [],
    grantTypes: ['authorization_code', 'refresh_token'], permissions: []
  }
  editorVisible.value = true
}

function openEdit(c: AdminClientItem) {
  editingId.value = c.id
  form.value = {
    clientId: c.clientId,
    displayName: c.displayName,
    clientSecret: '',
    description: c.description ?? '',
    homepageUrl: c.homepageUrl ?? '',
    isFajorCertified: c.isFajorCertified,
    type: (c.type === 'Public' ? 'Public' : 'Confidential') as 'Public' | 'Confidential',
    scopes: [...c.scopes],
    redirectUris: [...c.redirectUris],
    postLogoutRedirectUris: [...c.postLogoutRedirectUris],
    grantTypes: [...c.grantTypes],
    permissions: [...c.permissions]
  }
  editorVisible.value = true
}

// 表单校验
const formErrors = ref<Record<string, string>>({})

function validateForm(): boolean {
  const errs: Record<string, string> = {}
  if (!form.value.clientId.trim()) errs.clientId = 'Client ID 不能为空'
  else if (form.value.clientId.length > 128) errs.clientId = 'Client ID 不能超过 128 字符'

  if (!form.value.displayName.trim()) errs.displayName = '显示名称不能为空'

  if (form.value.type === 'Confidential' && editingId.value === null && !form.value.clientSecret.trim()) {
    errs.clientSecret = 'Confidential 类型必须提供 Client Secret'
  }

  if (!form.value.scopes.length) errs.scopes = '至少选择一个 Scope'
  if (!form.value.grantTypes.length) errs.grantTypes = '至少选择一个 Grant Type'

  // Redirect URI 校验
  for (const uri of form.value.redirectUris) {
    if (!isValidRedirectUri(uri)) {
      errs.redirectUris = `非法 URI: ${uri}`
      break
    }
  }
  for (const uri of form.value.postLogoutRedirectUris) {
    if (!isValidRedirectUri(uri)) {
      errs.postLogoutRedirectUris = `非法 URI: ${uri}`
      break
    }
  }

  formErrors.value = errs
  return Object.keys(errs).length === 0
}

function isValidRedirectUri(uri: string): boolean {
  if (!uri.trim()) return false
  try {
    const u = new URL(uri)
    if (u.protocol === 'https:') return true
    if (u.protocol === 'http:' && (u.hostname === 'localhost' || u.hostname === '127.0.0.1')) return true
    return false
  } catch { return false }
}

async function save() {
  if (!validateForm()) {
    message.error('请修正表单错误后再保存')
    return
  }

  saving.value = true
  try {
    const body: Record<string, unknown> = {
      clientId: form.value.clientId,
      displayName: form.value.displayName,
      description: form.value.description || undefined,
      homepageUrl: form.value.homepageUrl || undefined,
      isFajorCertified: form.value.isFajorCertified,
      type: form.value.type,
      scopes: form.value.scopes,
      redirectUris: form.value.redirectUris,
      postLogoutRedirectUris: form.value.postLogoutRedirectUris,
      grantTypes: form.value.grantTypes,
      permissions: form.value.permissions
    }

    // Public 类型创建时不传 secret；Confidential 类型传值（含空字符串时由后端处理）
    if (form.value.type === 'Confidential') {
      body.clientSecret = form.value.clientSecret || undefined
    }

    if (editingId.value === null) {
      await authStore.request('/api/clients', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      message.success('客户端已创建')
    } else {
      // 编辑时只传有值的字段
      const updateBody: Record<string, unknown> = {}
      if (form.value.displayName) updateBody.displayName = form.value.displayName
      if (form.value.clientSecret) updateBody.clientSecret = form.value.clientSecret
      if (form.value.description !== undefined) updateBody.description = form.value.description || null
      if (form.value.homepageUrl !== undefined) updateBody.homepageUrl = form.value.homepageUrl || null
      updateBody.isFajorCertified = form.value.isFajorCertified
      updateBody.scopes = form.value.scopes
      updateBody.redirectUris = form.value.redirectUris
      updateBody.postLogoutRedirectUris = form.value.postLogoutRedirectUris
      updateBody.grantTypes = form.value.grantTypes
      updateBody.permissions = form.value.permissions

      await authStore.request(`/api/clients/${encodeURIComponent(editingId.value)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updateBody)
      })
      message.success('客户端已更新')
    }
    editorVisible.value = false
    load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function toggleDisable(c: AdminClientItem) {
  try {
    await authStore.request(`/api/clients/${encodeURIComponent(c.id)}/${c.isDisabled ? 'enable' : 'disable'}`, { method: 'PATCH' })
    message.success(c.isDisabled ? '客户端已启用' : '客户端已禁用')
    load()
  } catch (err) { message.error(err instanceof Error ? err.message : '操作失败') }
}

function confirmDelete(c: AdminClientItem) {
  dialog.warning({
    title: '删除客户端',
    content: `确定删除 ${c.displayName || c.clientId}？此操作不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await authStore.request(`/api/clients/${encodeURIComponent(c.id)}`, { method: 'DELETE' })
        message.success('客户端已删除')
        load()
      } catch (err) { message.error(err instanceof Error ? err.message : '删除失败') }
    }
  })
}

// ── Logo ─────────────────────────────────────────────────────
const logoFile = ref<File | null>(null)
const logoUid = ref('')
const logoVisible = ref(false)
const logoUploading = ref(false)

function openLogo(c: AdminClientItem) { logoUid.value = c.id; logoFile.value = null; logoVisible.value = true }
async function uploadLogo() {
  if (!logoFile.value) return
  logoUploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', logoFile.value)
    await authStore.request(`/api/clients/${encodeURIComponent(logoUid.value)}/logo`, { method: 'PUT', body: fd })
    message.success('Logo 已上传')
    logoVisible.value = false
    load()
  } catch (err) { message.error(err instanceof Error ? err.message : '上传失败') }
  finally { logoUploading.value = false }
}
async function deleteLogo(c: AdminClientItem) {
  try {
    await authStore.request(`/api/clients/${encodeURIComponent(c.id)}/logo`, { method: 'DELETE' })
    message.success('Logo 已删除')
    load()
  } catch (err) { message.error(err instanceof Error ? err.message : '删除失败') }
}

// ── Detail Modal ─────────────────────────────────────────────
const detailVisible = ref(false)
const detailClient = ref<AdminClientItem | null>(null)

function openDetail(c: AdminClientItem) {
  detailClient.value = c
  detailVisible.value = true
}

// ── Array helpers ────────────────────────────────────────────
function arrayInput(v: string): string[] {
  return v.split(/[\n,]/).map(s => s.trim()).filter(Boolean)
}
function arrayOutput(v: string[] | undefined): string {
  return (v || []).join('\n')
}

// 预设 Scope 快捷选择
const presetScopes = [
  { label: 'openid', desc: 'OpenID Connect 必需' },
  { label: 'profile:basic', desc: '基础个人资料' },
  { label: 'profile:mail', desc: '邮箱地址' },
  { label: 'profile:role', desc: '用户组' },
  { label: 'offline_access', desc: 'Refresh Token' }
]

function toggleScope(scope: string) {
  const idx = form.value.scopes.indexOf(scope)
  if (idx >= 0) {
    if (scope !== 'openid') form.value.scopes.splice(idx, 1)
  } else {
    form.value.scopes.push(scope)
  }
}

// 监听类型变化，清空错误
watch(() => form.value.type, () => {
  if (form.value.type === 'Public') form.value.clientSecret = ''
  formErrors.value = {}
})
</script>

<template>
  <section class="admin-page">
    <PageHeader title="客户端管理" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary type="success" @click="load">刷新</NButton>
        <NButton v-if="endpointAllowed('POST','/api/clients')" type="success" ghost @click="openCreate">
          创建客户端
        </NButton>
      </template>
    </PageHeader>

    <!-- 客户端列表 -->
    <div class="admin-table-wrap">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="clients.length">
        <table class="admin-table">
          <thead>
            <tr>
              <th>客户端</th>
              <th>类型</th>
              <th>状态</th>
              <th>Scope</th>
              <th style="text-align:right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in clients" :key="c.id">
              <td>
                <div style="display:flex;align-items:center;gap:10px;">
                  <div v-if="c.hasLogo" class="client-logo">
                    <img :src="`/api/clients/${c.id}/logo`" alt="logo" />
                  </div>
                  <div v-else class="client-logo-placeholder">无</div>
                  <div style="display:flex;flex-direction:column;gap:2px;min-width:0;">
                    <span class="truncate" style="font-weight:600;">{{ c.displayName }}</span>
                    <span class="mono small muted">{{ c.clientId }}</span>
                  </div>
                </div>
              </td>
              <td>
                <AppBadge :tone="typeTone(c.type)">{{ c.type }}</AppBadge>
              </td>
              <td>
                <AppBadge :tone="c.isDisabled ? 'danger' : 'success'">
                  {{ c.isDisabled ? '禁用' : '正常' }}
                </AppBadge>
              </td>
              <td>
                <div style="display:flex;gap:4px;flex-wrap:wrap;">
                  <AppBadge v-for="s in c.scopes.slice(0, 3)" :key="s" tone="neutral" class="scope-badge">
                    {{ s }}
                  </AppBadge>
                  <span v-if="c.scopes.length > 3" class="small muted">+{{ c.scopes.length - 3 }}</span>
                </div>
              </td>
              <td style="text-align:right">
                <div style="display:inline-flex;gap:4px;flex-wrap:wrap;justify-content:flex-end;">
                  <NButton size="tiny" quaternary type="success" @click="openDetail(c)">详情</NButton>
                  <NButton v-if="endpointAllowed('PUT','/api/clients/{id}')" size="tiny" quaternary type="success"
                    @click="openEdit(c)">编辑</NButton>
                  <NButton size="tiny" quaternary @click="toggleDisable(c)">
                    {{ c.isDisabled ? '启用' : '禁用' }}
                  </NButton>
                  <NButton v-if="endpointAllowed('PUT','/api/clients/{id}/logo')" size="tiny" quaternary
                    @click="openLogo(c)">Logo</NButton>
                  <NButton v-if="c.hasLogo && endpointAllowed('DELETE','/api/clients/{id}/logo')" size="tiny"
                    quaternary type="error" @click="deleteLogo(c)">删Logo</NButton>
                  <NPopconfirm v-if="endpointAllowed('DELETE','/api/clients/{id}')" @positive-click="confirmDelete(c)">
                    <template #trigger>
                      <NButton size="tiny" quaternary type="error">删除</NButton>
                    </template>
                    <span style="white-space:nowrap">删除 {{ c.clientId }}？</span>
                  </NPopconfirm>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <AppPagination v-model:page="page" :page-size="pageSize" :total="total" unit="个" @update:page="load" />
      </template>
      <NEmpty v-else description="没有客户端" class="admin-empty" />
    </div>

    <!-- ── 创建/编辑 弹窗 ─────────────────────────────────────── -->
    <NModal v-model:show="editorVisible" preset="card"
      style="width:min(92%,640px);max-height:90vh;overflow:auto;"
      :title="editingId === null ? '创建客户端' : '编辑客户端'">
      <div class="client-form">
        <!-- 基础信息 -->
        <div class="form-section">
          <h4 class="section-title">基础信息</h4>

          <label class="form-field" :class="{ 'has-error': formErrors.clientId }">
            <span class="field-label required">Client ID</span>
            <input v-model="form.clientId" class="admin-input mono" :disabled="editingId !== null"
              placeholder="唯一标识，如 my-app" />
            <span v-if="formErrors.clientId" class="field-error">{{ formErrors.clientId }}</span>
          </label>

          <label class="form-field" :class="{ 'has-error': formErrors.displayName }">
            <span class="field-label required">显示名称</span>
            <input v-model="form.displayName" class="admin-input" placeholder="应用显示名称" />
            <span v-if="formErrors.displayName" class="field-error">{{ formErrors.displayName }}</span>
          </label>

          <!-- 类型选择 -->
          <div class="form-field">
            <span class="field-label required">客户端类型</span>
            <div class="type-selector">
              <div v-for="opt in clientTypeOptions" :key="opt.value" class="type-option"
                :class="{ active: form.type === opt.value }" @click="form.type = opt.value as 'Confidential' | 'Public'">
                <div class="type-option-header">
                  <span class="type-radio" :class="{ checked: form.type === opt.value }"></span>
                  <strong>{{ opt.label }}</strong>
                </div>
                <span class="type-option-desc">{{ opt.desc }}</span>
              </div>
            </div>
          </div>

          <!-- Secret -->
          <label v-if="editingId === null" class="form-field"
            :class="{ 'has-error': formErrors.clientSecret }">
            <span class="field-label">Client Secret</span>
            <input v-model="form.clientSecret" type="password" class="admin-input mono"
              :placeholder="secretPlaceholder" :disabled="secretDisabled" />
            <span v-if="form.type === 'Public'" class="field-hint">Public 类型使用 PKCE 验证，无需 Secret</span>
            <span v-else class="field-hint">Confidential 类型必须提供 Secret，或留空由后端自动生成</span>
            <span v-if="formErrors.clientSecret" class="field-error">{{ formErrors.clientSecret }}</span>
          </label>

          <label class="form-field">
            <span class="field-label">介绍</span>
            <input v-model="form.description" class="admin-input" placeholder="应用简介（可选）" />
          </label>

          <label class="form-field">
            <span class="field-label">主页</span>
            <input v-model="form.homepageUrl" class="admin-input" placeholder="https://example.com" />
          </label>

          <label class="form-field checkbox-field">
            <input v-model="form.isFajorCertified" type="checkbox" />
            <span>Fajor 认证</span>
            <span class="field-hint inline">标记为经过 Fajor 认证的可信应用</span>
          </label>
        </div>

        <!-- OAuth 配置 -->
        <div class="form-section">
          <h4 class="section-title">OAuth 配置</h4>

          <!-- Scopes -->
          <div class="form-field" :class="{ 'has-error': formErrors.scopes }">
            <span class="field-label required">Scopes</span>
            <div class="scope-chips">
              <button v-for="s in presetScopes" :key="s.label" type="button" class="scope-chip"
                :class="{ active: form.scopes.includes(s.label), required: s.label === 'openid' }"
                @click="toggleScope(s.label)">
                {{ s.label }}
                <span class="scope-chip-desc">{{ s.desc }}</span>
              </button>
            </div>
            <label class="field-label" style="margin-top:8px;">自定义 Scopes（每行一个）</label>
            <textarea :value="arrayOutput(form.scopes.filter(s => !presetScopes.some(p => p.label === s)))"
              class="admin-input mono" rows="2"
              @input="evt => {
                const custom = arrayInput((evt.target as HTMLTextAreaElement).value)
                const preset = form.scopes.filter(s => presetScopes.some(p => p.label === s))
                form.scopes = [...preset, ...custom.filter(c => !preset.includes(c))]
              }" />
            <span v-if="formErrors.scopes" class="field-error">{{ formErrors.scopes }}</span>
          </div>

          <!-- Redirect URIs -->
          <label class="form-field" :class="{ 'has-error': formErrors.redirectUris }">
            <span class="field-label required">Redirect URIs（每行一个）</span>
            <textarea :value="arrayOutput(form.redirectUris)" class="admin-input mono" rows="3"
              placeholder="https://your-domain/callback"
              @input="form.redirectUris = arrayInput(($event.target as HTMLTextAreaElement).value)" />
            <span class="field-hint">必须 https:// 开头，或 http://localhost</span>
            <span v-if="formErrors.redirectUris" class="field-error">{{ formErrors.redirectUris }}</span>
          </label>

          <!-- Post Logout URIs -->
          <label class="form-field" :class="{ 'has-error': formErrors.postLogoutRedirectUris }">
            <span class="field-label">Post Logout Redirect URIs（每行一个）</span>
            <textarea :value="arrayOutput(form.postLogoutRedirectUris)" class="admin-input mono" rows="2"
              placeholder="https://your-domain/"
              @input="form.postLogoutRedirectUris = arrayInput(($event.target as HTMLTextAreaElement).value)" />
            <span v-if="formErrors.postLogoutRedirectUris" class="field-error">{{ formErrors.postLogoutRedirectUris }}</span>
          </label>

          <!-- Grant Types -->
          <div class="form-field" :class="{ 'has-error': formErrors.grantTypes }">
            <span class="field-label required">Grant Types（每行一个）</span>
            <textarea :value="arrayOutput(form.grantTypes)" class="admin-input mono" rows="2"
              @input="form.grantTypes = arrayInput(($event.target as HTMLTextAreaElement).value)" />
            <span class="field-hint">常用: authorization_code, refresh_token, client_credentials</span>
            <span v-if="formErrors.grantTypes" class="field-error">{{ formErrors.grantTypes }}</span>
          </div>
        </div>

        <div style="display:flex;justify-content:flex-end;margin-top:8px;gap:8px;">
          <NButton quaternary @click="editorVisible = false">取消</NButton>
          <NButton type="success" ghost :loading="saving" @click="save">保存</NButton>
        </div>
      </div>
    </NModal>

    <!-- ── 详情弹窗 ───────────────────────────────────────────── -->
    <NModal v-model:show="detailVisible" preset="card" style="width:min(92%,600px)" title="客户端详情">
      <div v-if="detailClient" class="client-detail">
        <div class="detail-header">
          <div v-if="detailClient.hasLogo" class="client-logo-large">
            <img :src="`/api/clients/${detailClient.id}/logo`" alt="logo" />
          </div>
          <div v-else class="client-logo-large placeholder">{{ detailClient.displayName.charAt(0).toUpperCase() }}</div>
          <div class="detail-header-info">
            <h3>{{ detailClient.displayName }}</h3>
            <span class="mono muted">{{ detailClient.clientId }}</span>
            <div style="display:flex;gap:6px;margin-top:6px;">
              <AppBadge :tone="typeTone(detailClient.type)">{{ detailClient.type }}</AppBadge>
              <AppBadge :tone="detailClient.isDisabled ? 'danger' : 'success'">
                {{ detailClient.isDisabled ? '禁用' : '正常' }}
              </AppBadge>
              <AppBadge v-if="detailClient.isFajorCertified" tone="purple">Fajor 认证</AppBadge>
            </div>
          </div>
        </div>

        <dl class="admin-detail-grid" style="margin-top:16px;">
          <div v-if="detailClient.description">
            <dt>介绍</dt>
            <dd>{{ detailClient.description }}</dd>
          </div>
          <div v-if="detailClient.homepageUrl">
            <dt>主页</dt>
            <dd>
              <a :href="detailClient.homepageUrl" target="_blank" rel="noopener" class="detail-link">{{ detailClient.homepageUrl }}</a>
            </dd>
          </div>
          <div>
            <dt>Scopes</dt>
            <dd>
              <div style="display:flex;gap:4px;flex-wrap:wrap;">
                <AppBadge v-for="s in detailClient.scopes" :key="s" tone="neutral" class="scope-badge">{{ s }}</AppBadge>
              </div>
            </dd>
          </div>
          <div>
            <dt>Grant Types</dt>
            <dd class="mono">{{ detailClient.grantTypes.join(', ') }}</dd>
          </div>
          <div>
            <dt>Redirect URIs</dt>
            <dd class="mono small">{{ detailClient.redirectUris.join('\n') || '—' }}</dd>
          </div>
          <div>
            <dt>Post Logout URIs</dt>
            <dd class="mono small">{{ detailClient.postLogoutRedirectUris.join('\n') || '—' }}</dd>
          </div>
          <div>
            <dt>Permissions</dt>
            <dd class="mono small">{{ detailClient.permissions.join(', ') || '—' }}</dd>
          </div>
        </dl>
      </div>
    </NModal>

    <!-- ── Logo 弹窗 ──────────────────────────────────────────── -->
    <NModal v-model:show="logoVisible" preset="card" style="width:min(92%,400px)" title="上传 Logo">
      <div style="display:flex;flex-direction:column;gap:12px;">
        <input type="file" accept="image/svg+xml,image/png"
          @change="logoFile = ($event.target as HTMLInputElement).files?.[0] ?? null" />
        <p class="muted small">仅支持 SVG 和 PNG，最大 2MB</p>
        <div style="display:flex;justify-content:flex-end;">
          <NButton type="success" ghost :loading="logoUploading" :disabled="!logoFile" @click="uploadLogo">上传
          </NButton>
        </div>
      </div>
    </NModal>
  </section>
</template>

<style scoped>
/* 列表页 */
.client-logo {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  overflow: hidden;
  background: var(--surface);
  flex-shrink: 0;
}

.client-logo img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.client-logo-placeholder {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  font-size: 12px;
  flex-shrink: 0;
  background: var(--surface);
}

.scope-badge {
  font-size: 11px;
  padding: 1px 6px;
}

/* 表单 */
.client-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.section-title {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.form-field {
  display: block;
}

.form-field.has-error .admin-input {
  border-color: var(--danger);
  box-shadow: 0 0 0 3px var(--danger-soft);
}

.field-label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-tertiary);
  margin-bottom: 6px;
}

.field-label.required::after {
  content: ' *';
  color: var(--danger);
}

.field-error {
  display: block;
  font-size: 12px;
  color: var(--danger);
  margin-top: 4px;
}

.field-hint {
  display: block;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
}

.field-hint.inline {
  display: inline;
  margin-left: 6px;
}

/* 类型选择器 */
.type-selector {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.type-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 14px;
  border: 1.5px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-base);
  background: var(--surface);
}

.type-option:hover {
  border-color: var(--border-strong);
}

.type-option.active {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.type-option-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.type-option-header strong {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.type-option-desc {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-left: 26px;
}

.type-radio {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 2px solid var(--border-strong);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.type-radio.checked {
  border-color: var(--accent);
  background: var(--accent);
}

.type-radio.checked::after {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #fff;
}

/* Scope 快捷选择 */
.scope-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.scope-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border-radius: 99px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  font-family: var(--font-family-mono);
}

.scope-chip:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.scope-chip.active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.scope-chip.required {
  border-style: dashed;
}

.scope-chip-desc {
  font-family: var(--font-family);
  font-size: 11px;
  color: var(--text-tertiary);
}

.scope-chip.active .scope-chip-desc {
  color: var(--accent);
  opacity: 0.8;
}

/* Checkbox */
.checkbox-field {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
}

.checkbox-field input[type="checkbox"] {
  width: 18px;
  height: 18px;
  accent-color: var(--accent);
  cursor: pointer;
}

.checkbox-field span {
  font-size: 13px;
  color: var(--text-primary);
}

/* 详情 */
.client-detail {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.client-logo-large {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  overflow: hidden;
  background: var(--surface);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.client-logo-large img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.client-logo-large.placeholder {
  font-size: 22px;
  font-weight: 700;
  color: var(--accent);
  background: var(--accent-soft);
  border-color: var(--accent-ring);
}

.detail-header-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.detail-header-info h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.detail-link {
  color: var(--accent);
  text-decoration: none;
}

.detail-link:hover {
  text-decoration: underline;
}
</style>
