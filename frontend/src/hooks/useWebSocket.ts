import { useEffect, useRef, useCallback } from 'react'
import { useAppStore } from '../store/useAppStore'
import type { ImageItem, StyleGroup, PipelineStep, SessionStatus } from '../types'
import { apiUrl, preferHttpPollingForLiveSession, sessionMediaUrl, wsSessionUrl } from '../config'

export function useWebSocket(sessionId: string | null) {
  const ws = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const generation = useRef(0)
  const pollHintLogged = useRef(false)
  const sessionLostLogged = useRef(false)

  const usePolling = preferHttpPollingForLiveSession()

  // ── HTTP polling (Vercel / no WebSocket) ───────────────────────────────────
  useEffect(() => {
    pollHintLogged.current = false
    sessionLostLogged.current = false
    if (!sessionId || !usePolling) return

    let cancelled = false

    const tick = async () => {
      if (cancelled) return
      try {
        const res = await fetch(apiUrl(`/api/sessions/${sessionId}/state`))
        if (cancelled) return
        if (!res.ok) return
        const snap = (await res.json()) as PollSnapshot
        if (snap.session_lost) {
          if (!sessionLostLogged.current) {
            sessionLostLogged.current = true
            useAppStore.getState().addLog(
              'This page lost contact with the session on the server (common on serverless). Refresh the page to start a new session.',
              'warning'
            )
          }
          return
        }
        const st = useAppStore.getState()
        st.applyPollSnapshot({
          sessionStatus: snap.status as SessionStatus,
          images: buildImagesFromPoll(sessionId, snap.images ?? {}),
          groups: buildGroupsFromPoll(snap.groups ?? {}),
          pipelineSteps: buildStepsFromPoll(snap.pipeline_steps ?? []),
          pptUrl: snap.ppt_url ?? null,
          pptVersion: snap.version ?? 0,
          mergeEmptyPipeline: true,
        })
        if (!pollHintLogged.current) {
          pollHintLogged.current = true
          st.addLog('Live updates: polling (WebSockets are not available on this host).', 'info')
        }
      } catch {
        /* ignore transient network errors */
      }
    }

    void tick()
    const id = setInterval(() => void tick(), 900)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [sessionId, usePolling])

  const connect = useCallback(() => {
    if (!sessionId || usePolling) return
    if (ws.current?.readyState === WebSocket.OPEN) return
    if (ws.current?.readyState === WebSocket.CONNECTING) return

    const myGen = ++generation.current
    const socket = new WebSocket(wsSessionUrl(sessionId))
    ws.current = socket

    socket.onopen = () => {
      useAppStore.getState().addLog('Connected to pipeline', 'success')
      const hb = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'ping' }))
        } else {
          clearInterval(hb)
        }
      }, 25_000)
    }

    socket.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data)
        handleEvent(event, useAppStore.getState())
      } catch {
        // ignore malformed frames
      }
    }

    socket.onerror = () => {
      useAppStore.getState().addLog('WebSocket error — will retry…', 'warning')
    }

    socket.onclose = () => {
      if (generation.current === myGen) {
        reconnectTimer.current = setTimeout(connect, 3000)
      }
    }
  }, [sessionId, usePolling])

  useEffect(() => {
    if (!sessionId || usePolling) return

    generation.current++
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current)
      reconnectTimer.current = null
    }
    if (ws.current && ws.current.readyState !== WebSocket.CLOSED) {
      ws.current.onclose = null
      ws.current.close()
    }

    connect()

    return () => {
      generation.current++
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current)
        reconnectTimer.current = null
      }
      if (ws.current) {
        ws.current.onclose = null
        ws.current.close()
      }
    }
  }, [connect, sessionId, usePolling])
}

// ── Poll snapshot types / mappers ────────────────────────────────────────────

interface PollSnapshot {
  status: string
  session_lost?: boolean
  images?: Record<string, Record<string, unknown>>
  groups?: Record<string, Record<string, unknown>>
  pipeline_steps?: unknown[]
  ppt_url?: string | null
  version?: number
}

