<template>
  <altcha-widget
    :challengeurl="challengeUrl"
    :auto="auto"
    :hidefooter="hideFooter"
    @statechange="onStateChange"
    style="margin-top: 8px;"
  />
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  modelValue?: string | null
  auto?: string
  hideFooter?: boolean
}>()

const emit = defineEmits(['update:modelValue', 'verified', 'error'])

const challengeUrl = `${import.meta.env.VITE_API_BASE || ''}/api/altcha/challenge`
const internalPayload = ref<string | null>(null)

function onStateChange(ev: CustomEvent) {
  const { state, payload } = ev.detail
  if (state === 'verified') {
    internalPayload.value = payload
    emit('update:modelValue', payload)
    emit('verified', payload)
  } else if (state === 'error') {
    emit('error')
  }
}

watch(() => props.modelValue, (val) => {
  if (val !== internalPayload.value) {
    internalPayload.value = val ?? null
  }
})
</script>
