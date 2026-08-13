export interface BrowserDraft {
  id: string
  client_id: string
  text: string
  base_updated_at: string
  created_at: string
}

const clientStorageKey = 'monitoring-mentor:client-id'

// PRD BR-24 / 15.3: offline drafts must be encrypted at rest and unreadable once the
// session ends or access is revoked. The AES-GCM key lives only in sessionStorage (cleared
// when the tab/browser closes, or explicitly via clearOfflineDraftQueue), so the ciphertext
// left behind in localStorage becomes permanently unreadable without it — a lightweight,
// browser-only approximation of "本地加密...远程/本地受控清除机制".
const sessionKeyStorageKey = 'monitoring-mentor:offline-key'
let cachedKeyPromise: Promise<CryptoKey> | null = null

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return window.btoa(binary)
}

function base64ToBytes(value: string): Uint8Array<ArrayBuffer> {
  const binary = window.atob(value)
  const bytes = new Uint8Array(new ArrayBuffer(binary.length))
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return bytes
}

async function getSessionKey(): Promise<CryptoKey> {
  if (cachedKeyPromise) return cachedKeyPromise
  cachedKeyPromise = (async () => {
    const stored = window.sessionStorage.getItem(sessionKeyStorageKey)
    if (stored) {
      const raw = base64ToBytes(stored)
      return window.crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['encrypt', 'decrypt'])
    }
    const key = await window.crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt'])
    const exported = await window.crypto.subtle.exportKey('raw', key)
    window.sessionStorage.setItem(sessionKeyStorageKey, bytesToBase64(new Uint8Array(exported)))
    return key
  })()
  return cachedKeyPromise
}

async function encryptText(plaintext: string): Promise<{ iv: string; ciphertext: string }> {
  const key = await getSessionKey()
  const iv = window.crypto.getRandomValues(new Uint8Array(12))
  const encoded = new TextEncoder().encode(plaintext)
  const ciphertext = await window.crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded)
  return { iv: bytesToBase64(iv), ciphertext: bytesToBase64(new Uint8Array(ciphertext)) }
}

async function decryptText(iv: string, ciphertext: string): Promise<string> {
  const key = await getSessionKey()
  const plainBuffer = await window.crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: base64ToBytes(iv) },
    key,
    base64ToBytes(ciphertext),
  )
  return new TextDecoder().decode(plainBuffer)
}

interface EncryptedDraftRecord {
  id: string
  client_id: string
  base_updated_at: string
  created_at: string
  iv: string
  ciphertext: string
}

export function offlineDraftQueueStorageKey(visitId: string) {
  return `monitoring-mentor:offline-drafts:${visitId}`
}

export function makeBrowserDraftId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function getBrowserClientId() {
  const stored = window.localStorage.getItem(clientStorageKey)
  if (stored) return stored
  const created = makeBrowserDraftId('browser')
  window.localStorage.setItem(clientStorageKey, created)
  return created
}

export async function readOfflineDraftQueue(visitId: string): Promise<BrowserDraft[]> {
  if (!visitId) return []
  try {
    const raw = window.localStorage.getItem(offlineDraftQueueStorageKey(visitId))
    const parsed = raw ? (JSON.parse(raw) as EncryptedDraftRecord[]) : []
    if (!Array.isArray(parsed)) return []
    const decrypted = await Promise.all(
      parsed.map(async (record) => {
        try {
          const text = await decryptText(record.iv, record.ciphertext)
          return { id: record.id, client_id: record.client_id, text, base_updated_at: record.base_updated_at, created_at: record.created_at }
        } catch {
          // Session key unavailable (new tab/browser session) — encrypted drafts from a
          // prior session are, by design, no longer readable (BR-24 "权限撤销后不可读取").
          return null
        }
      }),
    )
    return decrypted.filter((item): item is BrowserDraft => item !== null)
  } catch {
    return []
  }
}

export async function writeOfflineDraftQueue(visitId: string, drafts: BrowserDraft[]): Promise<void> {
  const encrypted = await Promise.all(
    drafts.map(async (draft) => {
      const { iv, ciphertext } = await encryptText(draft.text)
      const record: EncryptedDraftRecord = {
        id: draft.id,
        client_id: draft.client_id,
        base_updated_at: draft.base_updated_at,
        created_at: draft.created_at,
        iv,
        ciphertext,
      }
      return record
    }),
  )
  window.localStorage.setItem(offlineDraftQueueStorageKey(visitId), JSON.stringify(encrypted))
}

/** PRD BR-24 controlled clear: wipe the local encrypted queue and its session key. */
export function clearOfflineDraftQueue(visitId: string) {
  window.localStorage.removeItem(offlineDraftQueueStorageKey(visitId))
}

export function clearOfflineEncryptionKey() {
  window.sessionStorage.removeItem(sessionKeyStorageKey)
  cachedKeyPromise = null
}