function buildImagesFromPoll(
  sessionId: string,
  raw: Record<string, Record<string, unknown>>,
): Record<string, ImageItem> {
  const out: Record<string, ImageItem> = {}
  for (const [id, row] of Object.entries(raw)) {
    const previewRaw = (row.preview_url as string) || ''
    const processedRaw = (row.processed_url as string) || undefined
    out[id] = {
      id,
      filename: row.filename as string,
      previewUrl: sessionMediaUrl(sessionId, previewRaw) ?? '',
      processedUrl: sessionMediaUrl(sessionId, processedRaw),
      status: row.status as ImageItem['status'],
      imageType: (row.image_type as ImageItem['imageType']) || undefined,
      styleId: row.style_id as string | undefined,
      confidence: (row.confidence as number) ?? 0,
      garmentData: row.garment_data as ImageItem['garmentData'],
      errorMessage: row.error_message as string | undefined,
      description: row.description as string | undefined,
      colors: row.colors as string[] | undefined,
    }
  }
  return out
}

function buildGroupsFromPoll(raw: Record<string, Record<string, unknown>>): Record<string, StyleGroup> {
  const out: Record<string, StyleGroup> = {}
  for (const [id, row] of Object.entries(raw)) {
    out[id] = {
      id,
      styleId: row.style_id as string,
      garmentType: row.garment_type as string | undefined,
      imageIds: (row.images as string[]) ?? [],
      garmentData: row.garment_data as StyleGroup['garmentData'],
      slideNumber: row.slide_number as number | undefined,
    }
  }
  return out
}

function buildStepsFromPoll(raw: unknown[]): PipelineStep[] {
  return raw
    .filter((x): x is Record<string, unknown> => typeof x === 'object' && x != null)
    .map((s) => ({
      id: String(s.id),
      label: String(s.label ?? ''),
      status: (s.status as PipelineStep['status']) ?? 'pending',
      progress: Number(s.progress ?? 0),
      message: s.message as string | undefined,
    }))
}

// ── WebSocket event dispatcher ───────────────────────────────────────────────

