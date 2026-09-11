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
  return cap.value?.endpoints.some((e) => e.method === method && e.path === path) ?? false
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      skip: String((page.value - 1) * pageSize),
      take: String(pageSize)
    })
    const data = await authStore.request<{ total: number; items: AdminClientItem[] }>(
      `/api/clients?${params.toString()}`
    )
    clients.value = data?.items ?? []
    total.value = data?.total ?? 0
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载客户端失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)

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

const presetScopes = [
  { value: 'openid', label: 'openid', desc: 'OpenID Connect 标识' },
  { value: 'profile:basic', label: 'profile:basic', desc: '基础资料' },
  { value: 'profile:mail', label: 'profile:mail', desc: '邮箱' },
  { value: 'profile:role', label: 'profile:role', desc: '用户组' },
  { value: 'offline_access', label: 'offline_access', desc: 'Refresh Token' }
]

const presetGrantTypes = [
  { value: 'authorization_code', label: 'Authorization Code', desc: '网页登录 / OIDC 推荐' },
  { value: 'refresh_token', label: 'Refresh Token', desc: '刷新访问令牌' },
  { value: 'client_credentials', label: 'Client Credentials', desc: '服务到服务，仅 Confidential' }
]

function defaultForm(): ClientForm {
  return {
    clientId: '',
    displayName: '',
    clientSecret: '',
    description: '',
    homepageUrl: '',
    isFajorCertified: false,
    type: 'Confidential',
    scopes: ['openid', 'profile:basic', 'profile:mail', 'profile:role', 'offline_access'],
    redirectUris: [],
    postLogoutRedirectUris: [],
    grantTypes: ['authorization_code', 'refresh_token'],
    permissions: []
  }
}

const editorVisible = ref(false)
const editorStep = ref(1)
const editingId = ref<string | null>(null)
const saving = ref(false)
const form = ref<ClientForm>(defaultForm())
const formErrors = ref<Record<string, string>>({})
const secretVisible = ref(false)

const isEditing = computed(() => editingId.value !== null)
const editorTitle = computed(() => isEditing.value ? '编辑 OAuth2 客户端' : '添加 OAuth2 客户端')
const usesAuthorizationCode = computed(() => form.value.grantTypes.includes('authorization_code'))

function openCreate() {
  editingId.value = null
  editorStep.value = 1
  formErrors.value = {}
  secretVisible.value = false
  form.value = defaultForm()
  editorVisible.value = true
}

function openEdit(client: AdminClientItem) {
  editingId.value = client.id
  editorStep.value = 1
  formErrors.value = {}
  secretVisible.value = false
  form.value = {
    clientId: client.clientId,
    displayName: client.displayName,
    clientSecret: '',
    description: client.description ?? '',
    homepageUrl: client.homepageUrl ?? '',
    isFajorCertified: client.isFajorCertified,
    type: normalizeClientType(client.type),
    scopes: [...client.scopes],
    redirectUris: [...client.redirectUris],
    postLogoutRedirectUris: [...client.postLogoutRedirectUris],
    grantTypes: [...client.grantTypes],
    permissions: [...client.permissions]
  }
  editorVisible.value = true
}

function setClientType(type: 'Confidential' | 'Public') {
  if (isEditing.value) return
  form.value.type = type
}

watch(() => form.value.type, (type) => {
  if (type === 'Public') {
    form.value.clientSecret = ''
    form.value.grantTypes = form.value.grantTypes.filter((value) => value !== 'client_credentials')
  }
  formErrors.value = {}
})

watch(editorVisible, (visible) => {
  if (visible) return
  form.value.clientSecret = ''
  secretVisible.value = false
  formErrors.value = {}
  editorStep.value = 1
})

function generateSecret() {
  const bytes = new Uint8Array(32)
  window.crypto.getRandomValues(bytes)
  const raw = String.fromCharCode(...bytes)
  form.value.clientSecret = btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
  secretVisible.value = true
  delete formErrors.value.clientSecret
}

async function copySecret() {
  if (!form.value.clientSecret) return
  try {
    await navigator.clipboard.writeText(form.value.clientSecret)
    message.success('Client Secret 已复制')
  } catch {
    message.warning('无法访问剪贴板，请手动复制 Client Secret')
  }
}

function isValidHomepage(value: string) {
  if (!value.trim()) return true
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:'
  } catch {
    return false
  }
}

function isLoopbackHost(hostname: string) {
  const host = hostname.toLowerCase()
  if (host === 'localhost' || host === '127.0.0.1' || host === '[::1]') return true
  if (/^127(?:\.\d{1,3}){3}$/.test(host)) return true
  return false
}

