import { Download, Layers, Zap, ChevronRight } from 'lucide-react'
import { motion } from 'framer-motion'
import { useAppStore } from '../store/useAppStore'
import { clsx } from 'clsx'
import { apiUrl } from '../config'

export function Header() {
  const { sessionId, sessionStatus, pptUrl, images, groups } = useAppStore()
  const imageCount  = Object.keys(images).length
  const groupCount  = Object.keys(groups).length
  const isProcessing = sessionStatus === 'processing'
  const isComplete   = sessionStatus === 'complete'

  return (
    <header className="h-[60px] flex items-center justify-between px-6 flex-shrink-0 border-b border-white/[0.06] bg-surface1/80 backdrop-blur-sm relative z-20">
      {/* Logo + branding */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-accent/20 border border-accent/30 flex items-center justify-center">
          <Layers className="w-4 h-4 text-accent" />
        </div>
        <div>
          <span className="text-sm font-semibold tracking-tight text-text">Garment Catalog Studio</span>
          <span className="ml-2 text-[10px] font-mono text-faint uppercase tracking-widest">v1.0</span>
        </div>

        {sessionId && (
          <>
            <span className="text-faint mx-1">
              <ChevronRight className="w-3.5 h-3.5" />
            </span>
            <span className="text-xs font-mono text-muted bg-white/5 border border-white/8 rounded px-2 py-0.5">
              #{sessionId}
            </span>
          </>
        )}
      </div>

      {/* Centre stats */}
      {imageCount > 0 && (
        <div className="flex items-center gap-5 text-xs text-muted">
          <Stat label="Images" value={imageCount} />
          <div className="w-px h-4 bg-white/10" />
          <Stat label="Styles" value={groupCount} accent={groupCount > 0} />
          <div className="w-px h-4 bg-white/10" />
          <StatusChip status={sessionStatus} />
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-3">
        {isProcessing && (
          <div className="flex items-center gap-2 text-xs text-gold">
            <Zap className="w-3.5 h-3.5 animate-pulse" />
            <span>Processing…</span>
          </div>
        )}

        {pptUrl && (
          <motion.a
            href={apiUrl(pptUrl)}
            download
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className={clsx(
              'flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold',
              'bg-accent hover:bg-accent/90 text-white transition-colors',
              'border border-accent/50'
            )}
          >
            <Download className="w-3.5 h-3.5" />
            Export PPT
          </motion.a>
        )}
      </div>
    </header>
  )
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={clsx('font-semibold', accent ? 'text-accent' : 'text-text')}>
        {value}
      </span>
      <span>{label}</span>
    </div>
  )
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, { label: string; color: string }> = {
    idle:       { label: 'Idle',       color: 'text-muted' },
    uploading:  { label: 'Uploading',  color: 'text-warning' },
    processing: { label: 'Processing', color: 'text-warning' },
    complete:   { label: 'Complete',   color: 'text-success' },
    error:      { label: 'Error',      color: 'text-danger' },
  }
  const cfg = map[status] ?? map.idle
  return (
    <span className={clsx('font-medium', cfg.color)}>{cfg.label}</span>
  )
}
