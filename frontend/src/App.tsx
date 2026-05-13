import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { PanelRightOpen, PanelRightClose } from 'lucide-react'
import { clsx } from 'clsx'

import { Header } from './components/Header'
import { LeftSidebar } from './components/LeftSidebar'
import { WorkspaceCanvas } from './components/WorkspaceCanvas'
import { PipelinePanel } from './components/PipelinePanel'
import { SlidePreviewBar } from './components/SlidePreviewBar'
import { useWebSocket } from './hooks/useWebSocket'
import { useAppStore } from './store/useAppStore'
import { apiUrl } from './config'

export default function App() {
  const {
    sessionId,
    setSessionId,
    rightPanelOpen,
    toggleRightPanel,
    addLog,
  } = useAppStore()

  const [sessionReady, setSessionReady] = useState(false)
  const [initError, setInitError] = useState<string | null>(null)

  // Create session on mount
  useEffect(() => {
    const init = async () => {
      try {
        const res = await fetch(apiUrl('/api/sessions'), { method: 'POST' })
        const text = await res.text()
        if (!res.ok) {
          let detail = text.slice(0, 400)
          try {
            const j = JSON.parse(text) as { detail?: string | unknown[] }
            if (typeof j.detail === 'string') detail = j.detail
            else if (Array.isArray(j.detail))
              detail = j.detail.map((d) => (typeof d === 'object' && d && 'msg' in d ? String((d as { msg: string }).msg) : JSON.stringify(d))).join('; ')
          } catch {
            /* keep raw slice */
          }
          throw new Error(`HTTP ${res.status}: ${detail}`)
        }
        const data = JSON.parse(text) as { session_id: string }
        setSessionId(data.session_id)
        setSessionReady(true)
        setInitError(null)
        addLog(`Session created: #${data.session_id}`, 'success')
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        setInitError(msg)
        addLog(`Failed to create session: ${e}`, 'error')
      }
    }
    init()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Connect WebSocket after session is ready
  useWebSocket(sessionReady ? sessionId : null)

  const handleProcessStart = () => {
    addLog('Pipeline started', 'info')
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-bg text-text">
      <Header />

      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar */}
        <aside className="w-64 flex-shrink-0 border-r border-white/[0.05] bg-surface1/50 overflow-y-auto">
          <LeftSidebar onProcessStart={handleProcessStart} />
        </aside>

        {/* Main workspace */}
        <main className="flex-1 flex flex-col overflow-hidden bg-bg relative">
          <WorkspaceCanvas />
          <SlidePreviewBar />
        </main>

        {/* Right pipeline panel */}
        <motion.aside
          animate={{ width: rightPanelOpen ? 320 : 0 }}
          transition={{ type: 'spring', stiffness: 400, damping: 40 }}
          className="flex-shrink-0 border-l border-white/[0.05] bg-surface1/50 overflow-hidden"
        >
          {rightPanelOpen && (
            <div className="w-80 h-full overflow-hidden">
              <PipelinePanel />
            </div>
          )}
        </motion.aside>

        {/* Toggle button */}
        <button
          onClick={toggleRightPanel}
          className={clsx(
            'absolute right-0 top-1/2 -translate-y-1/2 z-10',
            'w-5 h-10 flex items-center justify-center',
            'bg-surface2 border border-white/8 rounded-l-md',
            'hover:bg-surface3 transition-colors',
            rightPanelOpen ? 'translate-x-[-320px]' : ''
          )}
          style={{
            right: rightPanelOpen ? '320px' : '0',
            transition: 'right 0.35s cubic-bezier(0.4,0,0.2,1)',
          }}
        >
          {rightPanelOpen ? (
            <PanelRightClose className="w-3 h-3 text-muted" />
          ) : (
            <PanelRightOpen className="w-3 h-3 text-muted" />
          )}
        </button>
      </div>

      {/* Loading overlay */}
      {!sessionReady && (
        <motion.div
          initial={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 bg-bg flex items-center justify-center px-6"
        >
          <div className="text-center space-y-4 max-w-md">
            {!initError ? (
              <>
                <div className="w-12 h-12 border-2 border-accent/30 border-t-accent rounded-full animate-spin mx-auto" />
                <p className="text-sm text-muted">Initialising session…</p>
              </>
            ) : (
              <>
                <p className="text-sm text-danger">
                  Could not start a session ({initError}).
                </p>
                <p className="text-xs text-muted">
                  Check that you are online and the app finished deploying. If the problem continues,
                  try again in a moment.
                </p>
                <button
                  type="button"
                  onClick={() => window.location.reload()}
                  className="text-xs font-medium px-4 py-2 rounded-lg border border-white/15 hover:bg-white/5 text-text"
                >
                  Retry
                </button>
              </>
            )}
          </div>
        </motion.div>
      )}
    </div>
  )
}
