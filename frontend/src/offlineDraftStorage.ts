export interface BrowserDraft {
  id: string
  client_id: string
  text: string
  base_updated_at: string
  created_at: string
}

const clientStorageKey = 'monitoring-mentor:client-id'

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

export function readOfflineDraftQueue(visitId: string): BrowserDraft[] {
  if (!visitId) return []
  try {
    const raw = window.localStorage.getItem(offlineDraftQueueStorageKey(visitId))
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function writeOfflineDraftQueue(visitId: string, drafts: BrowserDraft[]) {
  window.localStorage.setItem(offlineDraftQueueStorageKey(visitId), JSON.stringify(drafts))
}
