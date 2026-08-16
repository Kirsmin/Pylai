const UTC8_OFFSET_MS = 8 * 60 * 60 * 1000

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function parseTimeValue(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : new Date(value.getTime())
  }

  if (typeof value === 'number') {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? null : date
  }

  const text = String(value).trim()
  if (!text) return null

  // 后端多处返回：yyyy-MM-dd HH:mm:ss UTC（该字符串表示的即为 UTC 时间）
  const serverUtc = text.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?: UTC)?$/)
  if (serverUtc) {
    const [, year, month, day, hour, minute, second] = serverUtc
    return new Date(Date.UTC(
      Number(year), Number(month) - 1, Number(day),
      Number(hour), Number(minute), Number(second)
    ))
  }

  const date = new Date(text)
  return Number.isNaN(date.getTime()) ? null : date
}

/** 把后端 UTC / ISO 时间格式化为 yyyy-MM-dd HH:mm:ss（UTC+8） */
export function formatUtc8(value: string | number | Date | null | undefined): string | null {
  const date = parseTimeValue(value)
  if (!date) return null

  const shifted = new Date(date.getTime() + UTC8_OFFSET_MS)
  return [
    `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`,
    `${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}:${pad(shifted.getUTCSeconds())}`
  ].join(' ')
}

/** 把 datetime-local 输入（按 UTC+8 墙钟时间解释）转为 UTC ISO 字符串 */
export function utc8ToIso(value: string | null | undefined): string | null {
  if (!value) return null
  const match = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?$/)
  if (!match) return null

  const [, year, month, day, hour, minute, second = '00'] = match
  const utcMs = Date.UTC(
    Number(year), Number(month) - 1, Number(day),
    Number(hour) - 8, Number(minute), Number(second)
  )
  return new Date(utcMs).toISOString()
}
