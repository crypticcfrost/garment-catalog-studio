import { create } from 'zustand'
import type {
  ImageItem, StyleGroup, PipelineStep, SessionStatus, GarmentData,
} from '../types'

interface LogEntry {
  ts: number
  message: string
  type: 'info' | 'success' | 'warning' | 'error'
}

interface AppState {
  // Session
  sessionId: string | null
  sessionStatus: SessionStatus

  // Data
  images: Record<string, ImageItem>
  groups: Record<string, StyleGroup>
  pipelineSteps: PipelineStep[]
  pptUrl: string | null
  pptVersion: number

  // UI
  logs: LogEntry[]
  selectedImageId: string | null
  rightPanelOpen: boolean
  slidePreviewOpen: boolean

  // Actions — session
  setSessionId: (id: string) => void
  setSessionStatus: (s: SessionStatus) => void

  // Actions — images
  addImage: (img: ImageItem) => void
  updateImage: (id: string, patch: Partial<ImageItem>) => void
  bulkUpdateImages: (patches: Record<string, Partial<ImageItem>>) => void

  // Actions — groups
  setGroups: (groups: StyleGroup[]) => void
  updateGroup: (id: string, patch: Partial<StyleGroup>) => void

  // Actions — pipeline
  setPipelineSteps: (steps: PipelineStep[]) => void
  updatePipelineStep: (id: string, patch: Partial<PipelineStep>) => void

  // Actions — export
  setPptUrl: (url: string, version?: number) => void

  // Actions — UI
  addLog: (msg: string, type?: LogEntry['type']) => void
  selectImage: (id: string | null) => void
  toggleRightPanel: () => void
  toggleSlidePreview: () => void

  // Actions — manual reclassify
  moveImageToGroup: (imageId: string, targetGroupId: string) => void
}

const INITIAL_STEPS: PipelineStep[] = [
  { id: 'classification', label: 'Image Classification', status: 'pending', progress: 0 },
  { id: 'grouping',       label: 'Style Grouping',       status: 'pending', progress: 0 },
  { id: 'extraction',     label: 'Spec Extraction',      status: 'pending', progress: 0 },
  { id: 'processing',     label: 'Image Processing',     status: 'pending', progress: 0 },
  { id: 'ppt_generation', label: 'PPT Generation',       status: 'pending', progress: 0 },
  { id: 'file_export',    label: 'File Export',          status: 'pending', progress: 0 },
]

export const useAppStore = create<AppState>((set, get) => ({
  sessionId: null,
  sessionStatus: 'idle',
  images: {},
  groups: {},
  pipelineSteps: INITIAL_STEPS,
  pptUrl: null,
  pptVersion: 0,
  logs: [],
  selectedImageId: null,
  rightPanelOpen: true,
  slidePreviewOpen: false,

  setSessionId: (id) => set({ sessionId: id }),
  setSessionStatus: (s) => set({ sessionStatus: s }),

  addImage: (img) =>
    set((state) => ({ images: { ...state.images, [img.id]: img } })),

  updateImage: (id, patch) =>
    set((state) => ({
      images: {
        ...state.images,
        [id]: state.images[id] ? { ...state.images[id], ...patch } : state.images[id],
      },
    })),

  bulkUpdateImages: (patches) =>
    set((state) => {
      const next = { ...state.images }
      for (const [id, patch] of Object.entries(patches)) {
        if (next[id]) next[id] = { ...next[id], ...patch }
      }
      return { images: next }
    }),

  setGroups: (groups) => {
    const map: Record<string, StyleGroup> = {}
    for (const g of groups) map[g.id] = g
    set({ groups: map })
  },

  updateGroup: (id, patch) =>
    set((state) => ({
      groups: {
        ...state.groups,
        [id]: state.groups[id] ? { ...state.groups[id], ...patch } : state.groups[id],
      },
    })),

  setPipelineSteps: (steps) => set({ pipelineSteps: steps }),

  updatePipelineStep: (id, patch) =>
    set((state) => ({
      pipelineSteps: state.pipelineSteps.map((s) =>
        s.id === id ? { ...s, ...patch } : s
      ),
    })),

  setPptUrl: (url, version) =>
    set((state) => ({
      pptUrl: url,
      pptVersion: version ?? state.pptVersion + 1,
    })),

  addLog: (msg, type = 'info') =>
    set((state) => ({
      logs: [{ ts: Date.now(), message: msg, type }, ...state.logs].slice(0, 120),
    })),

  selectImage: (id) => set({ selectedImageId: id }),
  toggleRightPanel: () => set((s) => ({ rightPanelOpen: !s.rightPanelOpen })),
  toggleSlidePreview: () => set((s) => ({ slidePreviewOpen: !s.slidePreviewOpen })),

  moveImageToGroup: (imageId, targetGroupId) =>
    set((state) => {
      const groups = { ...state.groups }
      // Remove from current group
      for (const g of Object.values(groups)) {
        const idx = g.imageIds.indexOf(imageId)
        if (idx !== -1) {
          groups[g.id] = { ...g, imageIds: g.imageIds.filter((id) => id !== imageId) }
        }
      }
      // Add to target
      if (groups[targetGroupId]) {
        groups[targetGroupId] = {
          ...groups[targetGroupId],
          imageIds: [...groups[targetGroupId].imageIds, imageId],
        }
      }
      return { groups }
    }),
}))
