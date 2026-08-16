<script setup lang="ts">
import { ref, nextTick, watch, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NInput, NAlert, NIcon } from 'naive-ui'
import { LockResetFilled } from '@vicons/material'
import { FileDoneOutlined } from '@vicons/antd'
import { api, ApiError } from '@/utils/api'
import { useAuthStore } from '@/stores/auth'
import type { PasswordPolicy } from '@/types/api'
import Dock from '@/components/Dock.vue'

type PageState = 'oldPassword' | 'newPassword' | 'completed' | 'needLogin'

const router = useRouter()
const authStore = useAuthStore()

const state = ref<PageState>('oldPassword')
const loading = ref(false)

const done = computed(() => state.value === 'completed')

const oldPassword = ref('')
const oldPasswordError = ref('')
const oldPasswordRef = ref<InstanceType<typeof NInput> | null>(null)

const password = ref('')
const passwordPolicy = ref<PasswordPolicy>({
  minLength: 8,
  requireDigit: true,
  requireLowercase: false,
  requireUppercase: false,
  requireNonAlphanumeric: false
})
const passwordSubmitError = ref('')
const passwordNativeRef = ref<InstanceType<typeof NInput> | null>(null)
const flashingRuleKeys = ref<Set<string>>(new Set())

onMounted(() => {
  if (!authStore.isAuthenticated) {
    state.value = 'needLogin'
  } else {
    nextTick(() => {
      oldPasswordRef.value?.focus()
    })
  }
})

function handleOldPasswordInput(value: string) {
  let cleaned = ''
  for (const char of value) {
    if (!(char.trim() === '' || (char.charCodeAt(0) >= 0 && char.charCodeAt(0) <= 31) || char.charCodeAt(0) === 127)) {
      cleaned += char
    }
  }
  oldPassword.value = cleaned
  oldPasswordError.value = ''
}

function goNewPassword() {
  // 旧密码本地校验（非空）通过后进入新密码步骤；真实校验在提交 change-password 时发生
  state.value = 'newPassword'
  password.value = ''
  passwordSubmitError.value = ''
  fetchPasswordPolicy()
  nextTick(() => {
    passwordNativeRef.value?.focus()
  })
}

async function handlePasswordSubmit() {
  const errors = validatePassword()
  if (errors.length > 0) {
    flashUnsatisfiedRules(passwordRequiredRules.value.filter(r => !r.satisfied).map(r => r.key))
    return
  }
  loading.value = true
  passwordSubmitError.value = ''
  try {
    const data = await api('/api/auth/account/change-password', {
      method: 'POST',
      body: JSON.stringify({
        currentPassword: oldPassword.value,
        newPassword: password.value
      })
    })
    if (data.success) {
      state.value = 'completed'
      // 修改成功后服务端吊销全部会话（含当前），本地凭据一并清除
      await authStore.logout()
    } else {
      passwordSubmitError.value = data.error || '修改失败，请重试'
    }
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401) {
        // 会话已失效（可能已被服务端吊销）→ 清除本地凭据并提示重新登录
        await authStore.logout()
        state.value = 'needLogin'
      } else if (e.errorCode === 'wrong_code') {
        // 旧密码错误 → 回到旧密码步骤重新输入
        state.value = 'oldPassword'
        oldPasswordError.value = e.data?.error || '当前密码错误。'
        oldPassword.value = ''
        nextTick(() => {
          oldPasswordRef.value?.focus()
        })
      } else if (e.errorCode === 'invalid_password') {
        passwordSubmitError.value = e.data?.error || '新密码不符合密码策略。'
        flashUnsatisfiedRules(passwordRequiredRules.value.filter(r => !r.satisfied).map(r => r.key))
      } else {
        passwordSubmitError.value = e.data?.error || '修改失败，请重试'
      }
    } else {
      passwordSubmitError.value = '网络错误，请重试'
    }
  } finally {
    loading.value = false
  }
}

async function fetchPasswordPolicy() {
  try {
    const data = await api('/api/auth/password-policy')
    passwordPolicy.value = {
      minLength: (data.minLength as number) ?? 6,
      requireDigit: (data.requireDigit as boolean) ?? false,
      requireLowercase: (data.requireLowercase as boolean) ?? false,
      requireUppercase: (data.requireUppercase as boolean) ?? false,
      requireNonAlphanumeric: (data.requireNonAlphanumeric as boolean) ?? false
    }
  } catch {
  }
}

