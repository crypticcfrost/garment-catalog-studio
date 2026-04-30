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

const API = 'http://localhost:8000'

export default function App() {
  const {
    sessionId,
    setSessionId,
    rightPanelOpen,
    toggleRightPanel,
    addLog,
  } = useAppStore()

  const [sessionReady, setSessionReady] = useState(false)

  // Create session on mount
  useEffect(() => {
    const init = async () => {
      try {
        const res = await fetch(`${API}/api/sessions`, { method: 'POST' })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        setSessionId(data.session_id)
        setSessionReady(true)
        addLog(`Session created: #${data.session_id}`, 'success')
      } catch (e) {
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
          className="fixed inset-0 z-50 bg-bg flex items-center justify-center"
        >
          <div className="text-center space-y-4">
            <div className="w-12 h-12 border-2 border-accent/30 border-t-accent rounded-full animate-spin mx-auto" />
            <p className="text-sm text-muted">Initialising session…</p>
          </div>
        </motion.div>
      )}
    </div>
  )
}
