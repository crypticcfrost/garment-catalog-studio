/**
 * API / WebSocket base for the FastAPI backend.
 *
 * - Local dev: empty string → same-origin paths like `/api/...` hit the Vite proxy.
 * - Vercel (experimentalServices): backend is mounted at `/_/backend` per vercel.json.
 * - Override anytime: set `VITE_API_BASE_URL` (e.g. https://api.example.com or /_/backend).
 */

function trimTrailingSlash(s: string): string {
  return s.replace(/\/+$/, '')
}

export const API_BASE: string = (() => {
  const fromEnv = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (typeof fromEnv === 'string' && fromEnv.trim().length > 0) {
    return trimTrailingSlash(fromEnv.trim())
  }
  if (import.meta.env.DEV) {
    return ''
  }
  return '/_/backend'
})()

/** Prefix a backend path (e.g. `/api/sessions`, `/uploads/...`) for fetch / img src. */
export function apiUrl(path: string | undefined | null): string {
  if (path == null || path === '') return ''
  if (path.startsWith('blob:')) return path
  if (path.startsWith('http://') || path.startsWith('https://')) return path
  const p = path.startsWith('/') ? path : `/${path}`
  if (API_BASE === '') return p
  return `${API_BASE}${p}`
}

/** Image preview / processed path from the store (relative or absolute). */
export function mediaUrl(path: string | undefined | null): string | undefined {
  if (!path) return undefined
  if (path.startsWith('blob:') || path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  return apiUrl(path)
}

/** WebSocket URL for pipeline events (`/ws/{sessionId}` on the backend). */
export function wsSessionUrl(sessionId: string): string {
  if (import.meta.env.DEV && API_BASE === '') {
    const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${wsProto}//${window.location.host}/ws/${sessionId}`
  }
  if (API_BASE.startsWith('http://') || API_BASE.startsWith('https://')) {
    const u = new URL(API_BASE)
    const wsProto = u.protocol === 'https:' ? 'wss:' : 'ws:'
    const basePath = trimTrailingSlash(u.pathname)
    const prefix = basePath ? `${basePath}/ws` : '/ws'
    return `${wsProto}//${u.host}${prefix}/${sessionId}`
  }
  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const basePath = trimTrailingSlash(API_BASE)
  return `${wsProto}//${window.location.host}${basePath}/ws/${sessionId}`
}