function handleEvent(event: { type: string; data: Record<string, unknown> }, store: ReturnType<typeof useAppStore.getState>) {
  const { type, data } = event

  switch (type) {
    case 'session_state': {
      if (data.pipeline_steps) {
        store.setPipelineSteps(data.pipeline_steps as PipelineStep[])
      }
      if (data.images) {
        const imgs = data.images as Record<string, Record<string, unknown>>
        for (const [id, img] of Object.entries(imgs)) {
          const opub = img.original_public_url as string | undefined
          const op = (img.original_path as string) || ''
          const fname = op.split(/[/\\]/).pop() ?? ''
          const fallback = `/api/sessions/${store.sessionId}/file/upload/${encodeURIComponent(fname)}`
          const thumb =
            sessionMediaUrl(store.sessionId, opub) ||
            sessionMediaUrl(store.sessionId, fallback) ||
            fallback
          store.addImage({
            id,
            filename: img.filename as string,
            previewUrl: thumb,
            status: (img.status as ImageItem['status']) ?? 'uploaded',
            imageType: img.image_type as ImageItem['imageType'],
            styleId: img.style_id as string | undefined,
            confidence: (img.confidence as number) ?? 0,
          } as ImageItem)
        }
      }
      if (data.groups) {
        const rawGroups = data.groups as Record<string, Record<string, unknown>>
        const groups: StyleGroup[] = Object.entries(rawGroups).map(([id, g]) => ({
          id,
          styleId: g.style_id as string,
          garmentType: g.garment_type as string | undefined,
          imageIds: (g.images as string[]) ?? [],
          garmentData: g.garment_data as StyleGroup['garmentData'],
          slideNumber: g.slide_number as number | undefined,
        }))
        store.setGroups(groups)
      }
      break
    }

    case 'pipeline_started': {
      store.setSessionStatus('processing')
      if (data.steps) store.setPipelineSteps(data.steps as PipelineStep[])
      store.addLog(`Pipeline started — ${data.total} images`, 'info')
      break
    }

    case 'image_uploaded': {
      const thumbRaw = (data.thumbnail as string) || ''
      const previewUrl = sessionMediaUrl(store.sessionId, thumbRaw) ?? ''
      store.addImage({
        id: data.image_id as string,
        filename: data.filename as string,
        previewUrl,
        status: 'uploaded',
        confidence: 0,
      } as ImageItem)
      break
    }

    case 'image_status': {
      store.updateImage(data.image_id as string, {
        status: data.status as ImageItem['status'],
      })
      break
    }

    case 'image_classified': {
      store.updateImage(data.image_id as string, {
        status: 'classified',
        imageType: data.image_type as ImageItem['imageType'],
        styleId: data.style_id as string | undefined,
        confidence: data.confidence as number,
        colors: data.colors as string[],
        description: (data.key_features || data.description) as string,
      })
      const pct = Math.round((data.confidence as number) * 100)
      store.addLog(
        `${data.image_id}: ${data.image_type} · ${data.primary_color || ''} ${data.garment_type || ''} (${pct}% conf)`,
        'info'
      )
      break
    }

    case 'spec_label_reassigned': {
      store.moveImageToGroup(data.image_id as string, data.group_id as string)
      store.addLog(
        `Spec label ${data.image_id} reassigned to ${data.style_id} (ref match)`,
        'success'
      )
      break
    }

    case 'images_grouped': {
      const rawGroups = (data.groups as Array<Record<string, unknown>>) ?? []
      const groups: StyleGroup[] = rawGroups.map((g) => ({
        id: g.group_id as string,
        styleId: g.style_id as string,
        garmentType: g.garment_type as string | undefined,
        imageIds: (g.image_ids as string[]) ?? [],
      }))
      store.setGroups(groups)
      store.addLog(`Formed ${groups.length} style groups`, 'success')
      break
    }

    case 'data_extracted': {
      const d = data.data as Record<string, unknown>
      store.updateImage(data.image_id as string, {
        status: 'extracted',
        garmentData: {
          reference_number: d.reference_number as string,
          fabric_composition: d.fabric_composition as string,
          gsm: d.gsm as string,
          date: d.date as string,
          brand: d.brand as string,
        },
      })
      store.addLog(`Extracted specs from ${data.image_id}`, 'success')
      break
    }

    case 'image_processed': {
      store.updateImage(data.image_id as string, {
        status: 'processed',
        processedUrl: sessionMediaUrl(store.sessionId, data.processed_url as string | undefined),
      })
      break
    }

    case 'image_error': {
      store.updateImage(data.image_id as string, {
        status: 'error',
        errorMessage: data.error as string,
      })
      store.addLog(`Error on ${data.image_id}: ${data.error}`, 'error')
      break
    }

    case 'image_reclassified': {
      store.updateImage(data.image_id as string, {
        imageType: data.image_type as ImageItem['imageType'],
      })
      if (data.group_id) store.moveImageToGroup(data.image_id as string, data.group_id as string)
      break
    }

    case 'step_update': {
      store.updatePipelineStep(data.step_id as string, {
        status: data.status as PipelineStep['status'],
        progress: data.progress as number,
        message: data.message as string | undefined,
      })
      if (data.message) store.addLog(data.message as string, data.status === 'complete' ? 'success' : 'info')
      break
    }

    case 'ppt_generated': {
      store.setPptUrl(data.ppt_url as string, data.version as number)
      store.addLog('PowerPoint catalog ready for download!', 'success')
      break
    }

    case 'pipeline_complete': {
      store.setSessionStatus('complete')
      store.setPptUrl(data.ppt_url as string)
      store.addLog('Pipeline complete', 'success')
      break
    }

    case 'pipeline_error': {
      store.setSessionStatus('error')
      store.addLog(`Pipeline error: ${data.error}`, 'error')
      break
    }

    default:
      break
  }
}
