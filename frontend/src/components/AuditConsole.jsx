import { useEffect, useRef, useState } from 'react'
import { get, wsURL, formatTime, formatDate } from '../api'
import Badge from './shared/Badge'

const VERDICT_TONE = {
  ALLOWED: 'emerald',
  NEEDS_APPROVAL: 'amber',
  BLOCKED: 'rose',
}

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'money', label: 'Money actions' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'approvals', label: 'Approvals' },
]

function isMoneyTool(tool) {
  return (
    typeof tool === 'string' &&
    (tool.startsWith('create_') || tool.startsWith('post_') || tool.startsWith('webhook:'))
  )
}

function StatusIcon({ status }) {
  if (status === 'pending' || status === 'awaiting_approval') {
    return <span className="pulse-dot inline-block h-2 w-2 rounded-full bg-amber-400" title={status} />
  }
  if (status === 'success') {
    return (
      <span className="text-emerald-400" title="success">
        &#10003;
      </span>
    )
  }
  if (status === 'failed' || status === 'blocked') {
    return (
      <span className="text-rose-400" title={status}>
        &#10007;
      </span>
    )
  }
  return <span className="text-slate-500">&middot;</span>
}

function AuditRow({ entry, isNew }) {
  const [open, setOpen] = useState(false)
  const hasDetail =
    entry.agent_reasoning || entry.policy_rule_hit || entry.razorpay_ref || entry.error ||
    (entry.args && Object.keys(entry.args).length > 0)

  return (
    <div
      className={`border-b border-slate-800/60 font-mono text-[12px] ${isNew ? 'flash-emerald' : ''}`}
    >
      <button
        onClick={() => hasDetail && setOpen((v) => !v)}
        className={`w-full flex items-center gap-3 px-3 py-2 text-left ${
          hasDetail ? 'hover:bg-slate-800/40 cursor-pointer' : 'cursor-default'
        }`}
      >
        <span className="text-slate-500 w-20 shrink-0">{formatTime(entry.ts)}</span>
        <Badge tone="sky" className="shrink-0">
          {entry.actor}
        </Badge>
        <span className="text-slate-200 shrink-0 truncate max-w-[220px]">{entry.tool}</span>
        <Badge tone={VERDICT_TONE[entry.policy_verdict] || 'slate'} className="shrink-0">
          {entry.policy_verdict || 'n/a'}
        </Badge>
        {entry.policy_rule_hit && (
          <span className="text-slate-500 truncate flex-1 text-[11px]">{entry.policy_rule_hit}</span>
        )}
        <span className="ml-auto shrink-0 flex items-center gap-2">
          <StatusIcon status={entry.status} />
          {hasDetail && <span className="text-slate-600">{open ? '▲' : '▼'}</span>}
        </span>
      </button>

      {open && hasDetail && (
        <div className="px-3 pb-3 space-y-2 bg-slate-950/40">
          {entry.args && Object.keys(entry.args).length > 0 && (
            <pre className="text-[11px] text-slate-300 bg-slate-950/60 rounded-lg p-2 overflow-x-auto border border-slate-800">
              {JSON.stringify(entry.args, null, 2)}
            </pre>
          )}
          {entry.agent_reasoning && (
            <p className="text-[11px] text-slate-400 italic">&ldquo;{entry.agent_reasoning}&rdquo;</p>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
            {entry.policy_rule_hit && (
              <span>
                rule: <span className="text-slate-300">{entry.policy_rule_hit}</span>
              </span>
            )}
            {entry.razorpay_ref && (
              <span>
                razorpay_ref: <span className="text-sky-400">{entry.razorpay_ref}</span>
              </span>
            )}
            {entry.error && (
              <span>
                error: <span className="text-rose-400">{entry.error}</span>
              </span>
            )}
            {entry.completed_ts && (
              <span>
                completed: <span className="text-slate-300">{formatDate(entry.completed_ts)} {formatTime(entry.completed_ts)}</span>
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default function AuditConsole({ refresh }) {
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [connected, setConnected] = useState(false)
  const [filter, setFilter] = useState('all')
  const [freshIds, setFreshIds] = useState(() => new Set())

  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const mountedRef = useRef(true)
  const firstLoad = useRef(true)

  useEffect(() => {
    // Only the first load shows the full-page loader; later refresh bumps
    // (e.g. from a live review) reload quietly — the live WS feed already
    // keeps entries current, this is just a periodic resync.
    if (firstLoad.current) setLoading(true)
    setError(null)
    get('/api/audit?limit=100')
      .then((r) => setEntries(r.entries || []))
      .catch((e) => setError(e.message))
      .finally(() => {
        setLoading(false)
        firstLoad.current = false
      })
  }, [refresh])

  useEffect(() => {
    mountedRef.current = true

    function connect() {
      if (!mountedRef.current) return
      let ws
      try {
        ws = new WebSocket(wsURL('/ws/audit'))
      } catch {
        scheduleReconnect()
        return
      }
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) return
        setConnected(true)
      }

      ws.onmessage = (event) => {
        if (!mountedRef.current) return
        let incoming
        try {
          incoming = JSON.parse(event.data)
        } catch {
          return
        }
        setEntries((prev) => {
          const idx = prev.findIndex((e) => e.id === incoming.id)
          if (idx === -1) return [incoming, ...prev]
          const next = [...prev]
          next[idx] = incoming
          return next
        })
        setFreshIds((prev) => {
          const next = new Set(prev)
          next.add(incoming.id)
          return next
        })
        setTimeout(() => {
          if (!mountedRef.current) return
          setFreshIds((prev) => {
            const next = new Set(prev)
            next.delete(incoming.id)
            return next
          })
        }, 1100)
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        setConnected(false)
        scheduleReconnect()
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    function scheduleReconnect() {
      if (reconnectTimer.current) return
      reconnectTimer.current = setTimeout(() => {
        reconnectTimer.current = null
        connect()
      }, 2000)
    }

    connect()

    return () => {
      mountedRef.current = false
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [])

  const filtered = entries.filter((e) => {
    if (filter === 'money') return isMoneyTool(e.tool)
    if (filter === 'blocked') return e.policy_verdict === 'BLOCKED' || e.status === 'blocked'
    if (filter === 'approvals') return e.policy_verdict === 'NEEDS_APPROVAL'
    return true
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
              filter === f.key
                ? 'bg-slate-800 border-slate-700 text-slate-100'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            {f.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 text-[11px] text-slate-400">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              connected ? 'bg-emerald-400' : 'bg-amber-400 pulse-dot'
            }`}
          />
          {connected ? 'live' : 'reconnecting'}
        </div>
      </div>

      <div className="bg-slate-950 border border-slate-800 rounded-xl overflow-hidden">
        <div className="flex items-center gap-3 px-3 py-2 border-b border-slate-800 text-[11px] text-slate-500 font-mono">
          <span className="w-20 shrink-0">time</span>
          <span className="shrink-0 w-16">actor</span>
          <span className="shrink-0">tool</span>
        </div>
        <div className="max-h-[600px] overflow-y-auto">
          {loading ? (
            <div className="px-3 py-4 text-xs text-slate-400">Loading audit trail…</div>
          ) : error ? (
            <div className="px-3 py-4 text-xs text-rose-400">Failed to load: {error}</div>
          ) : filtered.length === 0 ? (
            <div className="px-3 py-4 text-xs text-slate-500">No entries match this filter.</div>
          ) : (
            filtered.map((e) => <AuditRow key={e.id} entry={e} isNew={freshIds.has(e.id)} />)
          )}
        </div>
      </div>
    </div>
  )
}
