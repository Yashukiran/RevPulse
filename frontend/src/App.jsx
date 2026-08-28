import { useEffect, useRef, useState, useCallback } from 'react'
import { get, post, wsURL, onApiWaking, invalidate } from './api'
import Sidebar from './components/shared/Sidebar'
import ToastStack from './components/shared/Toast'
import Overview from './components/Overview'
import IssuesOpportunities from './components/IssuesOpportunities'
import ReplyQueue from './components/ReplyQueue'
import DemandPlanning from './components/DemandPlanning'
import RevenueIntelligence from './components/RevenueIntelligence'
import ActionCenter from './components/ActionCenter'
import AuditConsole from './components/AuditConsole'

const TITLES = {
  overview: 'Overview',
  issues: 'Issues & Opportunities',
  reply: 'Reply Queue',
  demand: 'Demand Planning',
  revenue: 'Revenue Intelligence',
  action: 'Action Center',
  audit: 'Audit Console',
}

// Each screen answers one question, in the order a merchant asks them.
const SUBTITLES = {
  overview: 'What is happening — business health at a glance',
  issues: 'Where the problems and opportunities are, with the evidence',
  reply: 'Reviews as they arrive, triaged and ready to answer',
  demand: 'What is coming, what will sell, and what to prepare',
  revenue: 'Did it actually make money — transactions, top items, associations',
  action: 'What the agent proposes, what you approve, and what it earned',
  audit: 'Proof of exactly what happened — every call, verdict and outcome',
}

