// PKCE 工具：优先使用 Web Crypto（安全上下文），
// HTTP 开发环境缺少 crypto.subtle 时回退到纯 JS SHA-256。

export function randomString(bytes = 32): string {
  const cryptoApi = globalThis.crypto
  if (cryptoApi?.getRandomValues) {
    const data = new Uint8Array(bytes)
    cryptoApi.getRandomValues(data)
    return bytesToBase64Url(data)
  }

  // 极旧浏览器兜底：质量弱于 CSPRNG，仅用于保证可用性。
  const data = new Uint8Array(bytes)
  for (let i = 0; i < bytes; i++) {
    data[i] = Math.floor(Math.random() * 256)
  }
  return bytesToBase64Url(data)
}

export async function sha256Base64Url(value: string): Promise<string> {
  const subtle = globalThis.crypto?.subtle
  if (subtle) {
    try {
      const bytes = new TextEncoder().encode(value)
      const digest = await subtle.digest('SHA-256', bytes)
      return bytesToBase64Url(new Uint8Array(digest))
    } catch {
      // 继续走纯 JS 回退
    }
  }

  return bytesToBase64Url(hexToBytes(sha256Hex(value)))
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = ''
  bytes.forEach((b) => { binary += String.fromCharCode(b) })
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

function hexToBytes(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2)
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16)
  }
  return bytes
}

// 仅处理 ASCII 输入（PKCE verifier 由 base64url 字符组成）。
function sha256Hex(ascii: string): string {
  function rightRotate(value: number, amount: number): number {
    return (value >>> amount) | (value << (32 - amount))
  }

  const maxWord = Math.pow(2, 32)
  const hash: number[] = []
  const k: number[] = []
  const isComposite: Record<number, number> = {}

  let primeCounter = 0
  for (let candidate = 2; primeCounter < 64; candidate++) {
    if (!isComposite[candidate]) {
      for (let i = 0; i < 313; i += candidate) {
        isComposite[i] = candidate
      }
      hash[primeCounter] = (Math.pow(candidate, 0.5) * maxWord) | 0
      k[primeCounter++] = (Math.pow(candidate, 1 / 3) * maxWord) | 0
    }
  }

  const asciiBitLength = ascii.length * 8

  ascii += '\u0080'
  while (ascii.length % 64 !== 56) {
    ascii += '\u0000'
  }

  const words: number[] = []
  for (let i = 0; i < ascii.length; i++) {
    const code = ascii.charCodeAt(i)
    if (code > 0xff) throw new Error('PKCE SHA-256 仅支持 ASCII 输入')
    const wordIndex = i >> 2
    words[wordIndex] = (words[wordIndex] || 0) | (code << ((3 - i) % 4) * 8)
  }
  words[words.length] = (asciiBitLength / maxWord) | 0
  words[words.length] = asciiBitLength

  let working = hash
  for (let j = 0; j < words.length;) {
    const w = words.slice(j, j += 16)
    const oldHash = working
    working = working.slice(0, 8)

    for (let i = 0; i < 64; i++) {
      const w15 = w[i - 15] || 0
      const w2 = w[i - 2] || 0
      const a = working[0] || 0
      const e = working[4] || 0
      const temp1 = (working[7] || 0)
        + (rightRotate(e, 6) ^ rightRotate(e, 11) ^ rightRotate(e, 25))
        + ((e & (working[5] || 0)) ^ ((~e) & (working[6] || 0)))
        + (k[i] || 0)
        + (w[i] = (i < 16)
          ? (w[i] || 0)
          : ((
              (w[i - 16] || 0)
              + (rightRotate(w15, 7) ^ rightRotate(w15, 18) ^ (w15 >>> 3))
              + (w[i - 7] || 0)
              + (rightRotate(w2, 17) ^ rightRotate(w2, 19) ^ (w2 >>> 10))
            ) | 0))

      const temp2 = (rightRotate(a, 2) ^ rightRotate(a, 13) ^ rightRotate(a, 22))
        + ((a & (working[1] || 0)) ^ (a & (working[2] || 0)) ^ ((working[1] || 0) & (working[2] || 0)))

      working = [(temp1 + temp2) | 0].concat(working)
      working[4] = ((working[4] || 0) + temp1) | 0
    }

    for (let i = 0; i < 8; i++) {
      working[i] = ((working[i] || 0) + (oldHash[i] || 0)) | 0
    }
  }

  let result = ''
  for (let i = 0; i < 8; i++) {
    for (let j = 3; j >= 0; j--) {
      const byte = ((working[i] || 0) >> (j * 8)) & 255
      result += (byte < 16 ? '0' : '') + byte.toString(16)
    }
  }
  return result
}
