import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  CheckCircle2, Circle, Loader2, AlertCircle, ChevronDown, ChevronRight,
  Terminal, ImageIcon, Filter, Cpu, FileSliders, FolderOutput,
} from 'lucide-react'
import { clsx } from 'clsx'
import { useAppStore } from '../store/useAppStore'
import { mediaUrl } from '../config'
import { StatusBadge } from './StatusBadge'
import type { PipelineStep, ImageItem } from '../types'

const STEP_ICONS: Record<string, React.ElementType> = {
  classification: ImageIcon,
  grouping:       Filter,
  extraction:     FileSliders,
  processing:     Cpu,
  ppt_generation: FileSliders,
  file_export:    FolderOutput,
}

export function PipelinePanel() {
  const { pipelineSteps, images, logs, sessionStatus } = useAppStore()
  const [activeTab, setActiveTab] = useState<'pipeline' | 'images' | 'log'>('pipeline')
  const imageList = Object.values(images)

  const overallProgress =
    pipelineSteps.length > 0
      ? Math.round(
          pipelineSteps.reduce((sum, s) => sum + s.progress, 0) / pipelineSteps.length
        )
      : 0

  const doneCount = pipelineSteps.filter((s) => s.status === 'complete').length

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-white/[0.05] flex-shrink-0">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-text">Pipeline</span>
          {pipelineSteps.length > 0 && (
            <span className="text-[10px] text-muted font-mono">
              {doneCount}/{pipelineSteps.length}
            </span>
          )}
        </div>

        {/* Overall progress bar */}
        {sessionStatus === 'processing' || sessionStatus === 'complete' ? (
          <div className="space-y-1">
            <div className="h-1 rounded-full bg-white/5 overflow-hidden">
              <motion.div
                className={clsx(
                  'h-full rounded-full',
                  sessionStatus === 'complete' ? 'bg-success' : 'bg-accent'
                )}
                animate={{ width: `${overallProgress}%` }}
                transition={{ duration: 0.4 }}
              />
            </div>
            <div className="flex justify-between text-[9px] text-faint">
              <span>
                {sessionStatus === 'complete' ? 'Complete' : 'Running…'}
              </span>
              <span>{overallProgress}%</span>
            </div>
          </div>
        ) : null}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-white/[0.05] flex-shrink-0">
        {(['pipeline', 'images', 'log'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={clsx(
              'flex-1 text-[10px] font-medium py-2 capitalize transition-colors',
              activeTab === tab
                ? 'text-accent border-b border-accent'
                : 'text-faint hover:text-muted'
            )}
          >
            {tab}
            {tab === 'images' && imageList.length > 0 && (
              <span className="ml-1 text-[9px] text-faint">({imageList.length})</span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <AnimatePresence mode="wait">
          {activeTab === 'pipeline' && (
            <motion.div
              key="pipeline"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="p-3 space-y-1"
            >
              {pipelineSteps.map((step, i) => (
                <PipelineStepRow key={step.id} step={step} index={i} />
              ))}
              {pipelineSteps.length === 0 && (
                <div className="text-center py-8">
                  <p className="text-xs text-faint">Upload images and run the pipeline</p>
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'images' && (
            <motion.div
              key="images"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="p-2 space-y-1"
            >
              {imageList.length === 0 ? (
                <div className="text-center py-8">
                  <p className="text-xs text-faint">No images uploaded</p>
                </div>
              ) : (
                imageList.map((img) => <ImageRow key={img.id} image={img} />)
              )}
            </motion.div>
          )}

          {activeTab === 'log' && (
            <motion.div
              key="log"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="p-3 space-y-1 font-mono"
            >
              {logs.length === 0 ? (
                <div className="text-center py-8">
                  <Terminal className="w-5 h-5 text-faint mx-auto mb-2" />
                  <p className="text-xs text-faint">Logs will appear here</p>
                </div>
              ) : (
                logs.map((log, i) => (
                  <div
                    key={i}
                    className={clsx(
                      'text-[10px] py-0.5 border-b border-white/[0.03]',
                      log.type === 'error' && 'text-danger',
                      log.type === 'success' && 'text-success',
                      log.type === 'warning' && 'text-warning',
                      log.type === 'info' && 'text-muted'
                    )}
                  >
                    <span className="text-faint mr-1.5">
                      {new Date(log.ts).toLocaleTimeString('en', { hour12: false })}
                    </span>
                    {log.message}
                  </div>
                ))
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function PipelineStepRow({ step, index }: { step: PipelineStep; index: number }) {
  const Icon = STEP_ICONS[step.id] ?? Circle
  const [expanded, setExpanded] = useState(false)

  return (
    <motion.div
      initial={{ opacity: 0, x: 8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.04 }}
      className={clsx(
        'rounded-lg border transition-colors',
        step.status === 'running'  && 'border-accent/30 bg-accent/5',
        step.status === 'complete' && 'border-success/20 bg-success/5',
        step.status === 'error'    && 'border-danger/30 bg-danger/5',
        step.status === 'pending'  && 'border-white/5 bg-white/[0.02]',
      )}
    >
      <button
        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-left"
        onClick={() => step.message && setExpanded((p) => !p)}
      >
        {/* Status icon */}
        <div className="w-5 flex-shrink-0">
          {step.status === 'pending'  && <Circle       className="w-4 h-4 text-faint" />}
          {step.status === 'running'  && <Loader2      className="w-4 h-4 text-accent animate-spin" />}
          {step.status === 'complete' && <CheckCircle2 className="w-4 h-4 text-success" />}
          {step.status === 'error'    && <AlertCircle  className="w-4 h-4 text-danger" />}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <span
              className={clsx(
                'text-xs font-medium',
                step.status === 'running'  && 'text-accent',
                step.status === 'complete' && 'text-success',
                step.status === 'error'    && 'text-danger',
                step.status === 'pending'  && 'text-faint',
              )}
            >
              {step.label}
            </span>
            {step.status === 'running' && (
              <span className="text-[9px] font-mono text-accent">{step.progress}%</span>
            )}
          </div>

          {/* Progress bar */}
          {step.status === 'running' && (
            <div className="mt-1 h-0.5 rounded-full bg-white/5 overflow-hidden">
              <motion.div
                className="h-full bg-accent rounded-full"
                animate={{ width: `${step.progress}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
          )}
        </div>

        {step.message && (
          expanded
            ? <ChevronDown className="w-3 h-3 text-faint flex-shrink-0" />
            : <ChevronRight className="w-3 h-3 text-faint flex-shrink-0" />
        )}
      </button>

      {/* Expanded message */}
      <AnimatePresence>
        {expanded && step.message && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <p className="text-[10px] text-muted px-10 pb-2.5">{step.message}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

function ImageRow({ image }: { image: ImageItem }) {
  const imgSrc = mediaUrl(image.processedUrl || image.previewUrl)

  return (
    <div className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-white/[0.03] transition-colors">
      <div className="w-8 h-10 rounded overflow-hidden bg-surface3 flex-shrink-0">
        {imgSrc ? (
          <img src={imgSrc} alt="" className="w-full h-full object-cover" loading="lazy" />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <ImageIcon className="w-3 h-3 text-faint" />
          </div>
        )}
      </div>
      <div className="flex-1 min-w-0 space-y-0.5">
        <p className="text-[10px] text-text truncate">{image.filename}</p>
        <div className="flex items-center gap-1.5">
          <StatusBadge status={image.status} size="sm" />
          {image.imageType && image.imageType !== 'unknown' && (
            <span className="text-[9px] text-faint capitalize">
              {image.imageType.replace('_', ' ')}
            </span>
          )}
        </div>
      </div>
      {image.confidence > 0 && (
        <span className="text-[9px] font-mono text-faint flex-shrink-0">
          {Math.round(image.confidence * 100)}%
        </span>
      )}
    </div>
  )
}
