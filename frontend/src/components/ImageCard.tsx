import { useState } from 'react'
import { motion } from 'framer-motion'
import { AlertCircle, RotateCcw } from 'lucide-react'
import { clsx } from 'clsx'
import { StatusBadge } from './StatusBadge'
import { useAppStore } from '../store/useAppStore'
import type { ImageItem } from '../types'
import { apiUrl, mediaUrl } from '../config'

const TYPE_LABELS: Record<string, string> = {
  front:      'F',
  back:       'B',
  detail:     'D',
  spec_label: 'S',
  unknown:    '?',
}

const TYPE_COLORS: Record<string, string> = {
  front:      'bg-accent/20 text-accent border-accent/30',
  back:       'bg-purple-500/20 text-purple-400 border-purple-500/30',
  detail:     'bg-gold/20 text-gold border-gold/30',
  spec_label: 'bg-success/20 text-success border-success/30',
  unknown:    'bg-white/5 text-muted border-white/10',
}

interface Props {
  image: ImageItem
  compact?: boolean
  selected?: boolean
  onSelect?: (id: string) => void
  draggable?: boolean
}

export function ImageCard({ image, compact = false, selected = false, onSelect, draggable }: Props) {
  const { sessionId, addLog } = useAppStore()
  const [retrying, setRetrying] = useState(false)
  const raw = image.processedUrl || image.previewUrl
  const imgSrc = mediaUrl(raw)

  const handleRetry = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!sessionId) return
    setRetrying(true)
    try {
      await fetch(apiUrl(`/api/sessions/${sessionId}/images/${image.id}/retry`), {
        method: 'POST',
      })
      addLog(`Retrying classification for ${image.id}`, 'info')
    } catch {
      addLog(`Retry failed for ${image.id}`, 'error')
    } finally {
      setRetrying(false)
    }
  }

  if (compact) {
    return (
      <motion.div
        layout
        layoutId={`img-${image.id}`}
        onClick={() => onSelect?.(image.id)}
        className={clsx(
          'img-card relative rounded-lg overflow-hidden cursor-pointer',
          'border border-white/8',
          selected && 'ring-1 ring-accent',
          image.status === 'error' && 'ring-1 ring-danger'
        )}
        style={{ aspectRatio: '3/4' }}
      >
        {imgSrc ? (
          <img
            src={imgSrc}
            alt={image.filename}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full bg-surface3 flex items-center justify-center">
            <span className="text-faint text-xs">{image.filename?.slice(0, 6)}</span>
          </div>
        )}

        {/* Type badge */}
        {image.imageType && (
          <span
            className={clsx(
              'absolute top-1 left-1 text-[9px] font-bold w-4 h-4 rounded flex items-center justify-center border',
              TYPE_COLORS[image.imageType] ?? TYPE_COLORS.unknown
            )}
          >
            {TYPE_LABELS[image.imageType] ?? '?'}
          </span>
        )}

        {/* Error overlay */}
        {image.status === 'error' && (
          <div className="absolute inset-0 bg-danger/20 flex items-center justify-center">
            <AlertCircle className="w-4 h-4 text-danger" />
          </div>
        )}

        {/* Status overlay for active processing */}
        {(image.status === 'classifying' || image.status === 'processing' || image.status === 'extracting') && (
          <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
            <div className="w-4 h-4 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        )}
      </motion.div>
    )
  }

  return (
    <motion.div
      layout
      layoutId={`img-full-${image.id}`}
      onClick={() => onSelect?.(image.id)}
      className={clsx(
        'img-card relative rounded-xl overflow-hidden cursor-pointer',
        'border bg-surface2',
        selected ? 'border-accent/60 glow-accent' : 'border-white/8',
        image.status === 'error' ? 'border-danger/40' : '',
        draggable && 'cursor-grab active:cursor-grabbing'
      )}
    >
      {/* Image */}
      <div className="relative" style={{ aspectRatio: '3/4' }}>
        {imgSrc ? (
          <img
            src={imgSrc}
            alt={image.filename}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full bg-surface3 flex items-center justify-center">
            <span className="text-faint text-xs font-mono">{image.id}</span>
          </div>
        )}

        {/* Processing spinner */}
        {(image.status === 'classifying' || image.status === 'processing' || image.status === 'extracting') && (
          <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
            <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {/* Error overlay with retry */}
        {image.status === 'error' && (
          <div className="absolute inset-0 bg-danger/20 flex flex-col items-center justify-center gap-2">
            <AlertCircle className="w-5 h-5 text-danger" />
            <button
              onClick={handleRetry}
              disabled={retrying}
              className="text-[10px] text-danger border border-danger/30 rounded px-2 py-0.5 hover:bg-danger/10 transition-colors"
            >
              {retrying ? 'Retrying…' : 'Retry'}
            </button>
          </div>
        )}

        {/* Type chip */}
        {image.imageType && (
          <span
            className={clsx(
              'absolute top-2 left-2 text-[10px] font-bold px-1.5 py-0.5 rounded border',
              TYPE_COLORS[image.imageType] ?? TYPE_COLORS.unknown
            )}
          >
            {image.imageType.replace('_', ' ')}
          </span>
        )}
      </div>

      {/* Footer */}
      <div className="p-2 space-y-1.5">
        <div className="flex items-center justify-between gap-1">
          <span className="text-[10px] text-muted truncate max-w-[80px]">{image.filename}</span>
          <StatusBadge status={image.status} size="sm" />
        </div>

        {/* Confidence bar */}
        {image.confidence > 0 && (
          <div className="space-y-0.5">
            <div className="flex justify-between text-[9px] text-faint">
              <span>confidence</span>
              <span>{Math.round(image.confidence * 100)}%</span>
            </div>
            <div className="h-0.5 rounded-full bg-white/5 overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${image.confidence * 100}%` }}
                transition={{ duration: 0.6, ease: 'easeOut' }}
                className={clsx(
                  'h-full rounded-full',
                  image.confidence > 0.8 ? 'bg-success' :
                  image.confidence > 0.5 ? 'bg-warning' : 'bg-danger'
                )}
              />
            </div>
          </div>
        )}

        {/* Style ID */}
        {image.styleId && (
          <p className="text-[9px] font-mono text-faint truncate">{image.styleId}</p>
        )}
      </div>
    </motion.div>
  )
}
