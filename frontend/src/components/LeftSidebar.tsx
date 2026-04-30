import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, ChevronRight, Upload, Layers, Circle } from 'lucide-react'
import { clsx } from 'clsx'
import { useAppStore } from '../store/useAppStore'
import { UploadZone } from './UploadZone'

interface Props {
  onProcessStart: () => void
}

export function LeftSidebar({ onProcessStart }: Props) {
  const { images, groups, sessionStatus } = useAppStore()
  const [uploadOpen, setUploadOpen] = useState(true)
  const [groupsOpen, setGroupsOpen] = useState(true)

  const imageCount = Object.keys(images).length
  const groupList  = Object.values(groups)

  const statusColor: Record<string, string> = {
    uploaded:    'text-faint',
    classifying: 'text-warning',
    classified:  'text-accent',
    processing:  'text-gold',
    processed:   'text-success',
    assigned:    'text-success',
    complete:    'text-success',
    error:       'text-danger',
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Upload section */}
      <Section
        title="Upload"
        icon={<Upload className="w-3.5 h-3.5" />}
        open={uploadOpen}
        onToggle={() => setUploadOpen((p) => !p)}
        badge={imageCount > 0 ? imageCount : undefined}
      >
        <UploadZone onProcessStart={onProcessStart} />
      </Section>

      {/* Style groups */}
      {groupList.length > 0 && (
        <Section
          title="Styles"
          icon={<Layers className="w-3.5 h-3.5" />}
          open={groupsOpen}
          onToggle={() => setGroupsOpen((p) => !p)}
          badge={groupList.length}
        >
          <div className="space-y-0.5">
            {groupList.map((g) => {
              const grpImages = g.imageIds.map((id) => images[id]).filter(Boolean)
              const statuses  = grpImages.map((img) => img.status)
              const dominant  = statuses.includes('error')
                ? 'error'
                : statuses.every((s) => s === 'complete')
                ? 'complete'
                : statuses.some((s) => s === 'processing' || s === 'classifying')
                ? 'processing'
                : 'classified'

              return (
                <div
                  key={g.id}
                  className="flex items-center gap-2 rounded-lg px-2.5 py-2 hover:bg-white/[0.04] cursor-pointer transition-colors"
                >
                  <Circle
                    className={clsx('w-2 h-2 flex-shrink-0', statusColor[dominant] ?? 'text-faint')}
                    fill="currentColor"
                  />
                  <span className="text-xs text-text truncate flex-1">{g.styleId}</span>
                  <span className="text-[10px] text-faint flex-shrink-0">{g.imageIds.length}</span>
                </div>
              )
            })}
          </div>
        </Section>
      )}
    </div>
  )
}

function Section({
  title,
  icon,
  open,
  onToggle,
  badge,
  children,
}: {
  title: string
  icon: React.ReactNode
  open: boolean
  onToggle: () => void
  badge?: number
  children: React.ReactNode
}) {
  return (
    <div className="border-b border-white/[0.05]">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-4 py-3 hover:bg-white/[0.02] transition-colors"
      >
        <span className="text-muted">{icon}</span>
        <span className="text-xs font-semibold text-text flex-1 text-left">{title}</span>
        {badge != null && (
          <span className="text-[10px] font-mono text-faint bg-white/5 border border-white/8 rounded px-1.5 py-0.5 mr-1">
            {badge}
          </span>
        )}
        {open
          ? <ChevronDown className="w-3.5 h-3.5 text-faint" />
          : <ChevronRight className="w-3.5 h-3.5 text-faint" />
        }
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
