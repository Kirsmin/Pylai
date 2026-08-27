<script setup lang="ts">
import { ref, nextTick, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NInput, NAlert, NInputOtp, NIcon } from 'naive-ui'
import { LockResetFilled } from '@vicons/material'
import { FileDoneOutlined } from '@vicons/antd'
import { api, ApiError } from '@/utils/api'
import type { PasswordPolicy } from '@/types/api'
import Dock from '@/components/Dock.vue'
import AltchaWidget from '@/components/AltchaWidget.vue'

type PageState = 'email' | 'verifyCode' | 'password' | 'completed' | 'rateLimited'

const router = useRouter()

const state = ref<PageState>('email')
const loading = ref(false)

const done = computed(() => state.value === 'completed')

const email = ref('')
const transactionId = ref('')
const emailError = ref('')
const emailRef = ref<InstanceType<typeof NInput> | null>(null)

const verificationCode = ref<string[]>([])
const otpStatus = ref<'warning'>()
const otpDisabled = ref(false)

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

const altchaPayload = ref<string | null>(null)

function isValidEmail(str: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(str)
}

function handleEmailInput(value: string) {
  let cleaned = ''
  for (const char of value) {
    if (char.charCodeAt(0) > 31 && char.charCodeAt(0) !== 127 && char !== ' ') {
      cleaned += char
    }
  }
  email.value = cleaned
  emailError.value = ''
}

async function handleEmailSubmit() {
  if (loading.value) return
  if (!isValidEmail(email.value)) {
    emailError.value = '邮箱格式错误'
    return
  }
  loading.value = true
  try {
    // 防枚举：无论邮箱是否注册都返回同形 transactionId。
    const data = await api('/api/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email: email.value, altcha: altchaPayload.value ? JSON.parse(altchaPayload.value) : null })
    })
    transactionId.value = data.transactionId as string
    state.value = 'verifyCode'
    verificationCode.value = []
    otpStatus.value = undefined
    otpDisabled.value = false
    emailError.value = ''
    await nextTick()
  } catch (e) {
    if (e instanceof ApiError && e.errorCode === 'altcha_invalid') {
      emailError.value = e.message || '验证失败，请刷新页面重试。'
      altchaPayload.value = null
    } else if (e instanceof ApiError && e.status === 429) {
      state.value = 'rateLimited'
    } else {
      emailError.value = '网络错误，请重试'
    }
  } finally {
    loading.value = false
  }
}

function handleResend() {
  state.value = 'email'
  transactionId.value = ''
  emailError.value = ''
  verificationCode.value = []
  otpStatus.value = undefined
  otpDisabled.value = false
  nextTick(() => {
    emailRef.value?.focus()
  })
}

function goPassword() {
  // 6 位验证码输入完整后进入新密码步骤（验证码与密码在最终提交时一并校验）
  state.value = 'password'
  password.value = ''
  passwordSubmitError.value = ''
  fetchPasswordPolicy()
  nextTick(() => {
    passwordNativeRef.value?.focus()
  })
}

function handleResetError(e: ApiError) {
  switch (e.errorCode) {
    case 'invalid_or_expired':
      state.value = 'verifyCode'
      otpStatus.value = 'warning'
      emailError.value = e.data?.error || '重置事务无效或已过期。'
      verificationCode.value = []
      break
    case 'invalid_password':
      passwordSubmitError.value = e.data?.error || '新密码不符合密码策略。'
      flashUnsatisfiedRules(passwordRequiredRules.value.filter(r => !r.satisfied).map(r => r.key))
      break
    case 'rate_limited':
      passwordSubmitError.value = e.data?.error || '请求过于频繁，请稍后重试。'
      break
    case 'altcha_invalid':
      passwordSubmitError.value = e.data?.error || '验证失败，请刷新页面重试。'
      altchaPayload.value = null
      break
    default:
      passwordSubmitError.value = e.data?.error || '重置失败，请重试'
  }
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
    const data = await api('/api/auth/reset-password', {
        method: 'POST',
        body: JSON.stringify({
          transactionId: transactionId.value,
          code: verificationCode.value.join(''),
        newPassword: password.value,
        altcha: altchaPayload.value ? JSON.parse(altchaPayload.value) : null
      })
    })
    if (data.success) {
      state.value = 'completed'
    } else {
      passwordSubmitError.value = data.error || '重置失败，请重试'
    }
  } catch (e) {
    if (e instanceof ApiError) {
      handleResetError(e)
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
  if (state.value === 'email' && email.value.includes('@')) {
    handleEmailSubmit()
  } else if (state.value === 'verifyCode' && verificationCode.value.length === 6) {
    goPassword()
  } else if (state.value === 'password') {
    handlePasswordSubmit()
  }
}

watch(state, (newState) => {
  if (newState === 'email') nextTick(() => {
    emailRef.value?.focus()
  })
  if (newState === 'verifyCode') nextTick(() => {
    const otpInput = document.querySelector('.n-input-otp input') as HTMLInputElement
    otpInput?.focus()
  })
  if (newState === 'password') {
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

          <p v-if="!done" class="reset-subtitle">重置密码</p>
          <p v-else class="reset-done-text">重置完成</p>

          <template v-if="state === 'rateLimited'">
            <NAlert
              type="warning"
              :show-icon="true"
              :bordered="false"
              style="width: 100%; max-width: 420px; text-align: left;"
            >
              <template #header>
                <span style="font-weight: 600;">请求过于频繁</span>
              </template>
              <p style="margin: 4px 0;">请求过于频繁，请稍后重试。</p>
              <p style="margin: 4px 0;">等待几分钟后刷新页面即可恢复。</p>
            </NAlert>
          </template>

          <template v-else-if="state === 'email'">
            <p v-if="emailError" class="error-msg">{{ emailError }}</p>

            <NInput
              ref="emailRef"
              v-model:value="email"
              type="text"
              size="large"
              placeholder="邮箱"
              class="underline-input"
              autofocus
              :input-props="{ onKeydown: handleKeyDown }"
              @input="handleEmailInput"
            />

            <AltchaWidget v-model="altchaPayload" auto="onsubmit" hide-footer />

            <NButton
              v-if="isValidEmail(email) && !loading"
              type="success"
              size="large"
              circle
              class="submit-btn"
              @click="handleEmailSubmit"
            >
              -&gt;
            </NButton>
            <NButton v-else-if="loading" type="success" size="large" circle class="submit-btn" loading />
          </template>

          <template v-else-if="state === 'verifyCode'">
            <p v-if="emailError" class="error-msg">{{ emailError }}</p>
            <p class="hint-msg">验证码已发送至 {{ email }}</p>
            <NInputOtp
              v-model:value="verificationCode"
              :length="6"
              :status="otpStatus"
              :disabled="otpDisabled"
              @complete="goPassword"
              @keydown="handleKeyDown"
            />
            <NButton
              v-if="!loading && verificationCode.length === 6 && !otpDisabled"
              type="success"
              size="large"
              circle
              class="submit-btn"
              @click="goPassword"
            >
              -&gt;
            </NButton>
            <NButton v-else-if="loading" type="success" size="large" circle class="submit-btn" loading />
            <NButton
              v-if="!loading && !otpDisabled"
              quaternary
              type="success"
              size="small"
              @click="handleResend"
            >
              重新获取验证码
            </NButton>
          </template>

          <template v-else-if="state === 'password'">
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

            <AltchaWidget v-model="altchaPayload" auto="onsubmit" hide-footer />

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

.hint-msg {
  margin: 0;
  font-size: 12px;
  color: var(--text-tertiary);
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