function handlePasswordInput(value: string) {
  let cleaned = ''
  for (const char of value) {
    if (!(char.trim() === '' || (char.charCodeAt(0) >= 0 && char.charCodeAt(0) <= 31) || char.charCodeAt(0) === 127)) {
      cleaned += char
    }
  }
  password.value = cleaned
}

function hasInvalidChars(str: string): boolean {
  for (const char of str) {
    if (char.trim() === '' || (char.charCodeAt(0) >= 0 && char.charCodeAt(0) <= 31) || char.charCodeAt(0) === 127) {
      return true
    }
  }
  return false
}

function validatePassword(): number[] {
  const errors: number[] = []
  const p = passwordPolicy.value
  if (password.value.length < p.minLength) errors.push(0)
  if (p.requireDigit && !/\d/.test(password.value)) errors.push(1)
  if (p.requireLowercase && !/[a-z]/.test(password.value)) errors.push(1)
  if (p.requireUppercase && !/[A-Z]/.test(password.value)) errors.push(1)
  if (p.requireNonAlphanumeric && !/[^a-zA-Z0-9]/.test(password.value)) errors.push(1)
  if (hasInvalidChars(password.value)) errors.push(3)
  return errors
}

const passwordValid = computed(() => validatePassword().length === 0)

const passwordSuggestionRules = computed(() => {
  const p = passwordPolicy.value
  const rules: { key: string; text: string }[] = []
  if (!p.requireDigit) rules.push({ key: 'suggest-digit', text: '数字' })
  if (!p.requireLowercase) rules.push({ key: 'suggest-lowercase', text: '小写字母' })
  if (!p.requireUppercase) rules.push({ key: 'suggest-uppercase', text: '大写字母' })
  if (!p.requireNonAlphanumeric) rules.push({ key: 'suggest-special', text: '特殊字符' })
  rules.push({ key: 'suggest-chinese', text: '支持中文' })
  rules.push({ key: 'suggest-invalidChars', text: '无空格和控制字符' })
  return rules
})

const passwordRequiredRules = computed(() => {
  const p = passwordPolicy.value
  const rules: { key: string; text: string; satisfied: boolean }[] = []
  rules.push({ key: 'minLength', text: `至少 ${p.minLength} 个字符`, satisfied: password.value.length >= p.minLength })
  if (p.requireDigit) rules.push({ key: 'digit', text: '必须包括数字', satisfied: /\d/.test(password.value) })
  if (p.requireLowercase) rules.push({ key: 'lowercase', text: '必须包括小写字母', satisfied: /[a-z]/.test(password.value) })
  if (p.requireUppercase) rules.push({ key: 'uppercase', text: '必须包括大写字母', satisfied: /[A-Z]/.test(password.value) })
  if (p.requireNonAlphanumeric) rules.push({ key: 'special', text: '必须包括特殊字符', satisfied: /[^a-zA-Z0-9]/.test(password.value) })
  return rules
})

function flashUnsatisfiedRules(keys: string[], duration = 600) {
  flashingRuleKeys.value = new Set(keys)
  setTimeout(() => {
    flashingRuleKeys.value = new Set()
  }, duration)
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Enter') return
  if (state.value === 'oldPassword' && oldPassword.value.length > 0) {
    goNewPassword()
  } else if (state.value === 'newPassword') {
    handlePasswordSubmit()
  }
}

watch(state, (newState) => {
  if (newState === 'oldPassword') nextTick(() => {
    oldPasswordRef.value?.focus()
  })
  if (newState === 'newPassword') {
    fetchPasswordPolicy()
    nextTick(() => {
      passwordNativeRef.value?.focus()
    })
  }
})
</script>

