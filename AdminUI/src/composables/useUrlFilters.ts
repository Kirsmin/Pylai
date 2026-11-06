import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export type FilterValues = Record<string, string | null>

/**
 * 列表筛选与分页同步 URL query。
 * 状态单一来源：用户操作只改写 URL，watch route.query 统一触发 onChange，
 * 因此刷新 / 分享 / 后退均可还原现场。筛选变更自动回到第 1 页。
 */
export function useUrlFilters(
  keys: string[],
  onChange: (filters: FilterValues, page: number) => void
) {
  const route = useRoute()
  const router = useRouter()

  const filters = ref<FilterValues>({})
  const page = ref(1)

  function readQuery(): { filters: FilterValues; page: number } {
    const q = route.query
    const next: FilterValues = {}
    for (const k of keys) {
      const raw = Array.isArray(q[k]) ? q[k][0] : q[k]
      next[k] = typeof raw === 'string' && raw.trim() !== '' ? raw : null
    }
    const rawPage = Array.isArray(q.page) ? q.page[0] : q.page
    const p = Number(rawPage)
    return { filters: next, page: Number.isInteger(p) && p > 0 ? p : 1 }
  }

  function toQuery(f: FilterValues, p: number): Record<string, string> {
    const query: Record<string, string> = {}
    for (const k of keys) {
      const v = f[k]
      if (v) query[k] = v
    }
    if (p > 1) query.page = String(p)
    return query
  }

  const initial = readQuery()
  filters.value = initial.filters
  page.value = initial.page

  /** patch 非空视为筛选变更（回到第 1 页）；纯分页请传 nextPage。 */
  async function apply(patch: FilterValues = {}, nextPage?: number) {
    const next = { ...filters.value, ...patch }
    const p = nextPage ?? (Object.keys(patch).length > 0 ? 1 : page.value)
    const query = toQuery(next, p)
    const same = JSON.stringify(query) === JSON.stringify(toQuery(filters.value, page.value))
    filters.value = next
    page.value = p
    // 目标与当前一致时 router.replace 不会触发 watcher，这里直接补发一次。
    if (same) onChange(next, p)
    else await router.replace({ query })
  }

  watch(
    () => route.query,
    () => {
      const current = readQuery()
      filters.value = current.filters
      page.value = current.page
      onChange(current.filters, current.page)
    }
  )

  return { filters, page, apply }
}
