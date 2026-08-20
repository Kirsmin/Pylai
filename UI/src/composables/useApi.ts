import { ref, type Ref } from 'vue'
import { ApiError, api, apiFetch } from '@/utils/api'

export { ApiError, api, apiFetch }

export function useApiState<T>() {
  const data = ref<T | null>(null) as Ref<T | null>
  const loading = ref(false)
  const error = ref('')

  async function execute(request: Promise<T>): Promise<T | null> {
    loading.value = true
    error.value = ''

    try {
      const result = await request
      data.value = result
      return result
    } catch (err) {
      error.value = err instanceof ApiError ? err.message : '网络错误，请重试'
      console.error('[API] 请求失败', err)
      return null
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, execute }
}
