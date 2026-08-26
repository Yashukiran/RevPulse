import { useEffect, useRef, useState } from 'react'
import { get, post, formatDate } from '../api'
import Badge from './shared/Badge'
import Spinner from './shared/Spinner'

const CONFIDENCE_TONE = { High: 'emerald', Medium: 'amber', Low: 'slate' }

function Stat({ label, value, sub, accent = 'text-slate-100' }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-0.5 text-2xl font-semibold tabular-nums ${accent}`}>{value}</p>
      {sub && <p className="text-[11px] text-slate-500">{sub}</p>}
    </div>
  )
}

export default function DemandPlanning({ refresh }) {
  const [data, setData] = useState(null)
  const [reason, setReason] = useState(null)
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [creating, setCreating] = useState(false)
  const [showWhy, setShowWhy] = useState(false)
  const firstLoad = useRef(true)

  const load = () => {
    if (firstLoad.current) setLoading(true)
    get('/api/demand/forecast')
      .then((r) => {
        setData(r.forecast)
        setReason(r.reason)
        setPlans(r.plans || [])
      })
      .catch((e) => setError(e.message))
      .finally(() => {
        setLoading(false)
        firstLoad.current = false
      })
  }

  useEffect(load, [refresh]) // eslint-disable-line react-hooks/exhaustive-deps

  const createPlan = () => {
    setCreating(true)
    post('/api/demand/plan')
      .then(() => load())
      .catch((e) => setError(e.message))
      .finally(() => setCreating(false))
  }

  if (loading) return <div className="text-slate-400 text-sm">Reading your order history…</div>
  if (error) return <div className="text-rose-400 text-sm">Failed to load: {error}</div>
  if (!data) return <p className="text-slate-400 text-xs">{reason}</p>

  const { peak, drivers, evidence, service_pressure: pressure, recommendation, checklist, accuracy, method } = data
  const extra = peak.expected_orders - peak.baseline_orders
  const planned = plans.find((p) => p.target_date === peak.target_date)

  return (
    <div className="space-y-6 max-w-5xl">
      {/* A. what is going to happen */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
          <span className="text-[11px] uppercase tracking-wide text-sky-400 font-semibold">
            Upcoming demand spike
          </span>
          <Badge tone={CONFIDENCE_TONE[peak.confidence] || 'slate'}>
            {peak.confidence} confidence
          </Badge>
        </div>

        <h3 className="text-2xl font-semibold tracking-tight text-slate-100">
          {peak.day_name} {peak.window_label}
        </h3>
        <p className="mt-0.5 text-xs text-slate-500">{formatDate(peak.target_date)}</p>

        <div className="mt-4 grid grid-cols-3 gap-4 border-t border-slate-800 pt-4">
          <Stat
            label="Expected orders"
            value={peak.expected_orders}
            sub={`about ${extra} more than usual`}
            accent="text-emerald-400"
          />
          <Stat label="A normal day" value={peak.baseline_orders} sub="same window, any day" />
          <Stat
            label="Busier by"
            value={`+${peak.uplift_pct}%`}
            sub={`based on ${peak.observations} past ${peak.day_name}s`}
            accent="text-amber-400"
          />
        </div>

        <p className="mt-4 text-sm text-slate-300 leading-relaxed">{recommendation}</p>
      </section>

      {/* B. what will drive it */}
      {drivers.length > 0 && (
        <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="text-sm font-semibold tracking-tight text-slate-200 mb-3">
            What will drive the demand
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-800">
                  <th className="pb-2 font-medium">Dish</th>
                  <th className="pb-2 font-medium text-right">Normal day</th>
                  <th className="pb-2 font-medium text-right">Expected</th>
                  <th className="pb-2 font-medium text-right">Change</th>
                </tr>
              </thead>
              <tbody>
                {drivers.map((d) => (
                  <tr key={d.item} className="border-b border-slate-800/60 last:border-0">
                    <td className="py-2 text-slate-200">{d.item}</td>
                    <td className="py-2 text-right text-slate-400 tabular-nums">{d.normal}</td>
                    <td className="py-2 text-right text-slate-100 tabular-nums font-semibold">
                      {d.expected}
                    </td>
                    <td className="py-2 text-right tabular-nums text-emerald-400">
                      +{d.change_pct}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* C. why the agent believes this */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold tracking-tight text-slate-200">
            Why the agent expects this
          </h3>
          <button
            onClick={() => setShowWhy((v) => !v)}
            className="text-[11px] text-sky-400 hover:text-sky-300 font-semibold"
          >
            {showWhy ? 'Hide method' : 'How is this calculated?'}
          </button>
        </div>
        <ul className="mt-3 space-y-1.5">
          {evidence.map((e, i) => (
            <li key={i} className="text-xs text-slate-300 flex gap-2">
              <span className="text-slate-600">•</span>
              <span>{e}</span>
            </li>
          ))}
        </ul>

        {showWhy && (
          <div className="mt-3 border-t border-slate-800 pt-3 space-y-2">
            <p className="text-[11px] text-slate-400 leading-relaxed">{method}</p>
            {accuracy && (
              <div>
                <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">
                  Forecast checked against what actually happened
                </p>
                <table className="text-[11px] w-full max-w-md">
                  <tbody>
                    {accuracy.rounds.map((r) => (
                      <tr key={r.date}>
                        <td className="py-0.5 text-slate-400">{formatDate(r.date)}</td>
                        <td className="py-0.5 text-slate-400 tabular-nums">
                          forecast {r.forecast}
                        </td>
                        <td className="py-0.5 text-slate-200 tabular-nums">actual {r.actual}</td>
                        <td className="py-0.5 text-right text-emerald-400 tabular-nums">
                          {r.accuracy_pct}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-1.5 text-xs text-slate-300">
                  Average accuracy on the last {accuracy.rounds.length} comparable windows:{' '}
                  <span className="text-emerald-400 font-semibold">
                    {accuracy.mean_accuracy_pct}%
                  </span>
                </p>
              </div>
            )}
          </div>
        )}
      </section>

      {/* why it matters — association, never causation */}
      {pressure && (
        <section className="bg-slate-900 border border-amber-400/20 rounded-xl p-5">
          <h3 className="text-sm font-semibold tracking-tight text-slate-200">Why this matters</h3>
          <p className="mt-2 text-xs text-slate-300 leading-relaxed">
            In this window, <span className="text-amber-400 font-semibold">
              {pressure.relative_pct}% more
            </span>{' '}
            of your reviews mention slow service than at other times —{' '}
            {pressure.slot_rate}% of {pressure.slot_n} reviews here, against {pressure.other_rate}%
            of {pressure.other_n} elsewhere.
          </p>
          <p className="mt-1.5 text-[11px] text-slate-500 leading-relaxed">
            Being busy and being slow are associated here; this does not prove one causes the
            other. Preparing before the rush may help reduce delays and protect the customer
            experience.
          </p>
        </section>
      )}

      {/* D. recommended preparation */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 className="text-sm font-semibold tracking-tight text-slate-200">
          Prepare for about {extra} additional orders
        </h3>
        <ul className="mt-3 space-y-1.5">
          {checklist.map((c, i) => (
            <li key={i} className="text-xs text-slate-300 flex gap-2">
              <span className="text-emerald-400">✓</span>
              <span>{c}</span>
            </li>
          ))}
        </ul>

        <div className="mt-4 flex items-center gap-3">
          {planned ? (
            <span className="flex items-center gap-2 text-xs text-emerald-400 font-semibold">
              ✓ Preparation plan created
              <span className="text-slate-500 font-normal">
                {formatDate(planned.created_ts)}
              </span>
            </span>
          ) : (
            <button
              onClick={createPlan}
              disabled={creating}
              className="px-4 py-2 rounded-lg bg-emerald-500/90 hover:bg-emerald-500 disabled:opacity-50 text-slate-950 text-xs font-semibold flex items-center gap-2"
            >
              {creating && <Spinner className="border-slate-950/40 border-t-slate-950" />}
              Create preparation plan
            </button>
          )}
          <span className="text-[11px] text-slate-500">
            Operational only — no offer, no discount, no money spent.
          </span>
        </div>
      </section>

      {/* outcome, once a planned window has passed */}
      {plans.length > 0 && (
        <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="text-sm font-semibold tracking-tight text-slate-200 mb-3">
            Past preparation plans
          </h3>
          <div className="space-y-2">
            {plans.map((p) => (
              <div
                key={p.id}
                className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs border border-slate-800 rounded-lg px-3 py-2"
              >
                <span className="text-slate-200 font-medium">
                  {p.day_name} {p.window_label}
                </span>
                <span className="text-slate-500">{formatDate(p.target_date)}</span>
                <span className="text-slate-400 tabular-nums">
                  forecast {p.expected_orders}
                </span>
                {p.outcome?.measured ? (
                  <>
                    <span className="text-slate-100 tabular-nums">
                      actual {p.outcome.actual}
                    </span>
                    <span className="text-emerald-400 tabular-nums font-semibold">
                      {p.outcome.accuracy_pct}% accurate
                    </span>
                  </>
                ) : (
                  <span className="text-slate-500">{p.outcome?.note || 'awaiting the window'}</span>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
