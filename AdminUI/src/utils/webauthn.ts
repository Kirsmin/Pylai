function decode(value: string): ArrayBuffer {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/')
  const padded = normalized + '='.repeat((4 - normalized.length % 4) % 4)
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes.buffer
}

function encode(value: ArrayBuffer | null): string | null {
  if (!value) return null
  const bytes = new Uint8Array(value)
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

export function isWebAuthnAvailable(): boolean {
  return typeof navigator !== 'undefined' &&
    navigator.credentials !== undefined &&
    typeof navigator.credentials.create === 'function' &&
    typeof navigator.credentials.get === 'function'
}

export function assertWebAuthnAvailable(): void {
  if (!isWebAuthnAvailable()) {
    throw new Error('当前浏览器环境不支持 WebAuthn / Passkey。请使用 HTTPS 或 localhost 访问，或改用 TOTP 验证。')
  }
}

export function formatWebAuthnError(err: unknown): string {
  const name = err instanceof DOMException ? err.name : ''
  switch (name) {
    case 'NotAllowedError':
      return '操作已取消或超时，请重试。'
    case 'InvalidStateError':
      return '当前设备可能已经注册过相同 Passkey，请检查凭据列表。'
    case 'SecurityError':
      return '当前安全上下文或域名不符合 WebAuthn 要求。'
    case 'UnknownError':
      return '系统凭据管理器暂时不可用，请稍后重试或从系统设置中移除旧 Passkey。'
    default:
      return 'Passkey 操作失败，请重试。'
  }
}

export async function getAssertion(options: any) {
  assertWebAuthnAvailable()
  const publicKey = {
    ...options,
    challenge: decode(options.challenge),
    allowCredentials: (options.allowCredentials ?? []).map((item: any) => ({
      ...item,
      id: decode(item.id)
    }))
  }
  const credential = await navigator.credentials.get({ publicKey }) as PublicKeyCredential | null
  if (!credential) throw new Error('未完成 Passkey 验证')
  const response = credential.response as AuthenticatorAssertionResponse
  return {
    id: credential.id,
    rawId: encode(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults() ?? {},
    response: {
      clientDataJSON: encode(response.clientDataJSON),
      authenticatorData: encode(response.authenticatorData),
      signature: encode(response.signature),
      userHandle: encode(response.userHandle)
    }
  }
}

export async function createCredential(options: any) {
  assertWebAuthnAvailable()
  const publicKey = {
    ...options,
    challenge: decode(options.challenge),
    user: { ...options.user, id: decode(options.user.id) },
    excludeCredentials: (options.excludeCredentials ?? []).map((item: any) => ({
      ...item,
      id: decode(item.id)
    }))
  }
  const credential = await navigator.credentials.create({ publicKey }) as PublicKeyCredential | null
  if (!credential) throw new Error('未完成 Passkey 注册')
  const response = credential.response as AuthenticatorAttestationResponse
  return {
    id: credential.id,
    rawId: encode(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults() ?? {},
    response: {
      clientDataJSON: encode(response.clientDataJSON),
      attestationObject: encode(response.attestationObject),
      transports: typeof response.getTransports === 'function' ? response.getTransports() : []
    }
  }
}
