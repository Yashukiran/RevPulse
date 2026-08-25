import { useEffect, useMemo, useRef, useState } from 'react'
import { get, post, formatINR, formatDate, formatTime } from '../api'
import Badge from './shared/Badge'
import Spinner from './shared/Spinner'
import OpportunityCard from './OpportunityCard'

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

function MarkdownTable({ rows, keyPrefix }) {
  const [header, ...body] = rows
  const cells = (row) =>
    row
      .trim()
      .replace(/^\||\|$/g, '')
      .split('|')
      .map((c) => c.trim())
  return (
    <div className="my-2 overflow-x-auto">
      <table className="w-full text-xs border border-slate-800 rounded-lg overflow-hidden">
        <thead className="bg-slate-950/60">
          <tr>
            {cells(header).map((c, i) => (
              <th
                key={`${keyPrefix}-h-${i}`}
                className="text-left font-semibold text-slate-300 px-3 py-1.5 border-b border-slate-800"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, r) => (
            <tr key={`${keyPrefix}-r-${r}`} className="border-b border-slate-800/60 last:border-0">
              {cells(row).map((c, i) => (
                <td key={`${keyPrefix}-c-${r}-${i}`} className="px-3 py-1.5 text-slate-300">
                  {renderInline(c, `${keyPrefix}-${r}-${i}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AgentText({ text }) {
  if (!text) return null
  const rawLines = text.split('\n')

  // Group consecutive markdown table rows so they render as a real table.
  const blocks = []
  for (let i = 0; i < rawLines.length; i++) {
    const line = rawLines[i]
    if (line.trim().startsWith('|') && line.includes('|', 1)) {
      const rows = []
      while (i < rawLines.length && rawLines[i].trim().startsWith('|')) {
        const row = rawLines[i]
        // skip the |---|---| separator row
        if (!/^\|[\s:-]+\|?$/.test(row.trim().replace(/\|/g, '|'))) {
          if (!/^[|\s:-]+$/.test(row.trim())) rows.push(row)
        }
        i++
      }
      i--
      if (rows.length) blocks.push({ type: 'table', rows })
      continue
    }
    blocks.push({ type: 'line', line })
  }

  return (
    <div className="space-y-1">
      {blocks.map((block, i) => {
        if (block.type === 'table') {
          return <MarkdownTable key={`t-${i}`} rows={block.rows} keyPrefix={`t-${i}`} />
        }
        const line = block.line
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

export default function ActionCenter({ refresh, agentRun, onAgentMessage, onRunAgent }) {
  const { message, running, result: agentResult, error: agentError, events } = agentRun

  const [approvals, setApprovals] = useState([])
  const [approvalsLoading, setApprovalsLoading] = useState(true)
  const approvalsFirstLoad = useRef(true)

  const [campaigns, setCampaigns] = useState([])
  const [campaignsLoading, setCampaignsLoading] = useState(true)
  const campaignsFirstLoad = useRef(true)

  const [opportunities, setOpportunities] = useState([])
  const [opportunitiesLoading, setOpportunitiesLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [scanMessage, setScanMessage] = useState(null)
  const opportunitiesFirstLoad = useRef(true)

  const loadOpportunities = () => {
    if (opportunitiesFirstLoad.current) setOpportunitiesLoading(true)
    get('/api/opportunities')
      .then((r) => {
        const rows = r.opportunities || []
        rows.sort((a, b) => {
          if ((a.status === 'open') !== (b.status === 'open')) return a.status === 'open' ? -1 : 1
          return new Date(b.ts) - new Date(a.ts)
        })
        setOpportunities(rows)
      })
      .catch(() => setOpportunities([]))
      .finally(() => {
        setOpportunitiesLoading(false)
        opportunitiesFirstLoad.current = false
      })
  }

  const scanNow = () => {
    setScanning(true)
    setScanMessage(null)
    post('/api/opportunities/scan')
      .then((res) => {
        loadOpportunities()
        // A scan that finds nothing still reports why, so the button never
        // looks broken when the guardrails are simply holding.
        setScanMessage(
          res.found > 0
            ? { tone: 'emerald', text: `Found ${res.found} new opportunity.` }
            : { tone: 'slate', text: res.reason || 'Scan complete — no new opportunities.' }
        )
      })
      .catch((e) => setScanMessage({ tone: 'rose', text: `Scan failed: ${e.message}` }))
      .finally(() => setScanning(false))
  }

  const loadApprovals = () => {
    // Only the first fetch shows a loader; later calls (a background refresh
    // bump, or right after an approve/reject) swap the list in quietly.
    if (approvalsFirstLoad.current) setApprovalsLoading(true)
    get('/api/approvals?status=pending')
      .then((r) => setApprovals(r.approvals || []))
      .catch(() => setApprovals([]))
      .finally(() => {
        setApprovalsLoading(false)
        approvalsFirstLoad.current = false
      })
  }

  const loadCampaigns = () => {
    if (campaignsFirstLoad.current) setCampaignsLoading(true)
    get('/api/campaigns')
      .then((r) => setCampaigns(r.campaigns || []))
      .catch(() => setCampaigns([]))
      .finally(() => {
        setCampaignsLoading(false)
        campaignsFirstLoad.current = false
      })
  }

  useEffect(() => {
    loadApprovals()
    loadCampaigns()
    loadOpportunities()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh])

  const runAgent = () => onRunAgent(message)

  const impact = useMemo(() => {
    const targeted = campaigns.reduce((n, c) => n + (c.targeted || 0), 0)
    const redeemed = campaigns.reduce((n, c) => n + (c.redeemed || 0), 0)
    const revenue = campaigns.reduce((n, c) => n + (c.revenue_attributed_inr || 0), 0)
    // Cost = incentive actually given away on redemptions, not budget reserved.
    const cost = campaigns.reduce((n, c) => n + (c.incentive_spent_inr || 0), 0)
    const reserved = campaigns.reduce((n, c) => n + (c.incentive_budget_inr || 0), 0)
    return {
      targeted,
      redeemed,
      revenue,
      cost,
      reserved,
      net: revenue - cost,
      redemptionRate: targeted ? Math.round((redeemed / targeted) * 100) : null,
    }
  }, [campaigns])

  return (
    <div className="space-y-8">
      <section>
        <div className="flex items-center justify-between gap-3 mb-3">
          <h3 className="text-sm font-semibold tracking-tight text-slate-200">
            Agent opportunities{' '}
            {opportunities.length > 0 && (
              <span className="text-sky-400">({opportunities.length})</span>
            )}
          </h3>
          <button
            onClick={scanNow}
            disabled={scanning}
            className="px-3 py-1.5 rounded-lg bg-sky-500/90 hover:bg-sky-500 disabled:opacity-50 text-slate-950 text-xs font-semibold flex items-center gap-1.5"
          >
            {scanning && <Spinner className="border-slate-950/40 border-t-slate-950" />}
            Scan now
          </button>
        </div>
        {scanMessage && (
          <p
            className={`mb-3 text-xs ${
              scanMessage.tone === 'emerald'
                ? 'text-emerald-400'
                : scanMessage.tone === 'rose'
                  ? 'text-rose-400'
                  : 'text-slate-400'
            }`}
          >
            {scanMessage.text}
          </p>
        )}
        {opportunitiesLoading ? (
          <div className="flex items-center gap-2 text-slate-400 text-xs">
            <Spinner /> Loading opportunities…
          </div>
        ) : opportunities.length === 0 ? (
          <p className="text-xs text-slate-500">
            No opportunities right now. The agent scans on startup and whenever new customer
            feedback signals churn.
          </p>
        ) : (
          <div className="space-y-4">
            {opportunities.map((o) => (
              <OpportunityCard key={o.id} opportunity={o} onDecided={loadOpportunities} />
            ))}
          </div>
        )}
      </section>

      <section className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <h3 className="text-sm font-semibold tracking-tight">Ask the agent a question</h3>
        <p className="mt-0.5 text-[11px] text-slate-500">
          The agent works proactively above — this is for ad-hoc questions.
        </p>
        <textarea
          value={message}
          onChange={(e) => onAgentMessage(e.target.value)}
          placeholder="e.g. Which customers should we win back this week, and why?"
          rows={3}
          className="mt-3 w-full bg-slate-950/60 border border-slate-800 rounded-lg p-3 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-400/50 resize-none"
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
            <span className="text-xs text-slate-400">
              Agent working&hellip; its answer appears here when done (usually 10–60s)
            </span>
          )}
        </div>

        {running && (
          <div className="mt-4 border-t border-slate-800 pt-3">
            <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-2">
              Live agent moves
            </p>
            {events.length === 0 ? (
              <p className="text-xs text-slate-500">Thinking&hellip;</p>
            ) : (
              <div className="space-y-1 font-mono text-[11px]">
                {events.map((e) => (
                  <div key={e.id} className="flex items-center gap-2">
                    <span className="text-slate-500">{formatTime(e.ts)}</span>
                    <span className="text-slate-300">{e.tool}</span>
                    <Badge tone={VERDICT_TONE[e.policy_verdict] || 'slate'}>
                      {e.policy_verdict}
                    </Badge>
                    {e.policy_rule_hit && (
                      <span className="text-slate-500 truncate">{e.policy_rule_hit}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {agentError && <p className="mt-3 text-xs text-rose-400">{agentError}</p>}

        {agentResult && (
          <div className="mt-4 border-t border-slate-800 pt-4">
            <AgentText
              text={
                agentResult.text?.trim() ||
                'The agent finished without a text summary — its tool calls are below, and the full chain is in the Audit Console.'
              }
            />
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

        <div className="grid grid-cols-4 gap-4 mb-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Customers targeted</p>
            <p className="mt-1 text-xl font-semibold text-slate-100">{impact.targeted}</p>
            <p className="text-[11px] text-slate-500">{impact.redeemed} redeemed</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Revenue attributed</p>
            <p className="mt-1 text-xl font-semibold text-emerald-400">
              {formatINR(impact.revenue)}
            </p>
            <p className="text-[11px] text-slate-500">via unique campaign links</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Incentive cost</p>
            <p className="mt-1 text-xl font-semibold text-amber-400">{formatINR(impact.cost)}</p>
            <p className="text-[11px] text-slate-500">
              paid on redemptions · {formatINR(impact.reserved)} reserved
            </p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Net revenue added</p>
            <p
              className={`mt-1 text-xl font-semibold ${
                impact.net >= 0 ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {formatINR(impact.net)}
            </p>
            <p className="text-[11px] text-slate-500">
              {impact.redemptionRate == null
                ? 'no redemptions yet'
                : `${impact.redemptionRate}% redemption rate`}
            </p>
          </div>
        </div>
        <p className="text-[11px] text-slate-500 mb-3">
          Exact attribution: each campaign issues one unique Razorpay link and offer code per
          customer, so every rupee above came through a specific campaign — measured, not estimated.
        </p>

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
