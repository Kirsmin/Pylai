<script setup lang="ts">
import { computed } from 'vue'
import { formatUtc8 } from '@/utils/time'

const props = withDefaults(defineProps<{
  value?: string | number | Date | null
  empty?: string
}>(), {
  empty: '—'
})

const text = computed(() => formatUtc8(props.value) ?? props.empty)
</script>

<template>
  <span class="mono time-text">{{ text }}</span>
</template>