<template>
  <div class="page-shell">
    <div class="page-wrapper">
      <div class="page-card">
        <div class="reset-content">
          <h1 class="reset-title">
            <NIcon class="reset-title-icon" :component="done ? FileDoneOutlined : LockResetFilled" />
            <span>Pylai</span>
          </h1>

          <template v-if="state === 'oldPassword'">
            <p class="reset-subtitle">验证旧密码</p>
            <p v-if="oldPasswordError" class="error-msg">{{ oldPasswordError }}</p>
            <NInput
              ref="oldPasswordRef"
              v-model:value="oldPassword"
              type="password"
              size="large"
              placeholder="当前密码"
              class="underline-input"
              autofocus
              :input-props="{ onKeydown: handleKeyDown, autocomplete: 'current-password' }"
              @input="handleOldPasswordInput"
            />
            <NButton
              v-if="oldPassword.length > 0 && !loading"
              type="success"
              size="large"
              circle
              class="submit-btn"
              @click="goNewPassword"
            >
              -&gt;
            </NButton>
            <NButton v-else-if="loading" type="success" size="large" circle class="submit-btn" loading />
          </template>

          <template v-else-if="state === 'newPassword'">
            <p class="reset-subtitle">设置新密码</p>
            <NInput
              ref="passwordNativeRef"
              v-model:value="password"
              type="password"
              size="large"
              placeholder="新密码"
              class="underline-input"
              autofocus
              :input-props="{ onKeydown: handleKeyDown, autocomplete: 'new-password' }"
              @input="handlePasswordInput"
            />

            <div class="rules-text-list">
              <div
                v-for="item in passwordSuggestionRules"
                :key="item.key"
                class="rule-text-item rule-text-suggestion"
              >
                <span class="rule-text-symbol">*</span>
                <span class="rule-text-content">{{ item.text }}</span>
              </div>
              <div
                v-for="item in passwordRequiredRules"
                :key="item.key"
                class="rule-text-item"
                :class="{ 'rule-text-satisfied': item.satisfied, 'rule-highlight': flashingRuleKeys.has(item.key) }"
              >
                <span class="rule-text-symbol">{{ item.satisfied ? '✓' : '○' }}</span>
                <span class="rule-text-content">{{ item.text }}</span>
              </div>
            </div>

            <p v-if="passwordSubmitError" class="error-msg">{{ passwordSubmitError }}</p>

            <NButton
              v-if="passwordValid && !loading"
              type="success"
              size="large"
              circle
              class="submit-btn"
              @click="handlePasswordSubmit"
            >
              -&gt;
            </NButton>
            <NButton v-else-if="loading" type="success" size="large" circle class="submit-btn" loading />

          </template>

          <template v-else-if="state === 'completed'">
            <p class="reset-done-text">修改完成</p>
            <NButton
              type="success"
              size="large"
              circle
              class="submit-btn"
              @click="router.push('/login')"
            >
              -&gt;
            </NButton>
          </template>

          <template v-else-if="state === 'needLogin'">
            <p class="reset-subtitle">修改登录密码</p>
            <NAlert
              type="warning"
              :show-icon="true"
              :bordered="false"
              style="width: 100%; max-width: 420px; text-align: left;"
            >
              <template #header>
                <span style="font-weight: 600;">请先登录</span>
              </template>
              <p style="margin: 4px 0;">修改登录密码需要先登录 Pylai 账号。</p>
            </NAlert>
            <NButton
              type="success"
              size="large"
              circle
              class="submit-btn"
              @click="router.push('/login')"
            >
              -&gt;
            </NButton>
          </template>
        </div>
      </div>
      <Dock />
    </div>
  </div>
</template>

<style scoped>




.reset-content {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 48px 32px;
  text-align: center;
}

.reset-title {
  margin: 0;
  font-weight: 600;
  font-size: 32px;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.reset-title-icon {
  font-size: 32px;
  color: var(--text-primary);
}

.reset-subtitle {
  margin: 0;
  font-size: 16px;
  color: var(--text-secondary);
}

.reset-done-text {
  margin: 0;
  font-size: 16px;
  color: var(--text-primary);
}

.rules-text-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  width: 100%;
  max-width: 280px;
  margin-bottom: 4px;
  text-align: left;
}

.rule-text-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-primary);
  position: relative;
  line-height: 1.5;
}

.rule-text-satisfied {
  color: var(--text-tertiary);
}

.rule-text-symbol {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  flex-shrink: 0;
  text-align: center;
  font-size: 15px;
  line-height: 1;
  font-family: 'Segoe UI Symbol', 'Courier New', Consolas, 'Noto Sans Symbols 2', monospace;
}

.rule-text-item::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  width: 100%;
  height: 2px;
  background: var(--highlight-color);
  opacity: 0;
  border-radius: 1px;
}

.rule-text-item.rule-highlight::after {
  animation: highlightLine 0.6s ease forwards;
}

@keyframes highlightLine {
  0% {
    opacity: 0;
  }
  25% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
  75% {
    opacity: 1;
  }
  100% {
    opacity: 0;
  }
}

@media (max-width: 640px) {
  .reset-content {
    gap: 12px;
    padding: 24px 16px;
  }

  .reset-title {
    font-size: 24px;
  }

  .reset-subtitle {
    font-size: 14px;
  }
}
</style>
