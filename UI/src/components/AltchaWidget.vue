<template>
  <altcha-widget
    v-if="enabled"
    ref="widgetRef"
    :challenge="challengeData"
    :auto="auto"
    :hidefooter="hideFooter"
    @statechange="onStateChange"
    style="margin-top: 8px;"
  />
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { getPublicConfigSnapshot, loadPublicConfig } from '@/utils/publicConfig'

interface AltchaStateChangeDetail {
  state?: string
  payload?: unknown
}

interface AltchaVerifyResult {
  payload?: unknown
}

interface AltchaWidgetElement extends HTMLElement {
  verify?: () => Promise<AltchaVerifyResult | null>
  reset?: () => void
}

interface AltchaVerificationResult {
  required: boolean
  payload: string | null
}

const props = withDefaults(defineProps<{
  modelValue?: string | null
  auto?: string
  hideFooter?: boolean
}>(), {
  modelValue: null,
  auto: 'off',
  hideFooter: true,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | null): void
  (e: 'verified', payload: string): void
  (e: 'error', message: string): void
}>()

const challengeUrl = `${window.location.origin}${import.meta.env.VITE_API_BASE || ''}/api/altcha/challenge`
const enabled = ref(getPublicConfigSnapshot()?.altchaEnabled ?? true)
const internalPayload = ref<string | null>(props.modelValue ?? null)
const widgetRef = ref<AltchaWidgetElement | null>(null)
const challengeData = ref<object | null>(null)

async function fetchChallenge() {
  try {
    const response = await fetch(challengeUrl, { credentials: 'include' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    challengeData.value = await response.json()
  } catch (err) {
    emit('error', '无法加载验证挑战，请刷新页面重试。')
  }
}

function decodePayload(payload: unknown): string | null {
  if (typeof payload !== 'string' || !payload.trim()) return null

  const raw = payload.trim()
  if (raw.startsWith('{')) return raw

  try {
    const decoded = atob(raw)
    if (decoded.trim().startsWith('{')) return decoded
  } catch {
    // 保持兼容
  }
  return raw
}

function commitPayload(payload: string | null) {
  if (internalPayload.value === payload) return
  internalPayload.value = payload
  emit('update:modelValue', payload)
}

function onStateChange(ev: Event) {
  const detail = (ev as CustomEvent<AltchaStateChangeDetail>).detail ?? {}
  const state = detail.state

  if (state === 'verified') {
    const payload = decodePayload(detail.payload)
    if (payload) {
      commitPayload(payload)
      emit('verified', payload)
    }
  } else if (state === 'unverified') {
    commitPayload(null)
  } else if (state === 'error' || state === 'expired') {
    commitPayload(null)
    emit('error', state === 'expired' ? '人机验证已过期，请重试。' : '人机验证失败，请重试。')
  }
}

async function ensureVerified(): Promise<AltchaVerificationResult> {
  if (!enabled.value) return { required: false, payload: null }
  if (internalPayload.value) return { required: true, payload: internalPayload.value }

  const element = widgetRef.value
  if (!element?.verify) return { required: true, payload: null }

  let result: AltchaVerifyResult | null = null
  try {
    result = await element.verify()
  } catch {
    result = null
  }

  const payload = decodePayload(result?.payload) ?? internalPayload.value
  if (payload) {
    commitPayload(payload)
    emit('verified', payload)
  }
  return { required: true, payload }
}

function reset() {
  commitPayload(null)
  widgetRef.value?.reset?.()
  fetchChallenge()
}

watch(() => props.modelValue, (value) => {
  const next = value ?? null
  if (next === internalPayload.value) return
  internalPayload.value = next
  if (next === null) widgetRef.value?.reset?.()
})

watch(enabled, (value) => {
  if (!value) commitPayload(null)
})

onMounted(async () => {
  try {
    enabled.value = (await loadPublicConfig()).altchaEnabled
  } catch {
    enabled.value = true
  }
  if (enabled.value) {
    await fetchChallenge()
  }
})

defineExpose({ ensureVerified, reset })
</script>
