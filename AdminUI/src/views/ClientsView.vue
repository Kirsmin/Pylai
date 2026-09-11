<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { X } from '@vicons/tabler'
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
  return cap.value?.endpoints.some((endpoint) => endpoint.method === method && endpoint.path === path) ?? false
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      skip: String((page.value - 1) * pageSize),
      take: String(pageSize)
    })
    const data = await authStore.request<{ total: number; items: AdminClientItem[] }>(`/api/clients?${params.toString()}`)
    clients.value = data?.items ?? []
    total.value = data?.total ?? 0
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载客户端失败')
  } finally {
    loading.value = false
  }
}

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

const scopeOptions = [
  { value: 'openid', label: 'openid — OpenID Connect 标识' },
  { value: 'profile:basic', label: 'profile:basic — 基础资料' },
  { value: 'profile:mail', label: 'profile:mail — 邮箱' },
  { value: 'profile:role', label: 'profile:role — 用户组' },
  { value: 'offline_access', label: 'offline_access — Refresh Token' }
]
const grantTypeOptions = [
  { value: 'authorization_code', label: 'authorization_code — 浏览器 / OIDC 推荐' },
  { value: 'refresh_token', label: 'refresh_token — 刷新访问令牌' },
  { value: 'client_credentials', label: 'client_credentials — 服务到服务' }
]
const permissionOptions = [
  { value: 'endpoint:introspection', label: 'endpoint:introspection' },
  { value: 'endpoint:revocation', label: 'endpoint:revocation' },
  { value: 'endpoint:authorization', label: 'endpoint:authorization' },
  { value: 'endpoint:token', label: 'endpoint:token' },
  { value: 'endpoint:end_session', label: 'endpoint:end_session' },
  { value: 'response_type:code', label: 'response_type:code' }
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
const stepDefinitions = [
  { value: 1, title: '身份与凭据', description: 'Client ID、类型和 Secret' },
  { value: 2, title: '授权能力', description: 'Scopes 与 Grant Types' },
  { value: 3, title: '回调地址', description: 'Redirect / Logout URI' },
  { value: 4, title: '确认配置', description: '元数据与高级权限' }
]

function normalizeClientType(type: string): 'Public' | 'Confidential' {
  return type.toLowerCase() === 'public' ? 'Public' : 'Confidential'
}

function typeTone(type: string): 'warning' | 'info' {
  return normalizeClientType(type) === 'Public' ? 'warning' : 'info'
}

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

watch(() => form.value.type, (type) => {
  if (type === 'Public') {
    form.value.clientSecret = ''
    form.value.grantTypes = form.value.grantTypes.filter((grant) => grant !== 'client_credentials')
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
  return host === 'localhost' || host === '127.0.0.1' || host === '[::1]' || /^127(?:\.\d{1,3}){3}$/.test(host)
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

function normalizeValues(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)))
}

function validateStep(step: number): boolean {
  const errors: Record<string, string> = { ...formErrors.value }

  if (step === 1) {
    for (const key of ['clientId', 'displayName', 'clientSecret', 'homepageUrl']) delete errors[key]
    const clientId = form.value.clientId.trim()
    if (!clientId) errors.clientId = 'Client ID 不能为空'
    else if (clientId.length > 128) errors.clientId = 'Client ID 不能超过 128 个字符'
    if (!form.value.displayName.trim()) errors.displayName = '显示名称不能为空'
    if (!isEditing.value && form.value.type === 'Confidential' && !form.value.clientSecret.trim()) {
      errors.clientSecret = 'Confidential 客户端创建时必须提供 Client Secret'
    }
    if (!isValidHomepage(form.value.homepageUrl)) errors.homepageUrl = '主页地址必须是完整的 http:// 或 https:// URL'
  }

  if (step === 2) {
    for (const key of ['scopes', 'grantTypes']) delete errors[key]
    if (!form.value.scopes.length) errors.scopes = '至少需要一个 Scope'
    if (!form.value.grantTypes.length) errors.grantTypes = '至少需要一个 Grant Type'
    if (form.value.type === 'Public' && form.value.grantTypes.includes('client_credentials')) {
      errors.grantTypes = 'Public 客户端不能使用 client_credentials'
    }
  }

  if (step === 3) {
    for (const key of ['redirectUris', 'postLogoutRedirectUris']) delete errors[key]
    const redirectUris = normalizeValues(form.value.redirectUris)
    const postLogoutUris = normalizeValues(form.value.postLogoutRedirectUris)
    const invalidRedirect = redirectUris.find((uri) => !isValidRedirectUri(uri))
    const invalidLogout = postLogoutUris.find((uri) => !isValidRedirectUri(uri))
    if (invalidRedirect) errors.redirectUris = `非法 Redirect URI：${invalidRedirect}`
    if (invalidLogout) errors.postLogoutRedirectUris = `非法 Post Logout URI：${invalidLogout}`
  }

  formErrors.value = errors
  const keysByStep: Record<number, string[]> = {
    1: ['clientId', 'displayName', 'clientSecret', 'homepageUrl'],
    2: ['scopes', 'grantTypes'],
    3: ['redirectUris', 'postLogoutRedirectUris']
  }
  return !(keysByStep[step] || []).some((key) => Boolean(errors[key]))
}

function goToStep(target: number) {
  if (target <= editorStep.value) {
    editorStep.value = target
    return
  }
  for (let step = 1; step < target; step += 1) {
    if (!validateStep(step)) {
      editorStep.value = step
      message.error('请先修正当前步骤中的配置')
      return
    }
  }
  editorStep.value = target
}

function nextStep() {
  if (!validateStep(editorStep.value)) {
    message.error('请先修正当前步骤中的配置')
    return
  }
  editorStep.value = Math.min(4, editorStep.value + 1)
}

function previousStep() {
  editorStep.value = Math.max(1, editorStep.value - 1)
}

function addUri(kind: 'redirect' | 'logout') {
  const target = kind === 'redirect' ? form.value.redirectUris : form.value.postLogoutRedirectUris
  target.push('')
}

function removeUri(kind: 'redirect' | 'logout', index: number) {
  const target = kind === 'redirect' ? form.value.redirectUris : form.value.postLogoutRedirectUris
  target.splice(index, 1)
  delete formErrors.value[kind === 'redirect' ? 'redirectUris' : 'postLogoutRedirectUris']
}

async function save() {
  for (let step = 1; step <= 3; step += 1) {
    if (!validateStep(step)) {
      editorStep.value = step
      message.error('请修正配置后再保存')
      return
    }
  }

  const redirectUris = normalizeValues(form.value.redirectUris)
  const postLogoutRedirectUris = normalizeValues(form.value.postLogoutRedirectUris)
  const scopes = normalizeValues(form.value.scopes)
  const grantTypes = normalizeValues(form.value.grantTypes)
  const permissions = normalizeValues(form.value.permissions)

  saving.value = true
  try {
    if (!isEditing.value) {
      await authStore.request('/api/clients', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          clientId: form.value.clientId.trim(),
          displayName: form.value.displayName.trim(),
          clientSecret: form.value.type === 'Confidential' ? form.value.clientSecret.trim() : '',
          description: form.value.description.trim(),
          homepageUrl: form.value.homepageUrl.trim(),
          isFajorCertified: form.value.isFajorCertified,
          type: form.value.type,
          scopes,
          redirectUris,
          postLogoutRedirectUris,
          grantTypes,
          permissions
        })
      })
      message.success('OAuth2 客户端已创建')
    } else {
      const updateBody: Record<string, unknown> = {
        displayName: form.value.displayName.trim(),
        description: form.value.description.trim(),
        homepageUrl: form.value.homepageUrl.trim(),
        isFajorCertified: form.value.isFajorCertified,
        scopes,
        redirectUris,
        postLogoutRedirectUris,
        grantTypes,
        permissions
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

function moreOptions(client: AdminClientItem): any[] {
  const togglePath = client.isDisabled ? '/api/clients/{id}/enable' : '/api/clients/{id}/disable'
  return [
    { label: client.isDisabled ? '启用客户端' : '禁用客户端', key: 'toggle', disabled: !endpointAllowed('PATCH', togglePath) },
    { label: '上传 / 更换 Logo', key: 'logo', disabled: !endpointAllowed('PUT', '/api/clients/{id}/logo') },
    ...(client.hasLogo ? [{ label: '删除 Logo', key: 'delete-logo', disabled: !endpointAllowed('DELETE', '/api/clients/{id}/logo') }] : []),
    { type: 'divider', key: 'divider' },
    { label: '删除客户端', key: 'delete', disabled: !endpointAllowed('DELETE', '/api/clients/{id}') }
  ]
}

function handleMore(key: string, client: AdminClientItem) {
  if (key === 'toggle') void toggleDisable(client)
  if (key === 'logo') openLogo(client)
  if (key === 'delete-logo') confirmDeleteLogo(client)
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
    await authStore.request(`/api/clients/${encodeURIComponent(logoTarget.value.id)}/logo`, { method: 'PUT', body })
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

onMounted(load)
</script>

<template>
  <section class="admin-page">
    <PageHeader title="OAuth2 / OIDC 客户端" :subtitle="cap?.description || '管理接入 Pylai 的 OAuth2 / OpenID Connect 客户端。'">
      <template #actions>
        <NButton quaternary :loading="loading" @click="load">刷新</NButton>
        <NButton v-if="endpointAllowed('POST', '/api/clients')" type="primary" @click="openCreate">添加客户端</NButton>
      </template>
    </PageHeader>

    <div class="admin-context-strip client-guide">
      <span>Client ID 与客户端类型创建后不可修改；编辑时只有填写新的 Client Secret 才会轮换现有凭据。</span>
      <strong>{{ total }} 个客户端</strong>
    </div>

    <div class="admin-table-wrap">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="clients.length">
        <table class="admin-table client-table">
          <thead>
            <tr>
              <th>客户端</th>
              <th>类型</th>
              <th>授权能力</th>
              <th>回调地址</th>
              <th>状态</th>
              <th style="text-align:right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="client in clients" :key="client.id">
              <td>
                <div class="client-cell">
                  <div v-if="client.hasLogo" class="client-logo"><img :src="`/api/clients/${client.id}/logo`" alt="" /></div>
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
                  <span class="small muted">{{ client.scopes.length }} scopes · {{ client.grantTypes.length }} grants</span>
                </div>
              </td>
              <td>
                <div class="compact-stack uri-summary">
                  <span class="mono">{{ client.redirectUris[0] || '未配置' }}</span>
                  <span v-if="client.redirectUris.length > 1" class="small muted">另有 {{ client.redirectUris.length - 1 }} 个</span>
                </div>
              </td>
              <td><AppBadge :tone="client.isDisabled ? 'danger' : 'success'">{{ client.isDisabled ? '已禁用' : '启用' }}</AppBadge></td>
              <td style="text-align:right">
                <div class="row-actions">
                  <NButton size="tiny" quaternary @click="openDetail(client)">详情</NButton>
                  <NButton v-if="endpointAllowed('PUT', '/api/clients/{id}')" size="tiny" quaternary @click="openEdit(client)">编辑</NButton>
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

    <NModal v-model:show="editorVisible" :mask-closable="!saving" :close-on-esc="!saving">
      <div class="client-editor-dialog" role="dialog" aria-modal="true" :aria-label="editorTitle">
        <header class="client-editor-header">
          <div>
            <h2>{{ editorTitle }}</h2>
            <p>{{ isEditing ? '按后端更新契约调整客户端配置。Client ID 与类型保持只读。' : '按照 OAuth2 客户端接入流程完成身份、授权能力和回调地址配置。' }}</p>
          </div>
          <button type="button" class="editor-close" title="关闭" :disabled="saving" @click="editorVisible = false">
            <NIcon :component="X" />
          </button>
        </header>

        <div class="client-editor-layout">
          <aside class="client-editor-steps" aria-label="客户端配置步骤">
            <button
              v-for="step in stepDefinitions"
              :key="step.value"
              type="button"
              :class="{ active: editorStep === step.value, done: editorStep > step.value }"
              @click="goToStep(step.value)"
            >
              <span class="step-number">{{ step.value }}</span>
              <span class="step-copy">
                <strong>{{ step.title }}</strong>
                <small>{{ step.description }}</small>
              </span>
            </button>
          </aside>

          <main class="client-editor-content">
            <section v-if="editorStep === 1" class="editor-section">
              <div class="section-heading">
                <span class="section-kicker">STEP 1</span>
                <h3>身份与凭据</h3>
                <p>先确定客户端身份。Confidential 用于能够安全保存 Secret 的服务端应用；Public 用于 SPA / 原生应用。</p>
              </div>

              <div class="form-grid two-col">
                <div class="form-field" :class="{ 'has-error': formErrors.clientId }">
                  <span class="field-label required">Client ID</span>
                  <NInput v-model:value="form.clientId" :disabled="isEditing" placeholder="例如 console-web" maxlength="128" />
                  <span class="field-hint">OAuth 客户端唯一标识，最长 128 个字符；创建后不可修改。</span>
                  <span v-if="formErrors.clientId" class="field-error">{{ formErrors.clientId }}</span>
                </div>
                <div class="form-field" :class="{ 'has-error': formErrors.displayName }">
                  <span class="field-label required">显示名称</span>
                  <NInput v-model:value="form.displayName" placeholder="例如 Console Web" />
                  <span class="field-hint">展示给管理员和授权页面的名称。</span>
                  <span v-if="formErrors.displayName" class="field-error">{{ formErrors.displayName }}</span>
                </div>
              </div>

              <div class="form-field">
                <span class="field-label required">客户端类型</span>
                <div v-if="isEditing" class="readonly-value">
                  <AppBadge :tone="typeTone(form.type)">{{ form.type }}</AppBadge>
                  <span>后端更新接口不允许修改客户端类型。</span>
                </div>
                <NRadioGroup v-else v-model:value="form.type" name="client-type" class="client-type-group">
                  <NRadioButton value="Confidential">Confidential</NRadioButton>
                  <NRadioButton value="Public">Public</NRadioButton>
                </NRadioGroup>
                <span class="field-hint">Confidential 保存 Client Secret；Public 不保存 Secret，且不能使用 client_credentials。</span>
              </div>

              <div v-if="form.type === 'Confidential'" class="form-field" :class="{ 'has-error': formErrors.clientSecret }">
                <span class="field-label" :class="{ required: !isEditing }">Client Secret</span>
                <div class="secret-input-row">
                  <NInput v-model:value="form.clientSecret" :type="secretVisible ? 'text' : 'password'" :placeholder="isEditing ? '留空则保持现有 Secret' : '输入或生成安全 Secret'" />
                  <NButton @click="secretVisible = !secretVisible">{{ secretVisible ? '隐藏' : '显示' }}</NButton>
                  <NButton @click="generateSecret">生成</NButton>
                  <NButton :disabled="!form.clientSecret" @click="copySecret">复制</NButton>
                </div>
                <span class="field-hint">后端不会返回现有 Secret；编辑时仅提交非空值才会轮换。</span>
                <span v-if="formErrors.clientSecret" class="field-error">{{ formErrors.clientSecret }}</span>
              </div>

              <div class="form-grid two-col">
                <div class="form-field" :class="{ 'has-error': formErrors.homepageUrl }">
                  <span class="field-label">主页 URL</span>
                  <NInput v-model:value="form.homepageUrl" placeholder="https://app.example.com" />
                  <span v-if="formErrors.homepageUrl" class="field-error">{{ formErrors.homepageUrl }}</span>
                </div>
                <div class="form-field">
                  <span class="field-label">客户端说明</span>
                  <NInput v-model:value="form.description" placeholder="用途、负责人或集成说明" />
                </div>
              </div>
            </section>

            <section v-else-if="editorStep === 2" class="editor-section">
              <div class="section-heading">
                <span class="section-kicker">STEP 2</span>
                <h3>授权能力</h3>
                <p>配置客户端可请求的 Scope 与 OAuth Grant Type。后端会根据这些字段自动生成对应 OpenIddict 权限。</p>
              </div>

              <div class="form-field" :class="{ 'has-error': formErrors.scopes }">
                <span class="field-label required">Scopes</span>
                <NSelect v-model:value="form.scopes" :options="scopeOptions" multiple filterable tag placeholder="选择或输入 Scope" />
                <span class="field-hint">openid 用于 OIDC；offline_access 通常与 refresh_token 一起使用。</span>
                <span v-if="formErrors.scopes" class="field-error">{{ formErrors.scopes }}</span>
              </div>

              <div class="form-field" :class="{ 'has-error': formErrors.grantTypes }">
                <span class="field-label required">Grant Types</span>
                <NSelect
                  v-model:value="form.grantTypes"
                  :options="grantTypeOptions.map((item) => ({ ...item, disabled: item.value === 'client_credentials' && form.type === 'Public' }))"
                  multiple
                  placeholder="选择授权流程"
                />
                <span class="field-hint">浏览器登录通常使用 authorization_code + refresh_token；client_credentials 仅适用于 Confidential 服务端应用。</span>
                <span v-if="formErrors.grantTypes" class="field-error">{{ formErrors.grantTypes }}</span>
              </div>

              <NAlert v-if="form.type === 'Public'" type="info" :show-icon="false">
                Public 客户端不持有 Client Secret，也不能使用 client_credentials。对于 SPA / 原生应用，请在客户端侧配合 PKCE。
              </NAlert>
            </section>

            <section v-else-if="editorStep === 3" class="editor-section">
              <div class="section-heading">
                <span class="section-kicker">STEP 3</span>
                <h3>回调地址</h3>
                <p>Redirect URI 必须精确匹配客户端请求。生产环境使用 HTTPS；HTTP 仅允许 localhost / loopback。</p>
              </div>

              <div class="form-field" :class="{ 'has-error': formErrors.redirectUris }">
                <div class="field-heading-row">
                  <div>
                    <span class="field-label">Redirect URIs</span>
                    <span class="field-hint">Authorization Code 流程完成后跳转到这里。</span>
                  </div>
                  <NButton size="small" @click="addUri('redirect')">添加 URI</NButton>
                </div>
                <div v-if="form.redirectUris.length" class="uri-editor-list">
                  <div v-for="(_, index) in form.redirectUris" :key="`redirect-${index}`" class="uri-editor-row">
                    <NInput v-model:value="form.redirectUris[index]" placeholder="https://app.example.com/oauth/callback" />
                    <NButton quaternary @click="removeUri('redirect', index)">删除</NButton>
                  </div>
                </div>
                <div v-else class="empty-uri-row">尚未配置 Redirect URI。</div>
                <span v-if="usesAuthorizationCode && !form.redirectUris.length" class="field-warning">当前已启用 authorization_code，但尚未配置回调地址。</span>
                <span v-if="formErrors.redirectUris" class="field-error">{{ formErrors.redirectUris }}</span>
              </div>

              <div class="form-field" :class="{ 'has-error': formErrors.postLogoutRedirectUris }">
                <div class="field-heading-row">
                  <div>
                    <span class="field-label">Post Logout Redirect URIs</span>
                    <span class="field-hint">OIDC 登出完成后允许返回的地址。</span>
                  </div>
                  <NButton size="small" @click="addUri('logout')">添加 URI</NButton>
                </div>
                <div v-if="form.postLogoutRedirectUris.length" class="uri-editor-list">
                  <div v-for="(_, index) in form.postLogoutRedirectUris" :key="`logout-${index}`" class="uri-editor-row">
                    <NInput v-model:value="form.postLogoutRedirectUris[index]" placeholder="https://app.example.com/" />
                    <NButton quaternary @click="removeUri('logout', index)">删除</NButton>
                  </div>
                </div>
                <div v-else class="empty-uri-row">尚未配置 Post Logout URI。</div>
                <span v-if="formErrors.postLogoutRedirectUris" class="field-error">{{ formErrors.postLogoutRedirectUris }}</span>
              </div>
            </section>

            <section v-else class="editor-section">
              <div class="section-heading">
                <span class="section-kicker">STEP 4</span>
                <h3>确认配置</h3>
                <p>检查关键 OAuth 配置，并按需补充高级 OpenIddict 端点权限。</p>
              </div>

              <div class="setting-line">
                <div>
                  <strong>Fajor 认证标记</strong>
                  <span>在授权页面标记该客户端为已认证应用。只对经过内部审核的客户端开启。</span>
                </div>
                <NSwitch v-model:value="form.isFajorCertified" />
              </div>

              <div class="form-field">
                <span class="field-label">额外 Permissions</span>
                <NSelect v-model:value="form.permissions" :options="permissionOptions" multiple filterable tag placeholder="通常无需手动配置" />
                <span class="field-hint">后端会自动补齐 authorization / token / end_session / response_type:code，以及由 scopes / grantTypes 推导的权限。这里仅放额外权限。</span>
              </div>

              <div class="review-box">
                <dl>
                  <div><dt>Client ID</dt><dd class="mono">{{ form.clientId || '—' }}</dd></div>
                  <div><dt>类型</dt><dd>{{ form.type }}</dd></div>
                  <div><dt>显示名称</dt><dd>{{ form.displayName || '—' }}</dd></div>
                  <div><dt>Secret</dt><dd>{{ form.type === 'Public' ? '不使用' : isEditing && !form.clientSecret ? '保持现有' : '将提交' }}</dd></div>
                  <div><dt>Scopes</dt><dd>{{ form.scopes.join(', ') || '—' }}</dd></div>
                  <div><dt>Grant Types</dt><dd>{{ form.grantTypes.join(', ') || '—' }}</dd></div>
                  <div><dt>Redirect URIs</dt><dd>{{ normalizeValues(form.redirectUris).length }} 个</dd></div>
                  <div><dt>Post Logout URIs</dt><dd>{{ normalizeValues(form.postLogoutRedirectUris).length }} 个</dd></div>
                </dl>
              </div>
            </section>
          </main>
        </div>

        <footer class="client-editor-footer">
          <NButton quaternary :disabled="saving" @click="editorVisible = false">取消</NButton>
          <div class="editor-footer-right">
            <NButton v-if="editorStep > 1" :disabled="saving" @click="previousStep">上一步</NButton>
            <NButton v-if="editorStep < 4" type="primary" :disabled="saving" @click="nextStep">下一步</NButton>
            <NButton v-else type="primary" :loading="saving" @click="save">{{ isEditing ? '保存修改' : '创建客户端' }}</NButton>
          </div>
        </footer>
      </div>
    </NModal>

    <NModal v-model:show="detailVisible" preset="card" style="width:min(calc(100vw - 24px),720px)" title="客户端详情">
      <div v-if="detailLoading" class="detail-loading"><NSpin size="small" /></div>
      <div v-if="detailClient" class="client-detail">
        <div class="detail-client-header">
          <div v-if="detailClient.hasLogo" class="client-logo detail-logo"><img :src="`/api/clients/${detailClient.id}/logo`" alt="" /></div>
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

    <NModal v-model:show="logoVisible" preset="card" style="width:min(calc(100vw - 24px),460px)" title="更新客户端 Logo">
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
.client-guide strong { flex-shrink: 0; color: var(--text-primary); }
.client-table { min-width: 940px; }
.client-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
.client-cell-copy { min-width: 0; max-width: 250px; display: flex; flex-direction: column; gap: 1px; }
.client-cell-copy strong { font-size: 13px; font-weight: 650; }
.client-cell-copy span { font-size: 11px; color: var(--text-tertiary); }
.client-logo, .client-logo-placeholder { width: 32px; height: 32px; flex-shrink: 0; border: 1px solid var(--border); border-radius: 5px; background: var(--surface-sunken); }
.client-logo { overflow: hidden; }
.client-logo img { width: 100%; height: 100%; object-fit: contain; }
.client-logo-placeholder { display: flex; align-items: center; justify-content: center; color: var(--text-tertiary); font-weight: 650; }
.compact-stack { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.uri-summary { max-width: 270px; }
.uri-summary > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-actions { display: inline-flex; align-items: center; justify-content: flex-end; gap: 2px; }
.empty-clients { min-height: 260px; }

.client-editor-dialog {
  width: min(1040px, calc(100vw - 40px));
  height: min(760px, calc(100vh - 40px));
  max-height: calc(100vh - 40px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  background: var(--surface);
  color: var(--text-primary);
  box-shadow: var(--shadow-lg);
}
.client-editor-header { flex: 0 0 auto; display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 18px 20px; border-bottom: 1px solid var(--border); }
.client-editor-header h2 { margin: 0; font-size: 16px; font-weight: 650; }
.client-editor-header p { margin: 4px 0 0; color: var(--text-tertiary); font-size: 12px; line-height: 1.5; }
.editor-close { width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid transparent; border-radius: var(--radius-sm); background: transparent; color: var(--text-tertiary); cursor: pointer; font-size: 18px; }
.editor-close:hover:not(:disabled) { border-color: var(--border); background: var(--surface-hover); color: var(--text-primary); }
.client-editor-layout { flex: 1; min-height: 0; display: grid; grid-template-columns: 210px minmax(0, 1fr); }
.client-editor-steps { min-height: 0; padding: 14px 10px; border-right: 1px solid var(--border); background: var(--surface-sunken); overflow-y: auto; }
.client-editor-steps button { width: 100%; display: flex; align-items: flex-start; gap: 10px; padding: 10px; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--text-secondary); text-align: left; cursor: pointer; }
.client-editor-steps button:hover { background: var(--surface-hover); }
.client-editor-steps button.active { background: var(--surface-active); color: var(--text-primary); }
.step-number { width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; border: 1px solid var(--border-strong); border-radius: 50%; font-size: 10px; font-weight: 700; }
.client-editor-steps button.active .step-number, .client-editor-steps button.done .step-number { border-color: var(--accent); color: var(--accent); }
.step-copy { min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.step-copy strong { font-size: 12px; font-weight: 650; }
.step-copy small { color: var(--text-tertiary); font-size: 10px; line-height: 1.35; }
.client-editor-content { min-width: 0; min-height: 0; overflow-y: auto; padding: 22px 24px 28px; }
.editor-section { display: flex; flex-direction: column; gap: 20px; max-width: 760px; }
.section-heading { padding-bottom: 2px; }
.section-kicker { display: block; margin-bottom: 3px; color: var(--text-tertiary); font-size: 9px; font-weight: 700; letter-spacing: .08em; }
.section-heading h3 { margin: 0; font-size: 16px; font-weight: 650; }
.section-heading p { margin: 5px 0 0; max-width: 680px; color: var(--text-tertiary); font-size: 12px; line-height: 1.55; }
.form-grid.two-col { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
.client-type-group { display: inline-flex; }
.readonly-value { min-height: 38px; display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-sunken); }
.readonly-value > span:last-child { font-size: 11px; color: var(--text-tertiary); }
.secret-input-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto auto; gap: 7px; }
.field-heading-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.field-heading-row .field-label { margin-bottom: 1px; }
.uri-editor-list { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.uri-editor-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
.empty-uri-row { margin-top: 10px; padding: 10px 12px; border: 1px dashed var(--border-strong); border-radius: var(--radius-sm); color: var(--text-tertiary); font-size: 12px; }
.field-warning { display: block; margin-top: 7px; color: var(--warning); font-size: 12px; }
.setting-line { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-sunken); }
.setting-line > div { display: flex; flex-direction: column; gap: 2px; }
.setting-line strong { font-size: 12px; font-weight: 650; }
.setting-line span { color: var(--text-tertiary); font-size: 11px; }
.review-box { padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-sunken); }
.review-box dl { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 18px; margin: 0; }
.review-box dl > div { min-width: 0; }
.review-box dt { font-size: 10px; color: var(--text-tertiary); }
.review-box dd { margin: 2px 0 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); font-size: 12px; }
.client-editor-footer { flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 18px; border-top: 1px solid var(--border); background: var(--surface); }
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

@media (max-width: 760px) {
  .client-editor-dialog { width: calc(100vw - 16px); height: calc(100vh - 16px); max-height: calc(100vh - 16px); }
  .client-editor-header { padding: 14px 14px 12px; }
  .client-editor-layout { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); }
  .client-editor-steps { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); padding: 8px; border-right: 0; border-bottom: 1px solid var(--border); overflow: visible; }
  .client-editor-steps button { justify-content: center; padding: 7px 4px; }
  .step-copy { display: none; }
  .client-editor-content { padding: 18px 14px 24px; }
  .form-grid.two-col, .review-box dl, .detail-grid { grid-template-columns: 1fr; }
  .detail-wide { grid-column: auto; }
  .secret-input-row { grid-template-columns: repeat(3, 1fr); }
  .secret-input-row :deep(.n-input) { grid-column: 1 / -1; }
  .client-editor-footer { padding: 10px 12px; }
}
@media (max-width: 520px) {
  .client-guide { align-items: flex-start; flex-direction: column; gap: 5px; }
  .field-heading-row { flex-direction: column; }
  .uri-editor-row { grid-template-columns: 1fr; }
  .editor-footer-right { flex: 1; justify-content: flex-end; }
}
</style>
