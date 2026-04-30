import { motion, AnimatePresence } from 'framer-motion'
import { useDroppable } from '@dnd-kit/core'
import { SortableContext, rectSortingStrategy } from '@dnd-kit/sortable'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { clsx } from 'clsx'
import { Tag, Layers } from 'lucide-react'
import { ImageCard } from './ImageCard'
import { useAppStore } from '../store/useAppStore'
import type { StyleGroup } from '../types'

interface Props {
  group: StyleGroup
}

export function StyleGroupCluster({ group }: Props) {
  const { images, selectedImageId, selectImage } = useAppStore()
  const groupImages = group.imageIds.map((id) => images[id]).filter(Boolean)

  const { setNodeRef, isOver } = useDroppable({ id: group.id })

  const gdata = group.garmentData

  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.95, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      className={clsx(
        'rounded-2xl border p-3 flex flex-col gap-3',
        'bg-surface2/60',
        isOver ? 'border-accent/50 bg-accent/5' : 'border-white/8',
        'transition-colors duration-150'
      )}
      ref={setNodeRef}
    >
      {/* Group header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-6 h-6 rounded-md bg-accent/15 border border-accent/25 flex items-center justify-center flex-shrink-0">
            <Layers className="w-3 h-3 text-accent" />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-text truncate">{group.styleId}</p>
            {group.garmentType && (
              <p className="text-[10px] text-muted capitalize">{group.garmentType}</p>
            )}
          </div>
        </div>
        <span className="text-[10px] text-faint flex-shrink-0 mt-0.5">
          {groupImages.length} image{groupImages.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Spec data preview */}
      {gdata && (gdata.reference_number || gdata.fabric_composition || gdata.gsm) && (
        <div className="rounded-lg bg-surface3/60 border border-white/5 px-2.5 py-2 space-y-1">
          {gdata.reference_number && (
            <SpecRow label="REF" value={gdata.reference_number} />
          )}
          {gdata.fabric_composition && (
            <SpecRow label="COMP" value={gdata.fabric_composition} />
          )}
          {gdata.gsm && <SpecRow label="GSM" value={gdata.gsm} />}
          {gdata.date && <SpecRow label="DATE" value={gdata.date} />}
        </div>
      )}

      {/* Image grid */}
      <SortableContext items={group.imageIds} strategy={rectSortingStrategy}>
        <div className="grid grid-cols-2 gap-1.5">
          <AnimatePresence>
            {groupImages.map((img) => (
              <SortableImageCard
                key={img.id}
                imageId={img.id}
                selected={selectedImageId === img.id}
                onSelect={selectImage}
              />
            ))}
          </AnimatePresence>
        </div>
      </SortableContext>

      {/* Slide number badge */}
      {group.slideNumber != null && (
        <div className="flex justify-end">
          <span className="text-[9px] font-mono text-faint bg-white/5 border border-white/8 rounded px-1.5 py-0.5">
            SLIDE {group.slideNumber}
          </span>
        </div>
      )}
    </motion.div>
  )
}

function SortableImageCard({
  imageId,
  selected,
  onSelect,
}: {
  imageId: string
  selected: boolean
  onSelect: (id: string) => void
}) {
  const { images } = useAppStore()
  const image = images[imageId]
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: imageId })

  if (!image) return null

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={clsx(isDragging && 'dragging')}
      {...attributes}
      {...listeners}
    >
      <ImageCard image={image} compact selected={selected} onSelect={onSelect} draggable />
    </div>
  )
}

function SpecRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[9px] font-bold text-faint w-8 flex-shrink-0">{label}</span>
      <span className="text-[10px] text-muted truncate">{value}</span>
    </div>
  )
}
