<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { NSpin, NButton, NAlert, NIcon } from 'naive-ui'
import { Movement, ArrowsHorizontal } from '@vicons/carbon'
import { ShieldCheckmark24Regular, ShieldError24Regular } from '@vicons/fluent'
import { api, ApiError } from '@/utils/api'
import type { ScopeInfo } from '@/types/api'
import Dock from '@/components/Dock.vue'
import AltchaWidget from '@/components/AltchaWidget.vue'

interface AuthorizeRequest {
  displayName: string
  description?: string | null
  isFajorCertified?: boolean
  logoUrl?: string | null
  scopes: ScopeInfo[]
  existingScopes?: string[]
  user?: { displayName: string } | null
}

const route = useRoute()

const id = ref('')
const request = ref<AuthorizeRequest | null>(null)
const loading = ref(true)
const invalid = ref(false)
const needsLogin = ref(false)
const agreeLoading = ref(false)
const rejectLoading = ref(false)
const submitError = ref('')
const currentPage = ref(0)
const logoFailed = ref(false)

const altchaPayload = ref<string | null>(null)

const scopesPerPage = 5

const appName = computed(() => request.value?.displayName ?? '')

const existingNames = computed(
  () => new Set(request.value?.existingScopes ?? [])
)

const hasExisting = computed(() => existingNames.value.size > 0)

const existingScopes = computed(() =>
  (request.value?.scopes ?? []).filter((s) => existingNames.value.has(s.name))
)

const newScopes = computed(() =>
  (request.value?.scopes ?? []).filter((s) => !existingNames.value.has(s.name))
)

const pageCount = computed(() =>
  Math.ceil((newScopes.value.length) / scopesPerPage)
)

const pagedScopes = computed(() => {
  const scopes = newScopes.value
  const start = currentPage.value * scopesPerPage
  return scopes.slice(start, start + scopesPerPage)
})

function goLogin() {
  const returnUrl = encodeURIComponent(window.location.pathname + window.location.search)
  window.location.href = `/login?return_url=${returnUrl}`
}

async function loadRequest() {
  const queryId = route.query.requestId
  if (typeof queryId !== 'string' || !queryId) {
    invalid.value = true
    loading.value = false
    return
  }

  id.value = queryId

  try {
    const data = await api<AuthorizeRequest>(`/api/auth/authorize-request?requestId=${encodeURIComponent(id.value)}`)
    request.value = data
    currentPage.value = 0
    logoFailed.value = false

    if (!data.user) {
      needsLogin.value = true
    }
  } catch {
    invalid.value = true
  } finally {
    loading.value = false
  }
}


function isSafeRedirectUrl(url: string, approved: boolean): boolean {
  try {
    const u = new URL(url, window.location.origin)
    if (approved) {
      return u.origin === window.location.origin && u.pathname === '/connect/authorize'
    }
    return u.protocol === 'https:' || u.protocol === 'http:'
  } catch {
    return false
  }
}

async function submitConsent(approved: boolean) {
  submitError.value = ''
  if (approved) {
    agreeLoading.value = true
  } else {
    rejectLoading.value = true
  }

  try {
    const data = await api<{ redirectUrl?: string }>('/api/auth/authorize-request/consent', {
      method: 'POST',
      body: JSON.stringify({ requestId: id.value, approved, altcha: altchaPayload.value ? JSON.parse(altchaPayload.value) : null })
    })

    if (data.redirectUrl) {
      if (!isSafeRedirectUrl(data.redirectUrl, approved)) {
        submitError.value = '返回地址校验失败，请返回应用重试'
        return
      }
      window.location.href = data.redirectUrl
    } else {
      submitError.value = '返回地址缺失，请返回应用重试'
    }
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      needsLogin.value = true
      return
    }
    if (e instanceof ApiError && e.errorCode === 'altcha_invalid') {
      submitError.value = e.data?.error || '验证失败，请刷新页面重试。'
      altchaPayload.value = null
    } else {
      submitError.value = e instanceof ApiError
        ? (e.data?.error || '提交失败，请重试')
        : '网络错误，请重试'
    }
  } finally {
    agreeLoading.value = false
    rejectLoading.value = false
  }
}

