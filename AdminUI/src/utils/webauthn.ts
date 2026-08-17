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

export async function getAssertion(options: any) {
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
    response: {
      clientDataJSON: encode(response.clientDataJSON),
      authenticatorData: encode(response.authenticatorData),
      signature: encode(response.signature),
      userHandle: encode(response.userHandle)
    }
  }
}

export async function createCredential(options: any) {
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
    response: {
      clientDataJSON: encode(response.clientDataJSON),
      attestationObject: encode(response.attestationObject),
      transports: typeof response.getTransports === 'function' ? response.getTransports() : []
    }
  }
}
