import { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { motion, AnimatePresence } from 'framer-motion'
import { Upload, ImagePlus, X, Play, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { useAppStore } from '../store/useAppStore'

const API = 'http://localhost:8000'

interface Props {
  onProcessStart: () => void
}

export function UploadZone({ onProcessStart }: Props) {
  const { sessionId, images, sessionStatus, setSessionStatus, addImage, addLog } = useAppStore()
  const [isUploading, setIsUploading] = useState(false)
  const [previewFiles, setPreviewFiles] = useState<File[]>([])

  const imageCount = Object.keys(images).length
  const canProcess = imageCount > 0 && sessionStatus === 'idle'

  const onDrop = useCallback(
    async (accepted: File[]) => {
      if (!sessionId || accepted.length === 0) return
      setPreviewFiles((prev) => [...prev, ...accepted])
      setIsUploading(true)
      setSessionStatus('uploading')

      // Upload in batches of 10
      const BATCH = 10
      for (let i = 0; i < accepted.length; i += BATCH) {
        const batch = accepted.slice(i, i + BATCH)
        const form = new FormData()
        batch.forEach((f) => form.append('files', f))
        try {
          const res = await fetch(`${API}/api/sessions/${sessionId}/upload`, {
            method: 'POST',
            body: form,
          })
          if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
          addLog(`Uploaded ${batch.length} images`, 'success')
        } catch (e) {
          addLog(`Upload error: ${e}`, 'error')
        }
      }

      setIsUploading(false)
      setSessionStatus('idle')
    },
    [sessionId, setSessionStatus, addImage, addLog]
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'image/*': ['.jpg', '.jpeg', '.png', '.webp'] },
    maxFiles: 200,
    disabled: isUploading || sessionStatus === 'processing',
  })

  const handleProcess = async () => {
    if (!sessionId) return
    try {
      const res = await fetch(`${API}/api/sessions/${sessionId}/process`, { method: 'POST' })
      if (!res.ok) throw new Error(`Process failed: ${res.status}`)
      setSessionStatus('processing')
      onProcessStart()
    } catch (e) {
      addLog(`Failed to start pipeline: ${e}`, 'error')
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Drop target */}
      <div
        {...getRootProps()}
        className={clsx(
          'relative rounded-xl border-2 border-dashed transition-all duration-200 cursor-pointer',
          isDragActive
            ? 'border-accent bg-accent/10 scale-[1.01]'
            : 'border-white/10 hover:border-white/20 hover:bg-white/[0.02]',
          (isUploading || sessionStatus === 'processing') && 'opacity-50 cursor-not-allowed'
        )}
      >
        <input {...getInputProps()} />
        <div className="flex flex-col items-center justify-center gap-3 py-8 px-4 text-center">
          <div
            className={clsx(
              'w-12 h-12 rounded-xl flex items-center justify-center transition-colors',
              isDragActive ? 'bg-accent/20' : 'bg-white/5'
            )}
          >
            {isUploading ? (
              <Loader2 className="w-5 h-5 text-accent animate-spin" />
            ) : isDragActive ? (
              <ImagePlus className="w-5 h-5 text-accent" />
            ) : (
              <Upload className="w-5 h-5 text-muted" />
            )}
          </div>

          {isDragActive ? (
            <p className="text-sm font-medium text-accent">Drop images here</p>
          ) : (
            <>
              <div>
                <p className="text-sm font-medium text-text">Drop images or click to browse</p>
                <p className="text-xs text-muted mt-1">JPG, PNG, WebP · up to 200 images</p>
              </div>
              <p className="text-[10px] text-faint">3–4 images per style (front, back, detail, spec label)</p>
            </>
          )}
        </div>

        {/* Upload progress overlay */}
        <AnimatePresence>
          {isUploading && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 rounded-xl bg-surface2/60 flex items-center justify-center"
            >
              <span className="text-xs text-accent animate-pulse">Uploading…</span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Stats row */}
      {imageCount > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center justify-between text-xs text-muted px-1"
        >
          <span>{imageCount} image{imageCount !== 1 ? 's' : ''} ready</span>
          <span className="text-faint">~{Math.ceil(imageCount / 4)} styles</span>
        </motion.div>
      )}

      {/* Start button */}
      <AnimatePresence>
        {canProcess && (
          <motion.button
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 6 }}
            onClick={handleProcess}
            className={clsx(
              'w-full flex items-center justify-center gap-2 rounded-xl py-3',
              'text-sm font-semibold text-white',
              'bg-accent hover:bg-accent/90 active:bg-accent/80',
              'border border-accent/40 transition-colors',
              'glow-accent'
            )}
          >
            <Play className="w-4 h-4" />
            Run Pipeline
          </motion.button>
        )}
      </AnimatePresence>

      {sessionStatus === 'processing' && (
        <div className="flex items-center justify-center gap-2 text-xs text-warning py-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span>Pipeline running…</span>
        </div>
      )}
    </div>
  )
}