function isValidRedirectUri(value: string) {
  try {
    const url = new URL(value)
    if (!url.hostname) return false
    if (url.protocol === 'https:') return true
    return url.protocol === 'http:' && isLoopbackHost(url.hostname)
  } catch {
    return false
  }
}

function validateStep(step: number): boolean {
  const errors: Record<string, string> = { ...formErrors.value }

  if (step === 1) {
    delete errors.clientId
    delete errors.displayName
    delete errors.clientSecret
    delete errors.homepageUrl

    const clientId = form.value.clientId.trim()
    if (!clientId) errors.clientId = 'Client ID 不能为空'
    else if (clientId.length > 128) errors.clientId = 'Client ID 不能超过 128 个字符'

    if (!form.value.displayName.trim()) errors.displayName = '显示名称不能为空'

    if (!isEditing.value && form.value.type === 'Confidential' && !form.value.clientSecret.trim()) {
      errors.clientSecret = 'Confidential 客户端需要 Client Secret；可使用右侧按钮生成'
    }

    if (!isValidHomepage(form.value.homepageUrl)) {
      errors.homepageUrl = '主页地址必须是完整的 http:// 或 https:// URL'
    }
  }

  if (step === 2) {
    delete errors.scopes
    delete errors.grantTypes
    delete errors.redirectUris
    delete errors.postLogoutRedirectUris

    if (!form.value.scopes.length) errors.scopes = '至少需要一个 Scope'
    if (!form.value.grantTypes.length) errors.grantTypes = '至少需要一个 Grant Type'
    else if (form.value.type === 'Public' && form.value.grantTypes.includes('client_credentials')) {
      errors.grantTypes = 'Public 客户端不能使用 Client Credentials'
    }

    const invalidRedirect = form.value.redirectUris.find((uri) => !isValidRedirectUri(uri))
    if (invalidRedirect) errors.redirectUris = `非法 Redirect URI：${invalidRedirect}`

    const invalidLogout = form.value.postLogoutRedirectUris.find((uri) => !isValidRedirectUri(uri))
    if (invalidLogout) errors.postLogoutRedirectUris = `非法 Post Logout URI：${invalidLogout}`
  }

  formErrors.value = errors
  const keys = step === 1
    ? ['clientId', 'displayName', 'clientSecret', 'homepageUrl']
    : ['scopes', 'grantTypes', 'redirectUris', 'postLogoutRedirectUris']
  return !keys.some((key) => Boolean(errors[key]))
}

function nextStep() {
  if (!validateStep(editorStep.value)) {
    message.error('请先修正当前步骤中的配置')
    return
  }
  editorStep.value = Math.min(3, editorStep.value + 1)
}

function previousStep() {
  editorStep.value = Math.max(1, editorStep.value - 1)
}

function splitValues(value: string): string[] {
  return Array.from(new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean)))
}

function joinValues(value: string[]) {
  return value.join('\n')
}

function toggleScope(scope: string) {
  const index = form.value.scopes.indexOf(scope)
  if (index >= 0) form.value.scopes.splice(index, 1)
  else form.value.scopes.push(scope)
  delete formErrors.value.scopes
}

function toggleGrantType(grantType: string) {
  if (grantType === 'client_credentials' && form.value.type === 'Public') return
  const index = form.value.grantTypes.indexOf(grantType)
  if (index >= 0) form.value.grantTypes.splice(index, 1)
  else form.value.grantTypes.push(grantType)
  delete formErrors.value.grantTypes
}

