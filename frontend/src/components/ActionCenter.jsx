import { useEffect, useState } from 'react'
import { get, post, formatINR, formatDate } from '../api'
import Badge from './shared/Badge'
import Spinner from './shared/Spinner'

const VERDICT_TONE = {
  ALLOWED: 'emerald',
  NEEDS_APPROVAL: 'amber',
  BLOCKED: 'rose',
}

function renderInline(text, keyPrefix) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? (
      <strong key={`${keyPrefix}-${i}`} className="font-semibold text-slate-100">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <span key={`${keyPrefix}-${i}`}>{part}</span>
    )
  )
}

function AgentText({ text }) {
  if (!text) return null
  const lines = text.split('\n')
  return (
    <div className="space-y-1">
      {lines.map((line, i) => {
        const trimmed = line.trim()
        if (trimmed.startsWith('## ')) {
          return (
            <h4 key={i} className="text-sm font-semibold text-sky-400 mt-3 first:mt-0">
              {renderInline(trimmed.slice(3), i)}
            </h4>
          )
        }
        if (trimmed.startsWith('# ')) {
          return (
            <h3 key={i} className="text-base font-semibold text-slate-100 mt-3 first:mt-0">
              {renderInline(trimmed.slice(2), i)}
            </h3>
          )
        }
        if (trimmed === '') return <div key={i} className="h-1.5" />
        if (/^[-*]\s/.test(trimmed)) {
          return (
            <li key={i} className="text-xs text-slate-300 ml-4 list-disc leading-relaxed">
              {renderInline(trimmed.slice(2), i)}
            </li>
          )
        }
        return (
          <p key={i} className="text-xs text-slate-300 leading-relaxed">
            {renderInline(line, i)}
          </p>
        )
      })}
    </div>
  )
}

function ApprovalCard({ approval, onDecided }) {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [decision, setDecision] = useState(null)
  const [error, setError] = useState(null)

  const approve = () => {
    setBusy(true)
    setError(null)
    post(`/api/approvals/${approval.id}/approve`)
      .then((res) => {
        setResult(res.result)
        setDecision('approved')
        onDecided()
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false))
  }

  const reject = () => {
    setBusy(true)
    setError(null)
    post(`/api/approvals/${approval.id}/reject`)
      .then(() => {
        setDecision('rejected')
        onDecided()
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false))
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-sky-400">{approval.tool}</span>
        <span className="text-[11px] text-slate-500 shrink-0">{formatDate(approval.ts)}</span>
      </div>
      <pre className="mt-2 text-[11px] text-slate-300 bg-slate-950/60 rounded-lg p-2 overflow-x-auto">
        {JSON.stringify(approval.args, null, 2)}
      </pre>
      {approval.agent_reasoning && (
        <p className="mt-2 text-xs text-slate-400 italic leading-relaxed">
          &ldquo;{approval.agent_reasoning}&rdquo;
        </p>
      )}
      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}

      {decision === 'approved' ? (
        <div className="mt-3 border-l-2 border-emerald-400/50 pl-3">
          <Badge tone="emerald">Approved &amp; executed</Badge>
          {result && (
            <pre className="mt-2 text-[11px] text-emerald-300 bg-slate-950/60 rounded-lg p-2 overflow-x-auto">
              {JSON.stringify(result, null, 2)}
            </pre>
          )}
        </div>
      ) : decision === 'rejected' ? (
        <div className="mt-3">
          <Badge tone="rose">Rejected</Badge>
        </div>
      ) : (
        <div className="mt-3 flex gap-2">
          <button
            onClick={approve}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg bg-emerald-500/90 hover:bg-emerald-500 disabled:opacity-50 text-slate-950 text-xs font-semibold flex items-center gap-1.5"
          >
            {busy && <Spinner className="border-slate-950/40 border-t-slate-950" />}
            Approve
          </button>
          <button
            onClick={reject}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg bg-rose-500/90 hover:bg-rose-500 disabled:opacity-50 text-slate-950 text-xs font-semibold"
          >
            Reject
          </button>
        </div>
      )}
    </div>
  )
}