export default function App() {
  const [view, setView] = useState('overview')
  const [refresh, setRefresh] = useState(0)
  const [merchant, setMerchant] = useState(null)

  const [reviewsConnected, setReviewsConnected] = useState(false)
  const [incomingReview, setIncomingReview] = useState(null)
  const [toasts, setToasts] = useState([])

  // True while the API is being woken from idle. Shown as a banner so a cold
  // start reads as "starting up" rather than "the dashboard is broken".
  const [apiWaking, setApiWaking] = useState(false)
  useEffect(() => onApiWaking(setApiWaking), [])

  // The agent run lives here, not inside Action Center, so switching views
  // mid-run neither cancels it nor throws away the answer.
  const [agentRun, setAgentRun] = useState({
    message: '',
    running: false,
    result: null,
    error: null,
    events: [],
  })
  const runningRef = useRef(false)

  // Every refresh trigger — a live review, a found opportunity, a finished
  // agent run — means the cached reads are out of date, so drop them first.
  const bumpRefresh = useCallback(() => {
    invalidate()
    setRefresh((n) => n + 1)
  }, [])

  const setAgentMessage = useCallback((message) => {
    setAgentRun((s) => ({ ...s, message }))
  }, [])

  const runAgent = useCallback(
    (message) => {
      if (!message.trim() || runningRef.current) return
      runningRef.current = true
      setAgentRun({ message, running: true, result: null, error: null, events: [] })
      post('/api/agent/run', { message })
        .then((res) => setAgentRun((s) => ({ ...s, running: false, result: res })))
        .catch((e) => setAgentRun((s) => ({ ...s, running: false, error: e.message })))
        .finally(() => {
          runningRef.current = false
          bumpRefresh()
        })
    },
    [bumpRefresh]
  )

  const addToast = useCallback((text) => {
    const id = `${Date.now()}-${Math.random()}`
    setToasts((prev) => [...prev, { id, text }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 4000)
  }, [])

  useEffect(() => {
    get('/api/merchant')
      .then(setMerchant)
      .catch(() => setMerchant(null))
  }, [])

  // Single WebSocket for live review submissions: bumps the shared refresh
  // counter so Overview/Issues/Reply Queue quietly refetch, toasts the
  // merchant, and hands the raw event down to the reply queue.
  useEffect(() => {
    let mounted = true
    let ws = null
    let reconnectTimer = null

    function connect() {
      if (!mounted) return
      try {
        ws = new WebSocket(wsURL('/ws/reviews'))
      } catch {
        scheduleReconnect()
        return
      }

      ws.onopen = () => {
        if (mounted) setReviewsConnected(true)
      }

      ws.onmessage = (event) => {
        if (!mounted) return
        let msg
        try {
          msg = JSON.parse(event.data)
        } catch {
          return
        }
        if (msg?.type === 'opportunity') {
          bumpRefresh()
          addToast('Agent found a revenue opportunity')
          return
        }
        setIncomingReview(msg)
        bumpRefresh()
        addToast('New review received — dashboards updated')
      }

      ws.onclose = () => {
        if (!mounted) return
        setReviewsConnected(false)
        scheduleReconnect()
      }

      ws.onerror = () => {
        ws?.close()
      }
    }

    function scheduleReconnect() {
      if (reconnectTimer) return
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        connect()
      }, 2000)
    }

    connect()

    return () => {
      mounted = false
      if (reconnectTimer) clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [bumpRefresh, addToast])

  // Audit stream, used here only to show the agent's moves inline while a run
  // is in flight (the Audit Console keeps its own full-history connection).
  useEffect(() => {
    let mounted = true
    let ws = null
    let reconnectTimer = null

    function connect() {
      if (!mounted) return
      try {
        ws = new WebSocket(wsURL('/ws/audit'))
      } catch {
        scheduleReconnect()
        return
      }
      ws.onmessage = (event) => {
        if (!mounted || !runningRef.current) return
        let entry
        try {
          entry = JSON.parse(event.data)
        } catch {
          return
        }
        setAgentRun((s) => {
          if (!s.running) return s
          const events = s.events.filter((e) => e.id !== entry.id)
          return { ...s, events: [...events, entry].slice(-40) }
        })
      }
      ws.onclose = () => {
        if (mounted) scheduleReconnect()
      }
      ws.onerror = () => ws?.close()
    }

    function scheduleReconnect() {
      if (reconnectTimer) return
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        connect()
      }, 2000)
    }

    connect()
    return () => {
      mounted = false
      if (reconnectTimer) clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [])

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 text-[13px]">
      <Sidebar
        active={view}
        onSelect={setView}
        merchantName={merchant?.name}
        merchantCity={merchant?.city}
      />
      <main className="pl-56 min-h-screen flex flex-col">
        <header className="px-8 pt-6 pb-4 border-b border-slate-800/60 shrink-0">
          <h2 className="text-xl font-semibold tracking-tight text-slate-100">{TITLES[view]}</h2>
          <p className="mt-0.5 text-xs text-slate-400">{SUBTITLES[view]}</p>
        </header>
        {apiWaking && (
          <div className="mx-8 mt-4 flex items-center gap-2.5 rounded-lg border border-amber-400/40 bg-amber-400/10 px-4 py-2.5 text-xs text-amber-300">
            <span className="pulse-dot h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
            Starting the API — free hosting suspends it when idle. This takes up to a
            minute the first time; the page fills in on its own.
          </div>
        )}
        <div className="flex-1 px-8 py-6">
          {view === 'overview' && (
            <Overview refresh={refresh} live={reviewsConnected} onNavigate={setView} />
          )}
          {view === 'issues' && <IssuesOpportunities refresh={refresh} />}
          {view === 'reply' && (
            <ReplyQueue
              refresh={refresh}
              incomingReview={incomingReview}
              reviewsConnected={reviewsConnected}
            />
          )}
          {view === 'demand' && <DemandPlanning refresh={refresh} />}
          {view === 'revenue' && <RevenueIntelligence refresh={refresh} />}
          {view === 'action' && (
            <ActionCenter
              refresh={refresh}
              bumpRefresh={bumpRefresh}
              agentRun={agentRun}
              onAgentMessage={setAgentMessage}
              onRunAgent={runAgent}
            />
          )}
          {view === 'audit' && <AuditConsole refresh={refresh} />}
        </div>
      </main>
      <ToastStack toasts={toasts} />
    </div>
  )
}
