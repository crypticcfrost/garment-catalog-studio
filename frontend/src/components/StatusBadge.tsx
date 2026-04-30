import { clsx } from 'clsx'
import type { ImageStatus } from '../types'

const CONFIG: Record<ImageStatus, { label: string; dot: string; text: string; pulse: boolean }> = {
  uploaded:    { label: 'Uploaded',    dot: 'bg-faint',   text: 'text-muted',   pulse: false },
  classifying: { label: 'Classifying', dot: 'bg-warning', text: 'text-warning', pulse: true  },
  classified:  { label: 'Classified',  dot: 'bg-accent',  text: 'text-accent',  pulse: false },
  extracting:  { label: 'Extracting',  dot: 'bg-warning', text: 'text-warning', pulse: true  },
  extracted:   { label: 'Extracted',   dot: 'bg-accent',  text: 'text-accent',  pulse: false },
  processing:  { label: 'Processing',  dot: 'bg-gold',    text: 'text-gold',    pulse: true  },
  processed:   { label: 'Processed',   dot: 'bg-success', text: 'text-success', pulse: false },
  assigned:    { label: 'Assigned',    dot: 'bg-success', text: 'text-success', pulse: false },
  complete:    { label: 'Complete',    dot: 'bg-success', text: 'text-success', pulse: false },
  error:       { label: 'Error',       dot: 'bg-danger',  text: 'text-danger',  pulse: false },
}

interface Props {
  status: ImageStatus
  size?: 'sm' | 'md'
}

export function StatusBadge({ status, size = 'sm' }: Props) {
  const cfg = CONFIG[status] ?? CONFIG.uploaded
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full font-medium',
        size === 'sm' ? 'text-[10px] px-2 py-0.5' : 'text-xs px-2.5 py-1',
        'bg-white/5 border border-white/8',
        cfg.text
      )}
    >
      <span className="relative flex h-1.5 w-1.5">
        {cfg.pulse && (
          <span
            className={clsx('ping-slow absolute inline-flex h-full w-full rounded-full', cfg.dot)}
          />
        )}
        <span className={clsx('relative inline-flex rounded-full h-1.5 w-1.5', cfg.dot)} />
      </span>
      {cfg.label}
    </span>
  )
}
