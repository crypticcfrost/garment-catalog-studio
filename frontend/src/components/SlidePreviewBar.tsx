import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronUp, ChevronDown, Download, Presentation, Eye } from 'lucide-react'
import { clsx } from 'clsx'
import { useAppStore } from '../store/useAppStore'
import { apiUrl, mediaUrl } from '../config'

export function SlidePreviewBar() {
  const { groups, images, pptUrl, pptVersion, sessionStatus } = useAppStore()
  const [open, setOpen] = useState(false)

  const groupList = Object.values(groups)
  const isReady = pptUrl != null

  if (groupList.length === 0 && sessionStatus === 'idle') return null

  return (
    <div className="border-t border-white/[0.05] bg-surface1/80 backdrop-blur-sm flex-shrink-0">
      {/* Toggle bar */}
      <button
        onClick={() => setOpen((p) => !p)}
        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/[0.02] transition-colors"
      >
        <Presentation className="w-3.5 h-3.5 text-muted" />
        <span className="text-xs font-medium text-text flex-1 text-left">
          Slide Preview
          {groupList.length > 0 && (
            <span className="ml-1.5 text-muted font-normal">
              {groupList.length + 2} slides
            </span>
          )}
        </span>

        {isReady && (
          <div className="flex items-center gap-1.5 mr-2">
            <div className="w-1.5 h-1.5 rounded-full bg-success" />
            <span className="text-[10px] text-success">Ready · v{pptVersion}</span>
          </div>
        )}

        <a
          href={pptUrl ? apiUrl(pptUrl) : '#'}
          download
          onClick={(e) => !pptUrl && e.preventDefault()}
          className={clsx(
            'flex items-center gap-1.5 text-[10px] font-medium px-3 py-1.5 rounded-lg border transition-colors mr-1',
            isReady
              ? 'text-accent border-accent/30 hover:bg-accent/10'
              : 'text-faint border-white/8 cursor-not-allowed'
          )}
        >
          <Download className="w-3 h-3" />
          Export
        </a>

        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-faint" />
        ) : (
          <ChevronUp className="w-3.5 h-3.5 text-faint" />
        )}
      </button>

      {/* Preview cards */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 180, opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div className="flex gap-3 px-4 pb-3 overflow-x-auto h-[172px] items-center">
              {/* Cover placeholder */}
              <SlideCard label="Cover" index={0} isCover />

              {groupList.map((group, i) => {
                const frontId = group.imageIds.find((id) => {
                  const img = images[id]
                  return img?.imageType === 'front'
                })
                const frontImg = frontId ? images[frontId] : null
                const thumbRaw = frontImg?.processedUrl || frontImg?.previewUrl
                const thumb = mediaUrl(thumbRaw)

                return (
                  <SlideCard
                    key={group.id}
                    label={group.styleId}
                    sublabel={group.garmentType}
                    index={i + 1}
                    thumb={thumb}
                  />
                )
              })}

              {/* Closing placeholder */}
              {groupList.length > 0 && (
                <SlideCard label="Thank You" index={groupList.length + 1} isCover />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function SlideCard({
  label,
  sublabel,
  index,
  thumb,
  isCover,
}: {
  label: string
  sublabel?: string
  index: number
  thumb?: string
  isCover?: boolean
}) {
  return (
    <div className="flex-shrink-0 w-28 group">
      <div
        className={clsx(
          'w-28 h-[90px] rounded-lg border overflow-hidden relative',
          'border-white/10 bg-surface2',
          'transition-all duration-150 group-hover:border-white/20'
        )}
        style={{ aspectRatio: '16/9' }}
      >
        {thumb ? (
          <img src={thumb} alt="" className="w-full h-full object-cover" loading="lazy" />
        ) : (
          <div
            className={clsx(
              'w-full h-full flex flex-col items-center justify-center',
              isCover ? 'bg-surface3' : 'bg-surface2'
            )}
          >
            {isCover ? (
              <div className="w-4 h-4 rounded bg-white/5 border border-white/10" />
            ) : (
              <Eye className="w-3.5 h-3.5 text-faint" />
            )}
          </div>
        )}
        <span className="absolute bottom-1 right-1 text-[9px] font-mono text-white/30 bg-black/40 rounded px-1">
          {index + 1}
        </span>
      </div>
      <p className="text-[9px] text-muted mt-1 truncate">{label}</p>
      {sublabel && <p className="text-[8px] text-faint truncate capitalize">{sublabel}</p>}
    </div>
  )
}
