import { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  DndContext, DragEndEvent, DragOverlay, DragStartEvent,
  PointerSensor, useSensor, useSensors, closestCenter,
} from '@dnd-kit/core'
import { arrayMove, SortableContext } from '@dnd-kit/sortable'
import { clsx } from 'clsx'
import { Grid3X3, Layers, LayoutGrid } from 'lucide-react'

import { StyleGroupCluster } from './StyleGroupCluster'
import { ImageCard } from './ImageCard'
import { useAppStore } from '../store/useAppStore'
import { apiUrl } from '../config'
import { UploadZone } from './UploadZone'

type ViewMode = 'grouped' | 'grid'

export function WorkspaceCanvas() {
  const {
    images, groups, sessionStatus, selectedImageId, selectImage,
    moveImageToGroup, sessionId, addLog,
  } = useAppStore()

  const [viewMode, setViewMode] = useState<ViewMode>('grouped')
  const [activeDragId, setActiveDragId] = useState<string | null>(null)

  const imageList = Object.values(images)
  const groupList = Object.values(groups)
  const hasImages = imageList.length > 0
  const hasGroups = groupList.length > 0

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } })
  )

  const handleDragStart = useCallback((e: DragStartEvent) => {
    setActiveDragId(String(e.active.id))
  }, [])

  const handleDragEnd = useCallback(
    async (e: DragEndEvent) => {
      setActiveDragId(null)
      const { active, over } = e
      if (!over || active.id === over.id) return

      const overId = String(over.id)
      const activeId = String(active.id)

      // Check if dropped over a group container
      const targetGroup = groups[overId]
      if (targetGroup) {
        moveImageToGroup(activeId, overId)
        // Persist to backend
        if (sessionId) {
          try {
            await fetch(
              apiUrl(`/api/sessions/${sessionId}/images/${activeId}/reclassify`),
              {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ group_id: overId }),
              }
            )
          } catch {
            addLog(`Manual reclassify failed for ${activeId}`, 'warning')
          }
        }
      }
    },
    [groups, moveImageToGroup, sessionId, addLog]
  )

  const activeImage = activeDragId ? images[activeDragId] : null

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Toolbar */}
      {hasImages && (
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/[0.05] bg-surface1/40 flex-shrink-0">
          <span className="text-xs text-muted flex-1">
            {hasGroups
              ? `${groupList.length} styles · ${imageList.length} images`
              : `${imageList.length} images — awaiting grouping`}
          </span>
          <div className="flex items-center gap-1 bg-surface3/60 border border-white/8 rounded-lg p-0.5">
            <ToolbarBtn
              active={viewMode === 'grouped'}
              onClick={() => setViewMode('grouped')}
              title="Grouped view"
            >
              <Layers className="w-3.5 h-3.5" />
            </ToolbarBtn>
            <ToolbarBtn
              active={viewMode === 'grid'}
              onClick={() => setViewMode('grid')}
              title="Grid view"
            >
              <LayoutGrid className="w-3.5 h-3.5" />
            </ToolbarBtn>
          </div>
        </div>
      )}

      {/* Main area */}
      <div className="flex-1 overflow-auto dot-grid relative">
        {!hasImages ? (
          // Empty state — centered upload
          <div className="absolute inset-0 flex items-center justify-center p-8">
            <div className="w-full max-w-md">
              <EmptyState />
            </div>
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragStart={handleDragStart}
            onDragEnd={handleDragEnd}
          >
            <div className="p-4">
              <AnimatePresence mode="wait">
                {viewMode === 'grouped' && hasGroups ? (
                  <motion.div
                    key="grouped"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="columns-1 sm:columns-2 lg:columns-3 xl:columns-4 gap-3 space-y-3"
                  >
                    {groupList.map((group) => (
                      <div key={group.id} className="break-inside-avoid mb-3">
                        <StyleGroupCluster group={group} />
                      </div>
                    ))}

                    {/* Ungrouped images */}
                    {(() => {
                      const groupedIds = new Set(groupList.flatMap((g) => g.imageIds))
                      const ungrouped = imageList.filter((img) => !groupedIds.has(img.id))
                      if (ungrouped.length === 0) return null
                      return (
                        <div className="break-inside-avoid mb-3">
                          <div className="rounded-2xl border border-dashed border-white/10 p-3 space-y-3">
                            <p className="text-xs text-faint">Ungrouped</p>
                            <div className="grid grid-cols-2 gap-1.5">
                              {ungrouped.map((img) => (
                                <ImageCard
                                  key={img.id}
                                  image={img}
                                  compact
                                  selected={selectedImageId === img.id}
                                  onSelect={selectImage}
                                  draggable
                                />
                              ))}
                            </div>
                          </div>
                        </div>
                      )
                    })()}
                  </motion.div>
                ) : (
                  <motion.div
                    key="grid"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-8 gap-3"
                  >
                    {imageList.map((img) => (
                      <ImageCard
                        key={img.id}
                        image={img}
                        selected={selectedImageId === img.id}
                        onSelect={selectImage}
                        draggable
                      />
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* Drag overlay */}
            <DragOverlay>
              {activeImage && (
                <div className="w-24 rotate-3 opacity-90">
                  <ImageCard image={activeImage} compact />
                </div>
              )}
            </DragOverlay>
          </DndContext>
        )}
      </div>
    </div>
  )
}

function ToolbarBtn({
  active,
  onClick,
  title,
  children,
}: {
  active: boolean
  onClick: () => void
  title: string
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={clsx(
        'w-7 h-7 rounded flex items-center justify-center transition-colors',
        active ? 'bg-surface1 text-text' : 'text-faint hover:text-muted'
      )}
    >
      {children}
    </button>
  )
}

function EmptyState() {
  return (
    <div className="text-center space-y-6">
      <div className="flex justify-center">
        <div className="w-20 h-20 rounded-2xl border border-white/8 bg-surface2 flex items-center justify-center">
          <Grid3X3 className="w-8 h-8 text-faint" />
        </div>
      </div>
      <div>
        <h2 className="text-lg font-semibold text-text mb-2">Upload Garment Images</h2>
        <p className="text-sm text-muted max-w-xs mx-auto">
          Add 3–4 photos per garment style — front, back, detail, and spec label
        </p>
      </div>
    </div>
  )
}
