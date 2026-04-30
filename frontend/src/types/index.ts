export type ImageStatus =
  | 'uploaded'
  | 'classifying'
  | 'classified'
  | 'extracting'
  | 'extracted'
  | 'processing'
  | 'processed'
  | 'assigned'
  | 'complete'
  | 'error'

export type ImageType = 'front' | 'back' | 'detail' | 'spec_label' | 'unknown'

export interface GarmentData {
  reference_number?: string | null
  fabric_composition?: string | null
  gsm?: string | null
  date?: string | null
  garment_type?: string | null
  brand?: string | null
  size?: string | null
  origin?: string | null
  colors?: string[]
}

export interface ImageItem {
  id: string
  filename: string
  previewUrl: string         // local blob URL or /uploads/...
  processedUrl?: string      // /outputs/.../processed/...
  status: ImageStatus
  imageType?: ImageType
  styleId?: string
  confidence: number
  garmentData?: GarmentData
  errorMessage?: string
  colors?: string[]
  description?: string
  retryCount?: number
}

export interface StyleGroup {
  id: string
  styleId: string
  garmentType?: string
  imageIds: string[]
  garmentData?: GarmentData
  slideNumber?: number
}

export interface PipelineStep {
  id: string
  label: string
  status: 'pending' | 'running' | 'complete' | 'error'
  progress: number
  message?: string
}

export type SessionStatus = 'idle' | 'uploading' | 'processing' | 'complete' | 'error'

export interface WSEvent {
  type: string
  session_id: string
  data: Record<string, unknown>
  ts: number
}
