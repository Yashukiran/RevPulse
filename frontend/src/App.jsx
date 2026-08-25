import { useEffect, useRef, useState, useCallback } from 'react'
import { get, post, wsURL } from './api'
import Sidebar from './components/shared/Sidebar'
import ToastStack from './components/shared/Toast'
import Overview from './components/Overview'
import IssuesOpportunities from './components/IssuesOpportunities'
import ReplyQueue from './components/ReplyQueue'
import LiveFeedback from './components/LiveFeedback'
import RevenueIntelligence from './components/RevenueIntelligence'
import ActionCenter from './components/ActionCenter'
import AuditConsole from './components/AuditConsole'

const TITLES = {
  overview: 'Overview',
  issues: 'Issues & Opportunities',
  reply: 'Reply Queue',
  livefeedback: 'Live Feedback',
  revenue: 'Revenue Intelligence',
  action: 'Action Center',
  audit: 'Audit Console',
}

const SUBTITLES = {
  overview: 'Review intelligence at a glance',
  issues: 'Detected problems and growth opportunities, with evidence',
  reply: 'Triaged reviews awaiting a response',
  livefeedback: 'Real-time customer feedback, labeled as it arrives',
  revenue: 'Transactions, top items, and theme-revenue association',
  action: 'Run the agent, approve gated actions, track campaigns',
  audit: 'Live ops trail — every tool call, policy verdict, and outcome',
}

export default function App() {
  const [view, setView] = useState('overview')
  const [refresh, setRefresh] = useState(0)
  const [merchant, setMerchant] = useState(null)

  const [reviewsConnected, setReviewsConnected] = useState(false)
  const [incomingReview, setIncomingReview] = useState(null)
  const [toasts, setToasts] = useState([])

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

  const bumpRefresh = useCallback(() => setRefresh((n) => n + 1), [])

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
  // merchant, and hands the raw event down to Live Feedback's stream.
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
        let review
        try {
          review = JSON.parse(event.data)
        } catch {
          return
        }
        setIncomingReview(review)
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
        <div className="flex-1 px-8 py-6">
          {view === 'overview' && <Overview refresh={refresh} live={reviewsConnected} />}
          {view === 'issues' && <IssuesOpportunities refresh={refresh} />}
          {view === 'reply' && <ReplyQueue refresh={refresh} bumpRefresh={bumpRefresh} />}
          {view === 'livefeedback' && (
            <LiveFeedback incomingReview={incomingReview} reviewsConnected={reviewsConnected} />
          )}
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