async function save() {
  const basicOk = validateStep(1)
  const oauthOk = validateStep(2)
  if (!basicOk || !oauthOk) {
    editorStep.value = basicOk ? 2 : 1
    message.error('请修正配置后再保存')
    return
  }

  saving.value = true
  try {
    if (!isEditing.value) {
      const body = {
        clientId: form.value.clientId.trim(),
        displayName: form.value.displayName.trim(),
        clientSecret: form.value.type === 'Confidential' ? form.value.clientSecret : '',
        description: form.value.description.trim(),
        homepageUrl: form.value.homepageUrl.trim(),
        isFajorCertified: form.value.isFajorCertified,
        type: form.value.type,
        scopes: form.value.scopes,
        redirectUris: form.value.redirectUris,
        postLogoutRedirectUris: form.value.postLogoutRedirectUris,
        grantTypes: form.value.grantTypes,
        permissions: form.value.permissions
      }
      await authStore.request('/api/clients', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      message.success('OAuth2 客户端已创建')
    } else {
      const updateBody: Record<string, unknown> = {
        displayName: form.value.displayName.trim(),
        // 后端以 null 表示“不修改”；传空字符串才能清空现有元数据。
        description: form.value.description.trim(),
        homepageUrl: form.value.homepageUrl.trim(),
        isFajorCertified: form.value.isFajorCertified,
        scopes: form.value.scopes,
        redirectUris: form.value.redirectUris,
        postLogoutRedirectUris: form.value.postLogoutRedirectUris,
        grantTypes: form.value.grantTypes,
        permissions: form.value.permissions
      }
      if (form.value.clientSecret.trim()) updateBody.clientSecret = form.value.clientSecret.trim()

      await authStore.request(`/api/clients/${encodeURIComponent(editingId.value!)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updateBody)
      })
      message.success('OAuth2 客户端已更新')
    }
    editorVisible.value = false
    await load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '保存客户端失败')
  } finally {
    saving.value = false
  }
}

function normalizeClientType(type: string): 'Public' | 'Confidential' {
  return type.toLowerCase() === 'public' ? 'Public' : 'Confidential'
}

function typeTone(type: string) {
  return normalizeClientType(type) === 'Public' ? 'warning' : 'info'
}

function moreOptions(client: AdminClientItem): any[] {
  const togglePath = client.isDisabled ? '/api/clients/{id}/enable' : '/api/clients/{id}/disable'
  return [
    {
      label: client.isDisabled ? '启用客户端' : '禁用客户端',
      key: 'toggle',
      disabled: !endpointAllowed('PATCH', togglePath)
    },
    {
      label: '上传 / 更换 Logo',
      key: 'logo',
      disabled: !endpointAllowed('PUT', '/api/clients/{id}/logo')
    },
    ...(client.hasLogo ? [{
      label: '删除 Logo',
      key: 'delete-logo',
      disabled: !endpointAllowed('DELETE', '/api/clients/{id}/logo')
    }] : []),
    { type: 'divider', key: 'divider' },
    {
      label: '删除客户端',
      key: 'delete',
      disabled: !endpointAllowed('DELETE', '/api/clients/{id}')
    }
  ]
}

function handleMore(key: string, client: AdminClientItem) {
  if (key === 'toggle') void toggleDisable(client)
  if (key === 'logo') openLogo(client)
  if (key === 'delete-logo') void confirmDeleteLogo(client)
  if (key === 'delete') confirmDelete(client)
}

async function toggleDisable(client: AdminClientItem) {
  try {
    const action = client.isDisabled ? 'enable' : 'disable'
    await authStore.request(`/api/clients/${encodeURIComponent(client.id)}/${action}`, { method: 'PATCH' })
    message.success(client.isDisabled ? '客户端已启用' : '客户端已禁用')
    await load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '操作失败')
  }
}

function confirmDelete(client: AdminClientItem) {
  dialog.warning({
    title: '删除 OAuth2 客户端',
    content: `确定删除“${client.displayName || client.clientId}”吗？现有授权集成将立即失效，且无法恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await authStore.request(`/api/clients/${encodeURIComponent(client.id)}`, { method: 'DELETE' })
        message.success('客户端已删除')
        await load()
      } catch (err) {
        message.error(err instanceof Error ? err.message : '删除失败')
      }
    }
  })
}

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailClient = ref<AdminClientItem | null>(null)

async function openDetail(client: AdminClientItem) {
  detailVisible.value = true
  detailClient.value = client
  if (!endpointAllowed('GET', '/api/clients/{id}')) return
  detailLoading.value = true
  try {
    const latest = await authStore.request<AdminClientItem>(`/api/clients/${encodeURIComponent(client.id)}`)
    if (latest) detailClient.value = latest
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载客户端详情失败')
  } finally {
    detailLoading.value = false
  }
}

const logoVisible = ref(false)
const logoTarget = ref<AdminClientItem | null>(null)
const logoFile = ref<File | null>(null)
const logoUploading = ref(false)

function openLogo(client: AdminClientItem) {
  logoTarget.value = client
  logoFile.value = null
  logoVisible.value = true
}

function onLogoFile(event: Event) {
  const input = event.target as HTMLInputElement
  logoFile.value = input.files?.[0] ?? null
}

async function uploadLogo() {
  if (!logoTarget.value || !logoFile.value) return
  logoUploading.value = true
  try {
    const body = new FormData()
    body.append('file', logoFile.value)
    await authStore.request(`/api/clients/${encodeURIComponent(logoTarget.value.id)}/logo`, {
      method: 'PUT',
      body
    })
    message.success('Logo 已更新')
    logoVisible.value = false
    await load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : 'Logo 上传失败')
  } finally {
    logoUploading.value = false
  }
}

