import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  LineChart,
  Line,
  Legend,
  Cell,
} from 'recharts'
import { get, formatINR, isIssueTheme } from '../api'
import StatTile from './shared/StatTile'

const TOOLTIP_STYLE = {
  background: '#0f172a',
  border: '1px solid #1e293b',
  borderRadius: 8,
  fontSize: 12,
  color: '#e2e8f0',
}

const SENTIMENT_COLOR = {
  positive: '#34d399',
  negative: '#fb7185',
  mixed: '#fbbf24',
  neutral: '#38bdf8',
  unextracted: '#64748b',
}

const LINE_COLORS = ['#fb7185', '#fbbf24', '#f472b6']

export default function Overview({ refresh, live }) {
  const [stats, setStats] = useState(null)
  const [transactions, setTransactions] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const firstLoad = useRef(true)

  useEffect(() => {
    // Only show the full-page loading state on first mount; a refresh bump
    // (e.g. triggered by a live review coming in) refetches quietly behind
    // the data that's already on screen.
    if (firstLoad.current) setLoading(true)
    setError(null)
    Promise.all([get('/api/stats'), get('/api/transactions')])
      .then(([s, t]) => {
        setStats(s)
        setTransactions(t)
      })
      .catch((e) => setError(e.message))
      .finally(() => {
        setLoading(false)
        firstLoad.current = false
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh])


  const themeBars = useMemo(() => {
    if (!stats) return []
    return Object.entries(stats.theme_counts || {})
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([theme, count]) => ({ theme, count, issue: isIssueTheme(theme) }))
  }, [stats])

  const topIssueThemes = useMemo(() => {
    if (!stats) return []
    return Object.entries(stats.theme_counts || {})
      .filter(([theme]) => isIssueTheme(theme))
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([theme]) => theme)
  }, [stats])

  const trendData = useMemo(() => {
    if (!stats || topIssueThemes.length === 0) return []
    const months = new Set()
    topIssueThemes.forEach((t) => {
      Object.keys(stats.theme_monthly_trend?.[t] || {}).forEach((m) => months.add(m))
    })
    return [...months].sort().map((m) => {
      const row = { month: m }
      topIssueThemes.forEach((t) => {
        row[t] = stats.theme_monthly_trend?.[t]?.[m] || 0
      })
      return row
    })
  }, [stats, topIssueThemes])

  const sentimentBars = useMemo(() => {
    if (!stats) return []
    return Object.entries(stats.sentiment_distribution || {}).map(([k, v]) => ({
      sentiment: k,
      count: v,
    }))
  }, [stats])

  const praiseThemes = useMemo(() => {
    if (!stats) return []
    return Object.entries(stats.theme_counts || {})
      .filter(([theme]) => !isIssueTheme(theme))
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
  }, [stats])

  const issueThemesList = useMemo(() => {
    if (!stats) return []
    return Object.entries(stats.theme_counts || {})
      .filter(([theme]) => isIssueTheme(theme))
      .sort((a, b) => b[1] - a[1])
  }, [stats])

  const avgRating = useMemo(() => {
    if (!stats?.rating_distribution) return null
    let sum = 0
    let n = 0
    for (const [rating, count] of Object.entries(stats.rating_distribution)) {
      sum += Number(rating) * count
      n += count
    }
    return n ? (sum / n).toFixed(2) : null
  }, [stats])

  const pctPositive = useMemo(() => {
    if (!stats) return null
    const total = stats.total_reviews || 0
    const pos = stats.sentiment_distribution?.positive || 0
    return total ? Math.round((pos / total) * 100) : null
  }, [stats])

  const lastMonthRevenue = useMemo(() => {
    if (!transactions?.monthly) return null
    // last month with meaningful volume (a stray attributed order can open a new month)
    const months = Object.keys(transactions.monthly)
      .sort()
      .filter((m) => transactions.monthly[m].orders >= 5)
    const last = months[months.length - 1]
    return last ? { month: last, ...transactions.monthly[last] } : null
  }, [transactions])

  if (loading) return <div className="text-slate-400 text-sm">Loading overview…</div>
  if (error) return <div className="text-rose-400 text-sm">Failed to load: {error}</div>

  return (
    <div className="space-y-6">

      <div className="grid grid-cols-4 gap-4">
        <StatTile
          label={
            <span className="flex items-center gap-1.5">
              Total reviews
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${
                  live ? 'bg-emerald-400' : 'bg-slate-600'
                }`}
              />
              <span className={`text-[10px] font-medium ${live ? 'text-emerald-400' : 'text-slate-600'}`}>
                live
              </span>
            </span>
          }
          value={stats?.total_reviews ?? '—'}
        />
        <StatTile
          label="Positive sentiment"
          value={pctPositive != null ? `${pctPositive}%` : '—'}
          accent="text-emerald-400"
        />
        <StatTile label="Avg rating" value={avgRating ? `${avgRating} ★` : '—'} accent="text-amber-400" />
        <StatTile
          label={lastMonthRevenue ? `Revenue (${lastMonthRevenue.month})` : 'Revenue last month'}
          value={lastMonthRevenue ? formatINR(lastMonthRevenue.revenue_inr) : '—'}
          sub={lastMonthRevenue ? `${lastMonthRevenue.orders} orders` : undefined}
          accent="text-emerald-400"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h3 className="text-sm font-semibold tracking-tight mb-3">Top themes in reviews</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={themeBars} layout="vertical" margin={{ left: 8, right: 16 }}>
              <XAxis type="number" stroke="#64748b" fontSize={11} allowDecimals={false} />
              <YAxis
                type="category"
                dataKey="theme"
                stroke="#64748b"
                fontSize={11}
                width={120}
                tick={{ fill: '#94a3b8' }}
              />
              <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'rgba(148,163,184,0.06)' }} />
              <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                {themeBars.map((entry) => (
                  <Cell key={entry.theme} fill={entry.issue ? '#fb7185' : '#34d399'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h3 className="text-sm font-semibold tracking-tight mb-3">Top issue trends by month</h3>
          {trendData.length === 0 ? (
            <div className="h-[220px] flex items-center justify-center text-slate-500 text-xs">
              Not enough data
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={trendData} margin={{ left: -16, right: 8 }}>
                <XAxis dataKey="month" stroke="#64748b" fontSize={11} />
                <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                {topIssueThemes.map((t, i) => (
                  <Line
                    key={t}
                    type="monotone"
                    dataKey={t}
                    stroke={LINE_COLORS[i % LINE_COLORS.length]}
                    strokeWidth={2}
                    dot={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 col-span-1">
          <h3 className="text-sm font-semibold tracking-tight mb-3">Sentiment breakdown</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={sentimentBars} margin={{ left: -16 }}>
              <XAxis dataKey="sentiment" stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} />
              <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'rgba(148,163,184,0.06)' }} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {sentimentBars.map((entry) => (
                  <Cell key={entry.sentiment} fill={SENTIMENT_COLOR[entry.sentiment] || '#64748b'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 col-span-2">
          <h3 className="text-sm font-semibold tracking-tight mb-3">What customers love / hate</h3>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <p className="text-xs font-medium text-emerald-400 mb-2 uppercase tracking-wide">Love</p>
              <ul className="space-y-1.5">
                {praiseThemes.length === 0 && (
                  <li className="text-slate-500 text-xs">No praise themes found.</li>
                )}
                {praiseThemes.map(([theme, count]) => (
                  <li key={theme} className="flex items-center justify-between text-xs">
                    <span className="text-slate-300 truncate pr-2">{theme}</span>
                    <span className="text-emerald-400 font-semibold tabular-nums">{count}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-xs font-medium text-rose-400 mb-2 uppercase tracking-wide">Hate</p>
              <ul className="space-y-1.5">
                {issueThemesList.length === 0 && (
                  <li className="text-slate-500 text-xs">No issue themes found.</li>
                )}
                {issueThemesList.map(([theme, count]) => (
                  <li key={theme} className="flex items-center justify-between text-xs">
                    <span className="text-slate-300 truncate pr-2">{theme}</span>
                    <span className="text-rose-400 font-semibold tabular-nums">{count}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