function handleAgree() {
  submitConsent(true)
}

function handleReject() {
  submitConsent(false)
}

onMounted(() => {
  loadRequest()
})
</script>

<template>
  <div class="page-shell">
    <div class="page-wrapper">
      <div class="page-card">
        <div class="auth-content">
          <div v-if="loading" class="loading-wrap">
            <NSpin />
          </div>

          <template v-else>
            <NAlert
              v-if="invalid"
              type="error"
              :show-icon="true"
              :bordered="false"
              style="width: 100%; max-width: 420px; text-align: left;"
            >
              <template #header>
                <span style="font-weight: 600;">授权请求无效</span>
              </template>
              <p style="margin: 4px 0;">授权请求无效或已过期，请返回应用重试。</p>
            </NAlert>

            <template v-else-if="request">
              <div class="app-header">
                <span class="app-header-text">Pylai</span>
                <NIcon class="app-header-icon" :component="ArrowsHorizontal" />
                <img
                  v-if="request.logoUrl && !logoFailed"
                  :src="request.logoUrl"
                  alt=""
                  class="app-header-logo"
                  @error="logoFailed = true"
                />
                <span class="app-header-name" :title="appName">{{ appName }}</span>
              </div>

              <div class="divider" />

              <div class="fajor-row">
                <NIcon
                  class="fajor-icon"
                  :class="request.isFajorCertified ? 'fajor-safe' : 'fajor-warn'"
                  :component="request.isFajorCertified ? ShieldCheckmark24Regular : ShieldError24Regular"
                />
                <span class="fajor-text">
                  {{ request.isFajorCertified ? '该应用已经过 Fajor 审核。' : '该应用未经 Fajor 审核，也不是 Fajor 发布的应用。' }}
                </span>
              </div>

              <p class="scope-intro">
                应用 <strong class="app-name-em">{{ appName }}</strong>
                <template v-if="hasExisting">申请新增以下权限：</template>
                <template v-else>需要访问下述信息：</template>
              </p>

              <div v-if="existingScopes.length" class="scope-list">
                <div class="scope-group-title">已拥有权限</div>
                <div
                  v-for="scope in existingScopes"
                  :key="scope.name"
                  class="scope-item scope-existing"
                >
                  <span class="scope-bullet">-</span>
                  <span class="scope-line">
                    <span class="scope-name">{{ scope.displayName }}</span>
                    <span class="scope-sep">：</span>
                    <span class="scope-desc">{{ scope.description }}</span>
                    <span class="scope-tag">已授权</span>
                  </span>
                </div>
              </div>

              <div v-if="newScopes.length" class="scope-list">
                <div v-if="existingScopes.length" class="scope-group-title">本次新增</div>
                <div
                  v-for="scope in pagedScopes"
                  :key="scope.name"
                  class="scope-item"
                >
                  <span class="scope-bullet">-</span>
                  <span class="scope-line">
                    <span class="scope-name">{{ scope.displayName }}</span>
                    <span class="scope-sep">：</span>
                    <span class="scope-desc">{{ scope.description }}</span>
                  </span>
                </div>
              </div>

              <div v-if="pageCount > 1" class="scope-pagination">
                <NButton
                  quaternary
                  size="small"
                  :disabled="currentPage === 0"
                  @click="currentPage--"
                >
                  &lt;-
                </NButton>
                <span class="page-indicator">{{ currentPage + 1 }} / {{ pageCount }}</span>
                <NButton
                  quaternary
                  size="small"
                  :disabled="currentPage === pageCount - 1"
                  @click="currentPage++"
                >
                  -&gt;
                </NButton>
              </div>

              <div v-if="needsLogin" class="login-prompt">
                <p class="hint-text">请先登录</p>
                <NButton
                  type="success"
                  size="large"
                  :disabled="agreeLoading || rejectLoading"
                  @click="goLogin"
                >
                  登录
                </NButton>
              </div>

              <template v-else>
                <NAlert
                  v-if="submitError"
                  type="error"
                  :show-icon="true"
                  :bordered="false"
                  style="width: 100%; max-width: 420px; text-align: left;"
                >
                  <template #header>
                    <span style="font-weight: 600;">提交失败</span>
                  </template>
                  <p style="margin: 4px 0;">{{ submitError }}</p>
                </NAlert>

                <AltchaWidget v-model="altchaPayload" auto="onsubmit" hide-footer />

                <div class="btn-group">
                  <NButton
                    dashed
                    type="error"
                    size="large"
                    :disabled="agreeLoading || rejectLoading"
                    :loading="rejectLoading"
                    @click="handleReject"
                  >
                    {{ rejectLoading ? '处理中...' : '拒绝' }}
                  </NButton>
                  <NButton
                    type="success"
                    size="large"
                    :disabled="agreeLoading || rejectLoading"
                    :loading="agreeLoading"
                    @click="handleAgree"
                  >
                    同意
                  </NButton>
                </div>
              </template>
            </template>
          </template>
        </div>
      </div>

      <Dock>
        <template #spacer>
          <NIcon class="dock-context-icon" :component="Movement" />
          <span class="dock-context-text">连接第三方应用</span>
        </template>
      </Dock>
    </div>
  </div>