function confirmDeleteLogo(client: AdminClientItem) {
  dialog.warning({
    title: '删除 Logo',
    content: `确定删除“${client.displayName || client.clientId}”的 Logo 吗？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await authStore.request(`/api/clients/${encodeURIComponent(client.id)}/logo`, { method: 'DELETE' })
        message.success('Logo 已删除')
        await load()
      } catch (err) {
        message.error(err instanceof Error ? err.message : 'Logo 删除失败')
      }
    }
  })
}
</script>

<template>
  <section class="admin-page">
    <PageHeader title="OAuth2 / OIDC 客户端" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary @click="load">刷新</NButton>
        <NButton v-if="endpointAllowed('POST', '/api/clients')" type="primary" @click="openCreate">
          添加客户端
        </NButton>
      </template>
    </PageHeader>

    <div class="client-guide admin-panel">
      <div>
        <strong>客户端配置遵循后端实际契约</strong>
        <span>创建时配置类型、凭据和 OAuth 流程；创建后 Client ID 与类型不可通过当前后端更新接口修改。</span>
      </div>
      <span class="client-count">{{ total }} 个客户端</span>
    </div>

    <div class="admin-table-wrap">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="clients.length">
        <table class="admin-table client-table">
          <thead>
            <tr>
              <th>客户端</th>
              <th>类型</th>
              <th>OAuth 流程</th>
              <th>Redirect URI</th>
              <th>状态</th>
              <th style="text-align:right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="client in clients" :key="client.id">
              <td>
                <div class="client-cell">
                  <div v-if="client.hasLogo" class="client-logo">
                    <img :src="`/api/clients/${client.id}/logo`" alt="" />
                  </div>
                  <div v-else class="client-logo-placeholder">{{ client.displayName.charAt(0).toUpperCase() || '?' }}</div>
                  <div class="client-cell-copy">
                    <strong class="truncate">{{ client.displayName }}</strong>
                    <span class="mono truncate">{{ client.clientId }}</span>
                  </div>
                </div>
              </td>
              <td><AppBadge :tone="typeTone(client.type)">{{ normalizeClientType(client.type) }}</AppBadge></td>
              <td>
                <div class="compact-stack">
                  <span>{{ client.grantTypes.includes('authorization_code') ? 'Authorization Code' : (client.grantTypes[0] || '—') }}</span>
                  <span class="small muted">{{ client.scopes.length }} scopes · {{ client.grantTypes.length }} grant types</span>
                </div>
              </td>
              <td>
                <div class="compact-stack uri-summary">
                  <span class="mono">{{ client.redirectUris[0] || '未配置' }}</span>
                  <span v-if="client.redirectUris.length > 1" class="small muted">另有 {{ client.redirectUris.length - 1 }} 个</span>
                </div>
              </td>
              <td>
                <AppBadge :tone="client.isDisabled ? 'danger' : 'success'">
                  {{ client.isDisabled ? '已禁用' : '启用' }}
                </AppBadge>
              </td>
              <td style="text-align:right">
                <div class="row-actions">
                  <NButton size="tiny" quaternary @click="openDetail(client)">详情</NButton>
                  <NButton
                    v-if="endpointAllowed('PUT', '/api/clients/{id}')"
                    size="tiny"
                    quaternary
                    @click="openEdit(client)"
                  >编辑</NButton>
                  <NDropdown trigger="click" :options="moreOptions(client)" @select="(key: string | number) => handleMore(String(key), client)">
                    <NButton size="tiny" quaternary>更多</NButton>
                  </NDropdown>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <AppPagination v-model:page="page" :page-size="pageSize" :total="total" unit="个" @update:page="load" />
      </template>
      <div v-else class="admin-empty empty-clients">
        <NEmpty description="还没有 OAuth2 客户端">
          <template #extra>
            <NButton v-if="endpointAllowed('POST', '/api/clients')" type="primary" @click="openCreate">添加第一个客户端</NButton>
          </template>
        </NEmpty>
      </div>
    </div>

    <NModal
      v-model:show="editorVisible"
      preset="card"
      class="client-editor-modal"
      style="width:min(94vw,820px);max-height:92vh;"
      :title="editorTitle"
      :mask-closable="!saving"
      :close-on-esc="!saving"
    >
      <div class="editor-shell">
        <div class="editor-steps" aria-label="客户端配置步骤">
          <button type="button" :class="{ active: editorStep === 1, done: editorStep > 1 }" @click="editorStep = 1">
            <span>1</span><b>基本信息</b>
          </button>
          <button type="button" :class="{ active: editorStep === 2, done: editorStep > 2 }" @click="validateStep(1) && (editorStep = 2)">
            <span>2</span><b>OAuth 流程</b>
          </button>
          <button type="button" :class="{ active: editorStep === 3 }" @click="validateStep(1) && validateStep(2) && (editorStep = 3)">
            <span>3</span><b>高级与确认</b>
          </button>
        </div>

        <div class="editor-body">
          <div v-if="editorStep === 1" class="editor-section">
            <div class="section-heading">
              <h3>基本信息</h3>
              <p>先确定客户端身份与凭据。Client ID 和类型创建后不能通过当前更新接口修改。</p>
            </div>

            <div class="form-grid two-col">
              <label class="form-field" :class="{ 'has-error': formErrors.clientId }">
                <span class="field-label required">Client ID</span>
                <input v-model="form.clientId" class="admin-input mono" :disabled="isEditing" placeholder="例如 console-web" />
                <span class="field-hint">OAuth 客户端唯一标识，最长 128 个字符。</span>
                <span v-if="formErrors.clientId" class="field-error">{{ formErrors.clientId }}</span>
              </label>

              <label class="form-field" :class="{ 'has-error': formErrors.displayName }">
                <span class="field-label required">显示名称</span>
                <input v-model="form.displayName" class="admin-input" placeholder="例如 Console Web" />
                <span class="field-hint">展示给管理员和授权页面的名称。</span>
                <span v-if="formErrors.displayName" class="field-error">{{ formErrors.displayName }}</span>
              </label>
            </div>

            <div class="form-field">
              <span class="field-label required">客户端类型</span>
              <div v-if="!isEditing" class="type-grid">
                <button type="button" :class="['type-choice', { active: form.type === 'Confidential' }]" @click="setClientType('Confidential')">
                  <strong>Confidential</strong>
                  <span>服务端应用，持有 Client Secret。</span>
                </button>
                <button type="button" :class="['type-choice', { active: form.type === 'Public' }]" @click="setClientType('Public')">
                  <strong>Public</strong>
                  <span>SPA / 移动应用，不保存 Client Secret。</span>
                </button>
              </div>
              <div v-else class="readonly-value">
                <AppBadge :tone="typeTone(form.type)">{{ form.type }}</AppBadge>
                <span>后端 ClientUpdateRequest 不支持修改类型；如需变更，请创建新客户端。</span>
              </div>
            </div>

            <div v-if="form.type === 'Confidential'" class="form-field" :class="{ 'has-error': formErrors.clientSecret }">
              <span class="field-label" :class="{ required: !isEditing }">Client Secret</span>
              <div class="input-with-action">
                <input
                  v-model="form.clientSecret"
                  :type="secretVisible ? 'text' : 'password'"
                  autocomplete="new-password"
                  class="admin-input mono"
                  :placeholder="isEditing ? '留空表示不修改现有 Secret' : '输入或生成安全 Secret'"
                />
                <NButton @click="secretVisible = !secretVisible">{{ secretVisible ? '隐藏' : '显示' }}</NButton>
                <NButton @click="generateSecret">生成</NButton>
                <NButton :disabled="!form.clientSecret" @click="copySecret">复制</NButton>
              </div>
              <span class="field-hint">后端不会把现有 Secret 返回给 AdminUI。编辑时只有填写新值才会轮换 Secret。</span>
              <span v-if="formErrors.clientSecret" class="field-error">{{ formErrors.clientSecret }}</span>
            </div>

            <div v-else class="inline-note">
              Public 客户端不会提交 Client Secret。建议使用 Authorization Code + PKCE。
            </div>

            <label class="form-field">
              <span class="field-label">客户端说明</span>
              <textarea v-model="form.description" class="admin-input" rows="3" placeholder="用途、负责人或集成说明" />
            </label>

            <label class="form-field" :class="{ 'has-error': formErrors.homepageUrl }">
              <span class="field-label">主页 URL</span>
              <input v-model="form.homepageUrl" class="admin-input mono" placeholder="https://app.example.com" />
              <span v-if="formErrors.homepageUrl" class="field-error">{{ formErrors.homepageUrl }}</span>
            </label>
          </div>

          <div v-else-if="editorStep === 2" class="editor-section">
            <div class="section-heading">
              <h3>OAuth 流程</h3>
              <p>配置 Scope、Grant Type 和回调地址。URI 校验与后端规则保持一致。</p>
            </div>

            <div class="form-field" :class="{ 'has-error': formErrors.scopes }">
              <span class="field-label required">Scopes</span>
              <div class="option-grid">
                <button
                  v-for="scope in presetScopes"
                  :key="scope.value"
                  type="button"
                  :class="['option-toggle', { active: form.scopes.includes(scope.value) }]"
                  @click="toggleScope(scope.value)"
                >
                  <strong>{{ scope.label }}</strong><span>{{ scope.desc }}</span>
                </button>
              </div>
              <textarea
                :value="joinValues(form.scopes)"
                class="admin-input mono values-editor"
                rows="4"
                placeholder="每行一个 Scope"
                @input="form.scopes = splitValues(($event.target as HTMLTextAreaElement).value)"
              />
              <span class="field-hint">可直接编辑完整列表以添加自定义 Scope。</span>
              <span v-if="formErrors.scopes" class="field-error">{{ formErrors.scopes }}</span>
            </div>

            <div class="form-field" :class="{ 'has-error': formErrors.grantTypes }">
              <span class="field-label required">Grant Types</span>
              <div class="option-grid grant-grid">
                <button
                  v-for="grant in presetGrantTypes"
                  :key="grant.value"
                  type="button"
                  :disabled="grant.value === 'client_credentials' && form.type === 'Public'"
                  :class="['option-toggle', { active: form.grantTypes.includes(grant.value) }]"
                  @click="toggleGrantType(grant.value)"
                >
                  <strong>{{ grant.label }}</strong><span>{{ grant.desc }}</span>
                </button>
              </div>
              <textarea
                :value="joinValues(form.grantTypes)"
                class="admin-input mono values-editor"
                rows="3"
                placeholder="每行一个 Grant Type"
                @input="form.grantTypes = splitValues(($event.target as HTMLTextAreaElement).value)"
              />
              <span v-if="formErrors.grantTypes" class="field-error">{{ formErrors.grantTypes }}</span>
            </div>

            <label class="form-field" :class="{ 'has-error': formErrors.redirectUris }">
              <span class="field-label">Redirect URIs</span>
              <textarea
                :value="joinValues(form.redirectUris)"
                class="admin-input mono"
                rows="4"
                placeholder="https://app.example.com/callback"
                @input="form.redirectUris = splitValues(($event.target as HTMLTextAreaElement).value)"
              />
              <span class="field-hint">后端允许 HTTPS；开发环境允许 http://localhost 或 HTTP loopback 地址。每行一个。</span>
              <span v-if="usesAuthorizationCode && !form.redirectUris.length" class="field-warning">Authorization Code 通常需要至少一个 Redirect URI。</span>
              <span v-if="formErrors.redirectUris" class="field-error">{{ formErrors.redirectUris }}</span>
            </label>

            <label class="form-field" :class="{ 'has-error': formErrors.postLogoutRedirectUris }">
              <span class="field-label">Post Logout Redirect URIs</span>
              <textarea
                :value="joinValues(form.postLogoutRedirectUris)"
                class="admin-input mono"
                rows="3"
                placeholder="https://app.example.com/"
                @input="form.postLogoutRedirectUris = splitValues(($event.target as HTMLTextAreaElement).value)"
              />
              <span v-if="formErrors.postLogoutRedirectUris" class="field-error">{{ formErrors.postLogoutRedirectUris }}</span>
            </label>
          </div>

          <div v-else class="editor-section">
            <div class="section-heading">
              <h3>高级设置与确认</h3>
              <p>检查最终配置。原始 Permissions 仅在确实需要 OpenIddict 扩展权限时修改。</p>
            </div>

            <div class="setting-line">
              <div>
                <strong>Fajor 认证标记</strong>
                <span>对应后端 OAuthClientMetadata.IsFajorCertified。</span>
              </div>
              <NSwitch v-model:value="form.isFajorCertified" />
            </div>

            <label class="form-field">
              <span class="field-label">Raw Permissions</span>
              <textarea
                :value="joinValues(form.permissions)"
                class="admin-input mono"
                rows="5"
                placeholder="每行一个 OpenIddict permission；通常无需手动添加"
                @input="form.permissions = splitValues(($event.target as HTMLTextAreaElement).value)"
              />
              <span class="field-hint">后端会自动补齐 Authorization、Token、EndSession 和 code response type 等必需权限。</span>
            </label>

            <div class="review-box">
              <dl>
                <div><dt>Client ID</dt><dd class="mono">{{ form.clientId }}</dd></div>
                <div><dt>类型</dt><dd>{{ form.type }}</dd></div>
                <div><dt>Scopes</dt><dd>{{ form.scopes.length }}</dd></div>
                <div><dt>Grant Types</dt><dd>{{ form.grantTypes.length }}</dd></div>
                <div><dt>Redirect URIs</dt><dd>{{ form.redirectUris.length }}</dd></div>
                <div><dt>状态</dt><dd>{{ isEditing ? '保留当前启停状态' : '创建后默认启用' }}</dd></div>
              </dl>
            </div>
          </div>
        </div>

        <div class="editor-footer">
          <NButton quaternary :disabled="saving" @click="editorVisible = false">取消</NButton>
          <div class="editor-footer-right">
            <NButton v-if="editorStep > 1" :disabled="saving" @click="previousStep">上一步</NButton>
            <NButton v-if="editorStep < 3" type="primary" @click="nextStep">下一步</NButton>
            <NButton v-else type="primary" :loading="saving" @click="save">
              {{ isEditing ? '保存修改' : '创建客户端' }}
            </NButton>
          </div>
        </div>
      </div>
    </NModal>

    <NModal v-model:show="detailVisible" preset="card" style="width:min(94vw,720px)" title="客户端详情">
      <div v-if="detailLoading" class="detail-loading"><NSpin size="small" /></div>
      <div v-if="detailClient" class="client-detail">
        <div class="detail-client-header">
          <div v-if="detailClient.hasLogo" class="client-logo detail-logo">
            <img :src="`/api/clients/${detailClient.id}/logo`" alt="" />
          </div>
          <div v-else class="client-logo-placeholder detail-logo">{{ detailClient.displayName.charAt(0).toUpperCase() || '?' }}</div>
          <div>
            <h3>{{ detailClient.displayName }}</h3>
            <span class="mono muted">{{ detailClient.clientId }}</span>
            <div class="detail-badges">
              <AppBadge :tone="typeTone(detailClient.type)">{{ normalizeClientType(detailClient.type) }}</AppBadge>
              <AppBadge :tone="detailClient.isDisabled ? 'danger' : 'success'">{{ detailClient.isDisabled ? '已禁用' : '启用' }}</AppBadge>
              <AppBadge v-if="detailClient.isFajorCertified" tone="purple">Fajor 认证</AppBadge>
            </div>
          </div>
        </div>

        <dl class="admin-detail-grid detail-grid">
          <div><dt>说明</dt><dd>{{ detailClient.description || '—' }}</dd></div>
          <div><dt>主页</dt><dd><a v-if="detailClient.homepageUrl" :href="detailClient.homepageUrl" target="_blank" rel="noopener">{{ detailClient.homepageUrl }}</a><span v-else>—</span></dd></div>
          <div><dt>Scopes</dt><dd class="mono">{{ detailClient.scopes.join('\n') || '—' }}</dd></div>
          <div><dt>Grant Types</dt><dd class="mono">{{ detailClient.grantTypes.join('\n') || '—' }}</dd></div>
          <div><dt>Redirect URIs</dt><dd class="mono">{{ detailClient.redirectUris.join('\n') || '—' }}</dd></div>
          <div><dt>Post Logout URIs</dt><dd class="mono">{{ detailClient.postLogoutRedirectUris.join('\n') || '—' }}</dd></div>
          <div class="detail-wide"><dt>Permissions</dt><dd class="mono">{{ detailClient.permissions.join('\n') || '—' }}</dd></div>
        </dl>
      </div>
    </NModal>

    <NModal v-model:show="logoVisible" preset="card" style="width:min(92vw,460px)" title="更新客户端 Logo">
      <div class="logo-editor">
        <div v-if="logoTarget" class="logo-target">
          <strong>{{ logoTarget.displayName }}</strong>
          <span class="mono muted small">{{ logoTarget.clientId }}</span>
        </div>
        <input type="file" accept="image/svg+xml,image/png" @change="onLogoFile" />
        <span class="field-hint">后端仅接受 SVG / PNG，最大 2 MB；SVG 会由服务端进行安全清理。</span>
        <div class="modal-actions">
          <NButton quaternary @click="logoVisible = false">取消</NButton>
          <NButton type="primary" :disabled="!logoFile" :loading="logoUploading" @click="uploadLogo">上传</NButton>
        </div>
      </div>
    </NModal>
  </section>
</template>

<style scoped>
.client-guide {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 13px 16px;
}
.client-guide > div { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.client-guide strong { font-size: 12px; font-weight: 650; color: var(--text-primary); }
.client-guide span { font-size: 12px; color: var(--text-tertiary); }
.client-count { flex-shrink: 0; white-space: nowrap; }

.client-table { min-width: 940px; }
.client-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
.client-cell-copy { min-width: 0; max-width: 250px; display: flex; flex-direction: column; gap: 1px; }
.client-cell-copy strong { font-size: 13px; font-weight: 650; }
.client-cell-copy span { font-size: 11px; color: var(--text-tertiary); }
.client-logo,
.client-logo-placeholder {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-sunken);
}
.client-logo { overflow: hidden; }
.client-logo img { width: 100%; height: 100%; object-fit: contain; }
.client-logo-placeholder { display: flex; align-items: center; justify-content: center; color: var(--text-tertiary); font-weight: 650; }
.compact-stack { display: flex; flex-direction: column; gap: 1px; }
.uri-summary { max-width: 270px; }
.uri-summary > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-actions { display: inline-flex; align-items: center; justify-content: flex-end; gap: 2px; }
.empty-clients { min-height: 260px; }

.editor-shell { display: flex; flex-direction: column; min-height: 560px; }
.editor-steps {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
}
.editor-steps button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 0;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  text-align: left;
}
.editor-steps button > span {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid var(--border-strong);
  border-radius: 50%;
  font-size: 11px;
}
.editor-steps b { font-size: 12px; font-weight: 600; }
.editor-steps button.active { color: var(--text-primary); }
.editor-steps button.active > span { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.editor-steps button.done > span { border-color: var(--accent); color: var(--accent); }
.editor-body { flex: 1; min-height: 0; overflow-y: auto; padding: 20px 2px 18px; }
.editor-section { display: flex; flex-direction: column; gap: 18px; }
.section-heading h3 { margin: 0; font-size: 15px; font-weight: 650; }
.section-heading p { margin: 4px 0 0; color: var(--text-tertiary); font-size: 12px; }
.form-grid.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.type-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.type-choice,
.option-toggle {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
}
.type-choice { display: flex; flex-direction: column; gap: 3px; padding: 12px; }
.type-choice:hover,
.option-toggle:hover:not(:disabled) { border-color: var(--border-strong); background: var(--surface-hover); }
.type-choice.active,
.option-toggle.active { border-color: var(--accent); background: var(--accent-soft); }
.type-choice strong,
.option-toggle strong { color: var(--text-primary); font-size: 12px; font-weight: 650; }
.type-choice span,
.option-toggle span { color: var(--text-tertiary); font-size: 11px; }
.readonly-value { min-height: 38px; display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-sunken); }
.readonly-value > span:last-child { font-size: 11px; color: var(--text-tertiary); }
.input-with-action { display: grid; grid-template-columns: minmax(0, 1fr) auto auto auto; gap: 8px; }
.inline-note { padding: 10px 12px; border-left: 3px solid var(--info); background: var(--info-soft); color: var(--text-secondary); font-size: 12px; }
.option-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 9px; }
.option-toggle { display: flex; flex-direction: column; gap: 2px; min-height: 58px; padding: 9px 10px; }
.option-toggle:disabled { opacity: .45; cursor: not-allowed; }
.values-editor { margin-top: 0; }
.field-warning { display: block; margin-top: 5px; color: var(--warning); font-size: 12px; }
.setting-line { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-sunken); }
.setting-line > div { display: flex; flex-direction: column; gap: 2px; }
.setting-line strong { font-size: 12px; font-weight: 650; }
.setting-line span { font-size: 11px; color: var(--text-tertiary); }
.review-box { padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-sunken); }
.review-box dl { display: grid; grid-template-columns: 1fr 1fr; gap: 11px 18px; margin: 0; }
.review-box dl > div { min-width: 0; }
.review-box dt { font-size: 10px; color: var(--text-tertiary); }
.review-box dd { margin: 2px 0 0; font-size: 12px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.editor-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 14px; border-top: 1px solid var(--border); }
.editor-footer-right { display: flex; align-items: center; gap: 8px; }

.detail-loading { display: flex; justify-content: center; padding: 10px; }
.client-detail { display: flex; flex-direction: column; gap: 20px; }
.detail-client-header { display: flex; align-items: center; gap: 12px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
.detail-logo { width: 44px; height: 44px; }
.detail-client-header h3 { margin: 0 0 2px; font-size: 16px; font-weight: 650; }
.detail-client-header .mono { font-size: 11px; }
.detail-badges { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
.detail-grid { grid-template-columns: 1fr 1fr; }
.detail-wide { grid-column: 1 / -1; }
.logo-editor { display: flex; flex-direction: column; gap: 14px; }
.logo-target { display: flex; flex-direction: column; gap: 1px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }

@media (max-width: 720px) {
  .client-guide { align-items: flex-start; flex-direction: column; gap: 6px; }
  .form-grid.two-col,
  .type-grid,
  .option-grid,
  .review-box dl,
  .detail-grid { grid-template-columns: 1fr; }
  .detail-wide { grid-column: auto; }
  .input-with-action { grid-template-columns: 1fr 1fr 1fr; }
  .input-with-action .admin-input { grid-column: 1 / -1; }
  .editor-steps b { display: none; }
  .editor-steps button { justify-content: center; }
}
</style>