export default function ActionCenter({ refresh, bumpRefresh }) {
  const [message, setMessage] = useState('')
  const [running, setRunning] = useState(false)
  const [agentResult, setAgentResult] = useState(null)
  const [agentError, setAgentError] = useState(null)

  const [approvals, setApprovals] = useState([])
  const [approvalsLoading, setApprovalsLoading] = useState(true)

  const [campaigns, setCampaigns] = useState([])
  const [campaignsLoading, setCampaignsLoading] = useState(true)

  const loadApprovals = () => {
    setApprovalsLoading(true)
    get('/api/approvals?status=pending')
      .then((r) => setApprovals(r.approvals || []))
      .catch(() => setApprovals([]))
      .finally(() => setApprovalsLoading(false))
  }

  const loadCampaigns = () => {
    setCampaignsLoading(true)
    get('/api/campaigns')
      .then((r) => setCampaigns(r.campaigns || []))
      .catch(() => setCampaigns([]))
      .finally(() => setCampaignsLoading(false))
  }

  useEffect(() => {
    loadApprovals()
    loadCampaigns()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh])

  const runAgent = () => {
    if (!message.trim() || running) return
    setRunning(true)
    setAgentError(null)
    setAgentResult(null)
    post('/api/agent/run', { message })
      .then((res) => {
        setAgentResult(res)
        loadApprovals()
        bumpRefresh?.()
      })
      .catch((e) => setAgentError(e.message))
      .finally(() => setRunning(false))
  }

  return (
    <div className="space-y-8">
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <h3 className="text-sm font-semibold tracking-tight mb-3">Ask the growth agent</h3>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="e.g. Which customers should we win back this week, and why?"
          rows={3}
          className="w-full bg-slate-950/60 border border-slate-800 rounded-lg p-3 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-400/50 resize-none"
        />
        <div className="mt-2 flex items-center gap-3">
          <button
            onClick={runAgent}
            disabled={running || !message.trim()}
            className="px-4 py-2 rounded-lg bg-sky-500/90 hover:bg-sky-500 disabled:opacity-50 text-slate-950 text-xs font-semibold flex items-center gap-2"
          >
            {running && <Spinner className="border-slate-950/40 border-t-slate-950" />}
            Run agent
          </button>
          {running && (
            <span className="text-xs text-slate-400">Agent working — watch the audit console&hellip;</span>
          )}
        </div>

        {agentError && <p className="mt-3 text-xs text-rose-400">{agentError}</p>}

        {agentResult && (
          <div className="mt-4 border-t border-slate-800 pt-4">
            <AgentText text={agentResult.text} />
            {agentResult.tool_events?.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {agentResult.tool_events.map((ev, i) => (
                  <Badge key={i} tone={VERDICT_TONE[ev.verdict] || 'slate'}>
                    {ev.tool} · {ev.verdict}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold tracking-tight text-slate-200 mb-3">
          Pending approvals {approvals.length > 0 && <span className="text-amber-400">({approvals.length})</span>}
        </h3>
        {approvalsLoading ? (
          <div className="flex items-center gap-2 text-slate-400 text-xs">
            <Spinner /> Loading approvals…
          </div>
        ) : approvals.length === 0 ? (
          <p className="text-xs text-slate-500">No pending approvals.</p>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            {approvals.map((a) => (
              <ApprovalCard key={a.id} approval={a} onDecided={loadApprovals} />
            ))}
          </div>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold tracking-tight text-slate-200 mb-3">Campaigns &amp; results</h3>
        {campaignsLoading ? (
          <div className="flex items-center gap-2 text-slate-400 text-xs">
            <Spinner /> Loading campaigns…
          </div>
        ) : campaigns.length === 0 ? (
          <p className="text-xs text-slate-500">No campaigns yet.</p>
        ) : (
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-800">
                  <th className="px-3 py-2 font-medium">Kind</th>
                  <th className="px-3 py-2 font-medium">Segment</th>
                  <th className="px-3 py-2 font-medium">Offer code</th>
                  <th className="px-3 py-2 font-medium text-right">Targeted</th>
                  <th className="px-3 py-2 font-medium text-right">Redeemed</th>
                  <th className="px-3 py-2 font-medium text-right">Revenue attributed</th>
                  <th className="px-3 py-2 font-medium text-right">Incentive cost</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c) => (
                  <tr key={c.campaign_id} className="border-b border-slate-800/60 last:border-0">
                    <td className="px-3 py-2 text-slate-300">{c.kind}</td>
                    <td className="px-3 py-2 text-slate-300 max-w-[220px] truncate">{c.segment}</td>
                    <td className="px-3 py-2 font-mono text-sky-400">{c.offer_code}</td>
                    <td className="px-3 py-2 text-right text-slate-300 tabular-nums">{c.targeted}</td>
                    <td className="px-3 py-2 text-right text-slate-300 tabular-nums">{c.redeemed}</td>
                    <td className="px-3 py-2 text-right text-emerald-400 font-semibold tabular-nums">
                      {formatINR(c.revenue_attributed_inr)}
                    </td>
                    <td className="px-3 py-2 text-right text-slate-400 tabular-nums">
                      {formatINR(c.incentive_budget_inr)}
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={c.status === 'active' ? 'sky' : 'slate'}>{c.status}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
