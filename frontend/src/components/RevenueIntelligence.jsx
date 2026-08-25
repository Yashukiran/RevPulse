import { useEffect, useMemo, useRef, useState } from 'react'
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip } from 'recharts'
import { get, formatINR } from '../api'
import Spinner from './shared/Spinner'

const TOOLTIP_STYLE = {
  background: '#0f172a',
  border: '1px solid #1e293b',
  borderRadius: 8,
  fontSize: 12,
  color: '#e2e8f0',
}

const COMPARE_THEMES = ['slow delivery/service', 'packaging issue', 'food quality issue']

export default function RevenueIntelligence({ refresh }) {
  const [transactions, setTransactions] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [theme, setTheme] = useState(COMPARE_THEMES[0])
  const [comparison, setComparison] = useState(null)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const firstLoad = useRef(true)
  const prevTheme = useRef(null)

  useEffect(() => {
    // Only the first load shows the full-page loader; a refresh-only bump
    // (e.g. a live review arriving) refetches quietly behind current data.
    if (firstLoad.current) setLoading(true)
    setError(null)
    get('/api/transactions')
      .then(setTransactions)
      .catch((e) => setError(e.message))
      .finally(() => {
        setLoading(false)
        firstLoad.current = false
      })
  }, [refresh])

  useEffect(() => {
    // A theme switch is a real navigation and shows the loader; a
    // refresh-only trigger keeps the current comparison on screen.
    const isFreshLoad = prevTheme.current !== theme
    prevTheme.current = theme
    if (isFreshLoad) setComparisonLoading(true)
    get(`/api/transactions?compare_theme=${encodeURIComponent(theme)}`)
      .then((r) => setComparison(r.repeat_purchase_comparison || null))
      .catch(() => setComparison(null))
      .finally(() => setComparisonLoading(false))
  }, [theme, refresh])

  const revenueData = useMemo(() => {
    if (!transactions?.monthly) return []
    return Object.entries(transactions.monthly)
      .sort((a, b) => (a[0] > b[0] ? 1 : -1))
      .map(([month, v]) => ({ month, revenue_inr: v.revenue_inr, orders: v.orders }))
  }, [transactions])

  const topItems = useMemo(() => {
    if (!transactions?.top_items_by_revenue) return []
    const entries = Object.entries(transactions.top_items_by_revenue)
    const max = entries.length ? Math.max(...entries.map(([, v]) => v)) : 1
    return entries.map(([item, rev]) => ({ item, rev, pct: max ? (rev / max) * 100 : 0 }))
  }, [transactions])

  if (loading) return <div className="text-slate-400 text-sm">Loading revenue data…</div>
  if (error) return <div className="text-rose-400 text-sm">Failed to load: {error}</div>

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h3 className="text-sm font-semibold tracking-tight mb-3">Monthly revenue</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={revenueData} margin={{ left: -16, right: 8 }}>
              <XAxis dataKey="month" stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} tickFormatter={(v) => `₹${Math.round(v / 1000)}k`} />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(value, name) => [name === 'revenue_inr' ? formatINR(value) : value, name === 'revenue_inr' ? 'Revenue' : 'Orders']}
              />
              <Line type="monotone" dataKey="revenue_inr" stroke="#34d399" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h3 className="text-sm font-semibold tracking-tight mb-3">Top items by revenue</h3>
          <div className="space-y-2.5 max-h-[220px] overflow-y-auto pr-1">
            {topItems.length === 0 && <p className="text-xs text-slate-500">No transaction data.</p>}
            {topItems.map(({ item, rev, pct }) => (
              <div key={item}>
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-slate-300 truncate pr-2">{item}</span>
                  <span className="text-emerald-400 font-semibold tabular-nums shrink-0">
                    {formatINR(rev)}
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                  <div className="h-full bg-emerald-500/70 rounded-full" style={{ width: `${pct}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold tracking-tight">Theme &harr; repeat purchase association</h3>
          <select
            value={theme}
            onChange={(e) => setTheme(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-400/50"
          >
            {COMPARE_THEMES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        {comparisonLoading ? (
          <div className="flex items-center gap-2 text-slate-400 text-xs">
            <Spinner /> Comparing…
          </div>
        ) : comparison ? (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div className="border border-rose-400/20 bg-rose-400/5 rounded-lg p-4">
                <p className="text-xs text-slate-400 capitalize">
                  Customers mentioning &ldquo;{comparison.theme}&rdquo;
                </p>
                <p className="mt-1 text-2xl font-semibold text-rose-400 tabular-nums">
                  {(comparison.customers_mentioning_theme?.repeat_rate * 100).toFixed(1)}%
                </p>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  repeat rate (n={comparison.customers_mentioning_theme?.n})
                </p>
              </div>
              <div className="border border-emerald-400/20 bg-emerald-400/5 rounded-lg p-4">
                <p className="text-xs text-slate-400">Other reviewers</p>
                <p className="mt-1 text-2xl font-semibold text-emerald-400 tabular-nums">
                  {(comparison.other_reviewers?.repeat_rate * 100).toFixed(1)}%
                </p>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  repeat rate (n={comparison.other_reviewers?.n})
                </p>
              </div>
            </div>
            <p className="mt-4 text-[11px] text-amber-400 leading-relaxed">{comparison.note}</p>
          </>
        ) : (
          <p className="text-xs text-slate-500">No comparison data available.</p>
        )}
      </div>
    </div>
  )
}