</template>

<style scoped>




.auth-content {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 14px;
  padding: 28px 28px 32px;
  text-align: left;
}

.loading-wrap {
  padding: 40px 0;
  text-align: center;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
}

.app-header-text {
  flex-shrink: 0;
}

.app-header-icon {
  flex-shrink: 0;
  font-size: 16px;
  color: var(--text-tertiary);
}

.app-header-logo {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  border-radius: 4px;
  object-fit: contain;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
}

.app-header-name {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.divider {
  width: 100%;
  height: 1px;
  background: var(--input-border);
  margin: 2px 0;
}

.fajor-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.fajor-icon {
  flex-shrink: 0;
  font-size: 18px;
  margin-top: 1px;
}

.fajor-safe {
  color: var(--success-color);
}

.fajor-warn {
  color: var(--highlight-color);
}

.scope-intro {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
}

.app-name-em {
  font-weight: 600;
}

.scope-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  max-width: 100%;
  text-align: left;
}

.scope-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-primary);
}

.scope-bullet {
  flex-shrink: 0;
  width: 12px;
  text-align: center;
  color: var(--text-secondary);
  font-weight: 600;
}

.scope-line {
  flex: 1;
  min-width: 0;
}

.scope-name {
  font-weight: 600;
}

.scope-sep {
  color: var(--text-tertiary);
}

.scope-desc {
  color: var(--text-secondary);
}

.scope-group-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-tertiary);
  margin-top: 4px;
}

.scope-existing .scope-name {
  color: var(--text-tertiary);
}

.scope-tag {
  margin-left: 6px;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
  color: var(--text-tertiary);
}

.scope-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  width: 100%;
  font-size: 13px;
}

.page-indicator {
  color: var(--text-tertiary);
  min-width: 48px;
  text-align: center;
}

.hint-text {
  margin: 0;
  font-size: 14px;
  color: var(--text-secondary);
}

.login-prompt {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  margin-top: 4px;
}

.btn-group {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
  flex-wrap: wrap;
}

.dock-context-icon {
  font-size: 16px;
}

.dock-context-text {
  font-size: 14px;
  font-weight: 500;
}

@media (max-width: 640px) {
  .auth-content {
    gap: 12px;
    padding: 24px 20px 28px;
  }

  .app-header {
    font-size: 15px;
  }

  .btn-group {
    justify-content: stretch;
    width: 100%;
  }

  .btn-group :deep(.n-button) {
    flex: 1;
  }
}
</style>
