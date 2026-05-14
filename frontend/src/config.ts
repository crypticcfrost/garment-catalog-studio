/**
 * API / WebSocket base for the FastAPI backend.
 *
 * - Local dev: empty string → same-origin paths like `/api/...` hit the Vite proxy.
 * - Vercel (experimentalServices): backend is mounted at `/_/backend` per vercel.json.
 * - Override anytime: set `VITE_API_BASE_URL` (e.g. https://api.example.com or /_/backend).
 *
 * Backend path stripping: Python strips `VERCEL_BACKEND_PREFIX` (default `/_/backend`) from
 * every request path when it matches, so routes stay `/api/...` without relying on `VERCEL=1`.
 * Set `VERCEL_BACKEND_PREFIX=` (empty) on self-hosted APIs that are not mounted under a prefix.
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

/** Map legacy /uploads and /outputs paths to API file routes (works behind Vercel /_/backend). */
function upgradeMediaPath(path: string): string {
  const up = /^\/uploads\/([^/]+)\/([^/]+)$/
  const m = path.match(up)
  if (m) {
    const sid = m[1]
    const fn = encodeURIComponent(m[2])
    return `/api/sessions/${sid}/file/upload/${fn}`
  }
  const op = /^\/outputs\/([^/]+)\/processed\/([0-9a-fA-F]{8})_processed\.jpg$/
  const m2 = path.match(op)
  if (m2) {
    return `/api/sessions/${m2[1]}/file/processed/${m2[2]}`
  }
  return path
}

/** Image preview / processed path from the store (relative or absolute). */
export function mediaUrl(path: string | undefined | null): string | undefined {
  if (!path) return undefined
  if (path.startsWith('blob:') || path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  const upgraded = upgradeMediaPath(path.startsWith('/') ? path : `/${path}`)
  return apiUrl(upgraded)
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

/**
 * Vercel serverless cannot keep a WebSocket open to the Python backend.
 * Production builds poll `GET /api/sessions/:id/state` instead.
 * Set `VITE_USE_POLLING=false` at build time to use WebSockets (self-hosted ASGI).
 */
export function preferHttpPollingForLiveSession(): boolean {
  const v = import.meta.env.VITE_USE_POLLING as string | undefined
  if (v === 'true') return true
  if (v === 'false') return false
  return import.meta.env.PROD
}

/** Retry fetch on HTTP 503 (serverless may route to an instance without the session yet). */
export async function fetchWith503Retries(
  url: string,
  init: RequestInit,
  maxAttempts = 5,
): Promise<Response> {
  const backoffMs = [0, 400, 800, 1400, 2200]
  let last!: Response
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    if (attempt > 0) {
      await new Promise((r) => setTimeout(r, backoffMs[attempt] ?? 2000))
    }
    last = await fetch(url, init)
    if (last.ok || last.status !== 503) return last
  }
  return last
}
