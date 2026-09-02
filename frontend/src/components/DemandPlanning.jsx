import { useEffect, useRef, useState } from 'react'
import { get, post, formatDate, formatINR } from '../api'
import Badge from './shared/Badge'
import Spinner from './shared/Spinner'

const CONFIDENCE_TONE = { High: 'emerald', Medium: 'amber', Low: 'slate' }

export default function DemandPlanning({ refresh }) {
  const [data, setData] = useState(null)
  const [reason, setReason] = useState(null)
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [showMethod, setShowMethod] = useState(false)
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

  const savePlan = () => {
    setSaving(true)
    post('/api/demand/plan')
      .then(() => load())
      .catch((e) => setError(e.message))
      .finally(() => setSaving(false))
  }

  if (loading) return <div className="text-slate-400 text-sm">Reading your order history…</div>
  if (error) return <div className="text-rose-400 text-sm">Could not load: {error}</div>
  if (!data) return <p className="text-slate-400 text-xs">{reason}</p>

  const {
    peak, drivers, extra_orders: extra, items_per_order: perOrder,
    revenue_opportunity: money, service_pressure: pressure,
    evidence, recommendation, checklist, accuracy, method,
  } = data
  const ready = plans.find((p) => p.target_date === peak.target_date)

  return (
    <div className="space-y-5 max-w-4xl">
      {/* A — what is going to happen */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
          <span className="text-[11px] uppercase tracking-wide text-sky-400 font-semibold">
            Upcoming busy period
          </span>
          <Badge tone={CONFIDENCE_TONE[peak.confidence] || 'slate'}>
            {peak.confidence === 'High' ? 'Very likely' : peak.confidence === 'Medium'
              ? 'Likely' : 'Possible'}
          </Badge>
          {peak.holiday && <Badge tone="amber">{peak.holiday}</Badge>}
        </div>

        <h3 className="mt-2 text-2xl font-semibold tracking-tight text-slate-100">
          {peak.day_name} {peak.window_label}
        </h3>
        <p className="text-xs text-slate-500">
          {formatDate(peak.target_date)}
          {peak.days_ahead === 1 ? ' · tomorrow' : ` · in ${peak.days_ahead} days`}
        </p>

        {peak.upcoming?.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-[11px] uppercase tracking-wide text-slate-500">After that</span>
            {peak.upcoming.map((u) => (
              <span
                key={u.target_date}
                className="rounded border border-slate-800 bg-slate-900/60 px-2 py-1 text-xs text-slate-400"
              >
                <span className="text-slate-300">{u.day_name}</span> {u.window_label}
                <span className="ml-1.5 tabular-nums text-emerald-400/80">+{u.extra_orders}</span>
                {u.holiday && <span className="ml-1.5 text-amber-400">{u.holiday}</span>}
              </span>
            ))}
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-end gap-x-10 gap-y-4 border-t border-slate-800 pt-4">
          <div>
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Expected orders</p>
            <p className="text-4xl font-semibold text-emerald-400 tabular-nums">
              {peak.expected_orders}
            </p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wide text-slate-500">
              Typical {peak.window_label}
            </p>
            <p className="text-2xl font-semibold text-slate-300 tabular-nums">
              {peak.baseline_orders}
            </p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wide text-slate-500">That is</p>
            <p className="text-2xl font-semibold text-amber-400 tabular-nums">
              +{extra} orders
            </p>
            <p className="text-[11px] text-slate-500">+{peak.uplift_pct}% busier</p>
          </div>
        </div>

        <p className="mt-4 text-sm text-slate-300 leading-relaxed">{recommendation}</p>
      </section>

      {/* B — what will sell more */}
      {drivers.length > 0 && (
        <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="text-sm font-semibold tracking-tight text-slate-200">
            What will sell more
          </h3>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-800">
                  <th className="pb-2 font-medium">Food</th>
                  <th className="pb-2 font-medium text-right">Typical</th>
                  <th className="pb-2 font-medium text-right">Expected</th>
                  <th className="pb-2 font-medium text-right">Extra</th>
                </tr>
              </thead>
              <tbody>
                {drivers.map((d) => (
                  <tr key={d.item} className="border-b border-slate-800/60 last:border-0">
                    <td className="py-2 text-slate-200">{d.item}</td>
                    <td className="py-2 text-right text-slate-400 tabular-nums">{d.typical}</td>
                    <td className="py-2 text-right text-slate-100 tabular-nums font-semibold">
                      {d.expected}
                    </td>
                    <td className="py-2 text-right tabular-nums text-emerald-400 font-semibold">
                      +{d.extra}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-slate-500">
            These are plates, not orders — customers order about {perOrder} items each, so{' '}
            {peak.expected_orders} orders means considerably more dishes than that.
          </p>
        </section>
      )}

      {/* C — why we expect this */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold tracking-tight text-slate-200">
            Why we expect this
          </h3>
          <button
            onClick={() => setShowMethod((v) => !v)}
            className="text-[11px] text-sky-400 hover:text-sky-300 font-semibold"
          >
            {showMethod ? 'Hide' : 'How is this calculated?'}
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

        {showMethod && (
          <div className="mt-3 border-t border-slate-800 pt-3 space-y-2">
            <p className="text-[11px] text-slate-400 leading-relaxed">{method}</p>
            {accuracy && (
              <>
                <table className="text-[11px] w-full max-w-sm">
                  <tbody>
                    {accuracy.rounds.map((r) => (
                      <tr key={r.date}>
                        <td className="py-0.5 text-slate-400">{formatDate(r.date)}</td>
                        <td className="py-0.5 text-slate-400 tabular-nums">we said {r.forecast}</td>
                        <td className="py-0.5 text-slate-200 tabular-nums">
                          you got {r.actual}
                        </td>
                        <td className="py-0.5 text-right text-emerald-400 tabular-nums">
                          {r.accuracy_pct}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-xs text-slate-300">
                  On the last {accuracy.rounds.length} {peak.day_name}s our forecast was{' '}
                  <span className="text-emerald-400 font-semibold">
                    {accuracy.mean_accuracy_pct}%
                  </span>{' '}
                  accurate on average.
                </p>
              </>
            )}
          </div>
        )}
      </section>

      {/* D — why this matters */}
      {pressure && (
        <section className="bg-slate-900 border border-amber-400/20 rounded-xl p-5">
          <h3 className="text-sm font-semibold tracking-tight text-slate-200">Why this matters</h3>
          <p className="mt-2 text-xs text-slate-300">
            Your customers complain about slow service far more often during this busy period.
          </p>
          <div className="mt-3 flex flex-wrap items-end gap-x-8 gap-y-3">
            <div>
              <p className="text-xl font-semibold text-amber-400 tabular-nums">
                {pressure.slot_rate}%
              </p>
              <p className="text-[11px] text-slate-500">
                of reviews during this time mention slow service
              </p>
            </div>
            <div>
              <p className="text-xl font-semibold text-slate-300 tabular-nums">
                {pressure.other_rate}%
              </p>
              <p className="text-[11px] text-slate-500">at other times</p>
            </div>
            <div>
              <p className="text-xl font-semibold text-rose-400 tabular-nums">
                +{pressure.point_difference}
              </p>
              <p className="text-[11px] text-slate-500">percentage points higher</p>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-slate-500 leading-relaxed">
            This is a pattern in your data. It does not prove that being busy causes slow
            service — but being ready before the rush may help you serve people faster.
          </p>
        </section>
      )}

      {/* E — revenue opportunity */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 className="text-sm font-semibold tracking-tight text-slate-200">
          Sales opportunity
        </h3>
        <div className="mt-3 flex flex-wrap items-end gap-x-8 gap-y-3">
          <div>
            <p className="text-2xl font-semibold text-slate-100 tabular-nums">~{extra}</p>
            <p className="text-[11px] text-slate-500">extra orders expected</p>
          </div>
          <div>
            <p className="text-2xl font-semibold text-slate-300 tabular-nums">
              {formatINR(money.avg_order_value_inr)}
            </p>
            <p className="text-[11px] text-slate-500">average order in this window</p>
          </div>
          <div>
            <p className="text-2xl font-semibold text-emerald-400 tabular-nums">
              ~{formatINR(money.potential_inr)}
            </p>
            <p className="text-[11px] text-slate-500">could be on the table</p>
          </div>
        </div>
        <p className="mt-3 text-[11px] text-slate-500 leading-relaxed">
          These are customers you may be able to serve if you are ready for the rush. It is what
          the demand is worth, not money earned — actual sales only count once the orders are paid.
        </p>
      </section>

      {/* F — what to prepare */}
      <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 className="text-sm font-semibold tracking-tight text-slate-200">
          Get ready for the rush
        </h3>
        <p className="mt-1 text-xs text-slate-400">Expected extra orders: about {extra}</p>
        <ul className="mt-3 space-y-1.5">
          {checklist.map((c, i) => (
            <li key={i} className="text-xs text-slate-300 flex gap-2">
              <span className="text-emerald-400">✓</span>
              <span>{c}</span>
            </li>
          ))}
        </ul>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          {ready ? (
            <span className="flex items-center gap-2 text-xs text-emerald-400 font-semibold">
              ✓ Preparation plan ready
              <span className="text-slate-500 font-normal">
                saved {formatDate(ready.created_ts)}
              </span>
            </span>
          ) : (
            <button
              onClick={savePlan}
              disabled={saving}
              className="px-4 py-2 rounded-lg bg-emerald-500/90 hover:bg-emerald-500 disabled:opacity-50 text-slate-950 text-xs font-semibold flex items-center gap-2"
            >
              {saving && <Spinner className="border-slate-950/40 border-t-slate-950" />}
              Save preparation plan
            </button>
          )}
          <span className="text-[11px] text-slate-500">
            This is a recommendation. Nothing is ordered, booked or charged — you decide.
          </span>
        </div>
      </section>

      {/* G — how past forecasts turned out */}
      {plans.length > 0 && (
        <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="text-sm font-semibold tracking-tight text-slate-200 mb-3">
            How past forecasts turned out
          </h3>
          <div className="space-y-2">
            {plans.map((p) => (
              <div
                key={p.id}
                className="border border-slate-800 rounded-lg px-3 py-2 text-xs flex flex-wrap items-center gap-x-6 gap-y-1"
              >
                <span className="text-slate-200 font-medium">
                  {p.day_name} {p.window_label}
                </span>
                <span className="text-slate-500">{formatDate(p.target_date)}</span>
                <span className="text-slate-400 tabular-nums">
                  we said {p.expected_orders} orders
                </span>
                {p.outcome?.measured ? (
                  <>
                    <span className="text-slate-100 tabular-nums">
                      you got {p.outcome.actual}
                    </span>
                    <span className="text-emerald-400 tabular-nums font-semibold">
                      {p.outcome.accuracy_pct}% accurate
                    </span>
                  </>
                ) : (
                  <Badge tone="sky">{p.outcome?.note || 'Upcoming'}</Badge>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
