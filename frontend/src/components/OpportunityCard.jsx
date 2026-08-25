import { useState } from 'react'
import { post, formatINR, formatDate, ISSUE_THEMES } from '../api'
import Badge from './shared/Badge'
import Spinner from './shared/Spinner'

const VERDICT_TONE = {
  ALLOWED: 'emerald',
  NEEDS_APPROVAL: 'amber',
  BLOCKED: 'rose',
}

const VERDICT_LABEL = {
  ALLOWED: 'Allowed',
  NEEDS_APPROVAL: 'Needs your approval',
  BLOCKED: 'Blocked',
}

function relativeTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  const diffMs = Date.now() - d.getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function proposedActionText(opp) {
  const args = opp.proposed_args || {}
  const parts = []
  if (args.discount_pct != null) parts.push(`${args.discount_pct}% win-back offer`)
  if (Array.isArray(args.customer_ids)) parts.push(`${args.customer_ids.length} customers`)
  if (args.expiry_days != null) parts.push(`expires in ${args.expiry_days} days`)
  return parts.join(' · ') || opp.proposed_tool
}

function customerLookup(opp) {
  const map = {}
  for (const c of opp.evidence?.customers || []) map[c.customer_id] = c
  return map
}

function MoneyBox({ label, sub, value, accent }) {
  return (
    <div className="bg-slate-950/60 border border-slate-800 rounded-lg p-3 flex flex-col gap-1 min-w-0">
      <span className="text-[11px] text-slate-500 truncate">{label}</span>
      <span className={`text-lg font-semibold tracking-tight tabular-nums ${accent || 'text-slate-100'}`}>
        {value}
      </span>
      {sub ? <span className="text-[10px] text-slate-500 truncate">{sub}</span> : null}
    </div>
  )
}

