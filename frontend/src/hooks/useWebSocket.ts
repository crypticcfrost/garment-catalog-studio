import { useEffect, useRef, useCallback } from 'react'
import { useAppStore } from '../store/useAppStore'
import type { ImageItem, StyleGroup, PipelineStep } from '../types'

const WS_BASE = import.meta.env.DEV
  ? 'ws://localhost:8000/ws'
  : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`

export function useWebSocket(sessionId: string | null) {
  const ws = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const store = useAppStore()

  const connect = useCallback(() => {
    if (!sessionId) return
    if (ws.current?.readyState === WebSocket.OPEN) return

    const socket = new WebSocket(`${WS_BASE}/${sessionId}`)
    ws.current = socket

    socket.onopen = () => {
      store.addLog('Connected to pipeline', 'success')
      // Heartbeat
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
        handleEvent(event, store)
      } catch {
        // ignore malformed
      }
    }

    socket.onerror = () => {
      store.addLog('WebSocket error — reconnecting…', 'warning')
    }

    socket.onclose = () => {
      reconnectTimer.current = setTimeout(connect, 3000)
    }
  }, [sessionId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      ws.current?.close()
    }
  }, [connect])
}

// ── Event dispatcher ──────────────────────────────────────────────────────────

function handleEvent(event: { type: string; data: Record<string, unknown> }, store: ReturnType<typeof useAppStore.getState>) {
  const { type, data } = event

  switch (type) {
    case 'session_state': {
      // Restore full session after reconnect
      if (data.pipeline_steps) {
        store.setPipelineSteps(data.pipeline_steps as PipelineStep[])
      }
      if (data.images) {
        const imgs = data.images as Record<string, Record<string, unknown>>
        for (const [id, img] of Object.entries(imgs)) {
          const thumb = img.original_path
            ? `/uploads/${store.sessionId}/${(img.original_path as string).split('/').pop()}`
            : ''
          store.addImage({
            id,
            filename:   img.filename as string,
            previewUrl: thumb,
            status:     (img.status as ImageItem['status']) ?? 'uploaded',
            imageType:  img.image_type as ImageItem['imageType'],
            styleId:    img.style_id as string | undefined,
            confidence: (img.confidence as number) ?? 0,
          } as ImageItem)
        }
      }
      if (data.groups) {
        const rawGroups = data.groups as Record<string, Record<string, unknown>>
        const groups: StyleGroup[] = Object.entries(rawGroups).map(([id, g]) => ({
          id,
          styleId:     g.style_id as string,
          garmentType: g.garment_type as string | undefined,
          imageIds:    (g.images as string[]) ?? [],
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
      const thumb = `/uploads/${store.sessionId}/${(data.thumbnail as string)?.split('/').pop() ?? ''}`
      store.addImage({
        id:         data.image_id as string,
        filename:   data.filename as string,
        previewUrl: data.thumbnail as string ?? thumb,
        status:     'uploaded',
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
        status:      'classified',
        imageType:   data.image_type as ImageItem['imageType'],
        styleId:     data.style_id as string | undefined,
        confidence:  data.confidence as number,
        colors:      data.colors as string[],
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
      // Spec label moved to correct group after OCR extracted reference number
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
        id:          g.group_id as string,
        styleId:     g.style_id as string,
        garmentType: g.garment_type as string | undefined,
        imageIds:    (g.image_ids as string[]) ?? [],
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
          reference_number:   d.reference_number as string,
          fabric_composition: d.fabric_composition as string,
          gsm:                d.gsm as string,
          date:               d.date as string,
          brand:              d.brand as string,
        },
      })
      store.addLog(`Extracted specs from ${data.image_id}`, 'success')
      break
    }

    case 'image_processed': {
      store.updateImage(data.image_id as string, {
        status:       'processed',
        processedUrl: data.processed_url as string,
      })
      break
    }

    case 'image_error': {
      store.updateImage(data.image_id as string, {
        status:       'error',
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
        status:   data.status as PipelineStep['status'],
        progress: data.progress as number,
        message:  data.message as string | undefined,
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