function EvidenceList({ opp }) {
  const customers = opp.evidence?.customers || []
  return (
    <div className="mt-3 border-t border-slate-800 pt-3 space-y-3">
      {opp.evidence?.detection_rule && (
        <p className="font-mono text-[11px] text-slate-500">rule: {opp.evidence.detection_rule}</p>
      )}
      {opp.evidence?.assumption_note && (
        <p className="text-[11px] text-amber-400/90 bg-amber-400/5 border border-amber-400/20 rounded-lg p-2 leading-relaxed">
          {opp.evidence.assumption_note}
        </p>
      )}
      <ul className="space-y-2">
        {customers.map((c) => (
          <li key={c.customer_id} className="border border-slate-800 rounded-lg p-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <span className="text-xs font-semibold text-slate-100">{c.name}</span>
              <span className="text-[11px] text-slate-500">{c.zone}</span>
            </div>
            <div className="mt-1 flex items-center gap-3 text-[11px] text-slate-400">
              <span>
                LTV <span className="text-emerald-400 font-semibold">{formatINR(c.ltv_inr)}</span>
              </span>
              <span>AOV {formatINR(c.aov_inr)}</span>
              <span>Last order {formatDate(c.last_order)}</span>
            </div>
            {c.review && (
              <div className="mt-2 border-l-2 border-slate-700 pl-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-amber-400 text-[11px]">
                    {'★'.repeat(c.review.rating)}
                    {'☆'.repeat(5 - c.review.rating)}
                  </span>
                  <span className="text-[10px] text-slate-500">{formatDate(c.review.ts)}</span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed italic">&ldquo;{c.review.text}&rdquo;</p>
                {(c.review.themes || []).length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {c.review.themes.map((t) => (
                      <Badge key={t} tone={ISSUE_THEMES.includes(t) ? 'rose' : 'emerald'}>
                        {t}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function OpportunityCard({ opportunity, onDecided, compact = false }) {
  const [showEvidence, setShowEvidence] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [local, setLocal] = useState(opportunity)

  const opp = local
  const lookup = customerLookup(opp)

  const approve = () => {
    setBusy(true)
    setError(null)
    post(`/api/opportunities/${opp.id}/approve`)
      .then((res) => {
        if (res.executed) {
          setLocal((s) => ({
            ...s,
            status: 'executed',
            _executeResult: res.result,
          }))
        } else if (res.verdict) {
          setLocal((s) => ({ ...s, status: 'failed', error: `Blocked at execution: ${res.rule}` }))
        } else {
          setLocal((s) => ({ ...s, status: 'failed', error: res.error }))
        }
        onDecided?.()
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false))
  }

  const reject = () => {
    setBusy(true)
    setError(null)
    post(`/api/opportunities/${opp.id}/reject`)
      .then(() => {
        setLocal((s) => ({ ...s, status: 'rejected' }))
        onDecided?.()
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false))
  }

  const execResult = opp._executeResult
  const outcome = opp.outcome

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-sky-400/10 text-sky-400 border border-sky-400/30 text-[10px] font-semibold uppercase tracking-wide">
              <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
              Agent found
            </span>
            <span className="text-[11px] text-slate-500">{relativeTime(opp.ts)}</span>
          </div>
          <h3 className="mt-1.5 text-base font-semibold tracking-tight text-slate-100">{opp.title}</h3>
        </div>
        <Badge tone={VERDICT_TONE[opp.policy_verdict] || 'slate'} className="shrink-0">
          {VERDICT_LABEL[opp.policy_verdict] || opp.policy_verdict}
        </Badge>
      </div>

      <p className={`mt-2 text-slate-300 leading-relaxed ${compact ? 'text-xs line-clamp-3' : 'text-xs'}`}>
        {opp.rationale}
      </p>

      <div className="mt-3 grid grid-cols-3 gap-3">
        <MoneyBox label="Revenue at risk" value={formatINR(opp.revenue_at_risk_inr)} accent="text-slate-100" />
        <MoneyBox
          label="Expected recovered revenue"
          sub="if 30% redeem — projection"
          value={formatINR(opp.expected_revenue_inr)}
          accent="text-emerald-400"
        />
        <MoneyBox
          label="Maximum exposure"
          sub="worst case, if everyone redeems"
          value={formatINR(opp.max_exposure_inr)}
          accent="text-amber-400"
        />
      </div>

      <div className="mt-3 bg-slate-950/60 border border-slate-800 rounded-lg px-3 py-2">
        <span className="text-[11px] text-slate-500 mr-2">Proposed action</span>
        <span className="font-mono text-xs text-sky-400">{proposedActionText(opp)}</span>
      </div>

      {opp.excluded_note && (
        <p className="mt-2 text-[11px] text-slate-500">
          <span className="mr-1">🛡</span>
          {opp.excluded_note}
        </p>
      )}

      {!compact && (
        <div className="mt-3">
          <button
            onClick={() => setShowEvidence((s) => !s)}
            className="text-[11px] text-sky-400 hover:text-sky-300 font-medium"
          >
            {showEvidence ? 'Hide evidence' : 'Show evidence'}
          </button>
          {showEvidence && <EvidenceList opp={opp} />}
        </div>
      )}

      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}

      {opp.status === 'open' && (
        <div className="mt-3 flex items-center gap-2">
          <button
            onClick={approve}
            disabled={busy}
            className="px-4 py-2 rounded-lg bg-emerald-500/90 hover:bg-emerald-500 disabled:opacity-50 text-slate-950 text-xs font-semibold flex items-center gap-2"
          >
            {busy && <Spinner className="border-slate-950/40 border-t-slate-950" />}
            Approve &amp; execute
          </button>
          <button
            onClick={reject}
            disabled={busy}
            className="px-3 py-2 rounded-lg border border-rose-400/40 text-rose-400 hover:bg-rose-400/10 disabled:opacity-50 text-xs font-semibold"
          >
            Reject
          </button>
          {busy && (
            <span className="text-[11px] text-slate-400">Creating Razorpay payment links&hellip;</span>
          )}
        </div>
      )}

      {opp.status === 'executed' && (
        <div className="mt-3 border-t border-slate-800 pt-3">
          <div className="flex items-center gap-2">
            <span className="text-emerald-400">&#10003;</span>
            <span className="text-xs font-semibold text-emerald-400">Executed</span>
            {execResult?.offer_code && (
              <span className="font-mono text-xs text-slate-300">{execResult.offer_code}</span>
            )}
          </div>
          {execResult?.links?.length > 0 && (
            <ul className="mt-2 space-y-1">
              {execResult.links.map((l, i) => {
                const cust = lookup[l.customer_id]
                return (
                  <li key={i} className="flex items-center justify-between text-xs gap-2">
                    <span className="text-slate-300 truncate">{cust?.name || `Customer #${l.customer_id}`}</span>
                    <span className="text-slate-400 tabular-nums">{formatINR(l.amount_inr)}</span>
                    {l.short_url ? (
                      <a
                        href={l.short_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-sky-400 hover:text-sky-300 truncate max-w-[160px]"
                      >
                        {l.short_url}
                      </a>
                    ) : (
                      <span className="text-slate-500">Razorpay order</span>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
          {outcome && (
            <div className="mt-3 bg-slate-950/60 border border-slate-800 rounded-lg px-3 py-2 text-[11px] text-slate-300">
              {outcome.redeemed > 0 ? (
                <>
                  Redeemed {outcome.redeemed}/{outcome.targeted} · Revenue attributed{' '}
                  <span className="text-emerald-400 font-semibold">{formatINR(outcome.revenue_inr)}</span> ·
                  Incentive {formatINR(outcome.incentive_inr)} · Net{' '}
                  <span
                    className={
                      outcome.revenue_inr - outcome.incentive_inr >= 0
                        ? 'text-emerald-400 font-semibold'
                        : 'text-rose-400 font-semibold'
                    }
                  >
                    {formatINR(outcome.revenue_inr - outcome.incentive_inr)}
                  </span>
                </>
              ) : (
                'Awaiting payment — revenue will attribute here automatically when a customer pays.'
              )}
            </div>
          )}
        </div>
      )}

      {opp.status === 'rejected' && (
        <div className="mt-3 border-t border-slate-800 pt-3">
          <Badge tone="slate">Rejected by merchant</Badge>
        </div>
      )}

      {opp.status === 'failed' && (
        <div className="mt-3 border-t border-slate-800 pt-3 bg-rose-400/5 border-rose-400/20 rounded-lg p-3">
          <p className="text-xs text-rose-400 font-medium">{opp.error || 'Execution failed'}</p>
          <p className="mt-1 text-[11px] text-slate-500">
            Recorded in the audit trail; safe to retry (idempotent).
          </p>
        </div>
      )}
    </div>
  )
}
