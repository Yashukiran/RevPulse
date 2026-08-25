import { useEffect, useMemo, useState } from 'react'
import { LineChart, Line, ResponsiveContainer } from 'recharts'
import { get, formatINR, formatDate, ISSUE_THEMES } from '../api'
import Drawer from './shared/Drawer'
import Badge from './shared/Badge'
import Spinner from './shared/Spinner'

function Sparkline({ monthly }) {
  const data = useMemo(() => {
    const entries = Object.entries(monthly || {}).sort((a, b) => (a[0] > b[0] ? 1 : -1))
    return entries.map(([month, count]) => ({ month, count }))
  }, [monthly])
  if (data.length < 2) {
    return <div className="h-10 flex items-center text-[11px] text-slate-600">not enough data</div>
  }
  return (
    <ResponsiveContainer width="100%" height={40}>
      <LineChart data={data}>
        <Line type="monotone" dataKey="count" stroke="#fb7185" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

function IssueCard({ theme, stats, onOpen }) {
  const count = stats?.theme_counts?.[theme] || 0
  const monthly = stats?.theme_monthly_trend?.[theme] || {}
  const timeConcentration = stats?.theme_time_concentration?.[theme] || {}
  const zoneDist = stats?.theme_zone_distribution?.[theme] || {}
  const topSlot = Object.keys(timeConcentration)[0]
  const topZone = Object.keys(zoneDist)[0]

  return (
    <button
      onClick={() => onOpen(theme)}
      className="text-left bg-slate-900 border border-slate-800 rounded-xl p-4 hover:border-rose-500/40 transition-colors"
    >
      <div className="flex items-start justify-between gap-2">
        <h4 className="text-sm font-semibold tracking-tight text-slate-100 capitalize">{theme}</h4>
        <span className="text-lg font-semibold text-rose-400 tabular-nums shrink-0">{count}</span>
      </div>
      <div className="mt-2">
        <Sparkline theme={theme} monthly={monthly} />
      </div>
      <div className="mt-2 flex flex-col gap-1 text-[11px] text-slate-400">
        <span>
          Peak slot: <span className="text-slate-200">{topSlot || 'n/a'}</span>
        </span>
        <span>
          Top zone: <span className="text-slate-200">{topZone || 'n/a'}</span>
        </span>
      </div>
    </button>
  )
}

export default function IssuesOpportunities({ refresh }) {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [drawerTheme, setDrawerTheme] = useState(null)
  const [drawerReviews, setDrawerReviews] = useState([])
  const [drawerLoading, setDrawerLoading] = useState(false)

  const [churnCustomers, setChurnCustomers] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    get('/api/stats')
      .then(setStats)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
    get('/api/customers?churn_signal=true&limit=60')
      .then(setChurnCustomers)
      .catch(() => setChurnCustomers(null))
  }, [refresh])

  const openDrawer = (theme) => {
    setDrawerTheme(theme)
    setDrawerLoading(true)
    get(`/api/reviews?theme=${encodeURIComponent(theme)}&limit=15`)
      .then((r) => setDrawerReviews(r.reviews || []))
      .catch(() => setDrawerReviews([]))
      .finally(() => setDrawerLoading(false))
  }

  const heroTheme = useMemo(() => {
    if (!stats) return null
    const entries = Object.entries(stats.theme_counts || {}).filter(
      ([theme]) => theme.toLowerCase().includes('biryani')
    )
    if (entries.length === 0) return null
    entries.sort((a, b) => b[1] - a[1])
    return entries[0]
  }, [stats])

  const positiveTotal = stats?.sentiment_distribution?.positive || 0
  const heroShare = heroTheme && positiveTotal ? Math.round((heroTheme[1] / positiveTotal) * 100) : null

  const churnLtvTotal = useMemo(() => {
    if (!churnCustomers?.customers) return 0
    return churnCustomers.customers.reduce((sum, c) => sum + (c.ltv_inr || 0), 0)
  }, [churnCustomers])

  if (loading) return <div className="text-slate-400 text-sm">Loading issues…</div>
  if (error) return <div className="text-rose-400 text-sm">Failed to load: {error}</div>

  return (
    <div className="space-y-8">
      <section>
        <h3 className="text-sm font-semibold tracking-tight text-slate-200 mb-3">Detected issues</h3>
        <div className="grid grid-cols-4 gap-4">
          {ISSUE_THEMES.map((theme) => (
            <IssueCard key={theme} theme={theme} stats={stats} onOpen={openDrawer} />
          ))}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-semibold tracking-tight text-slate-200 mb-3">Opportunities</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <p className="text-xs text-slate-400 uppercase tracking-wide">Hero product</p>
            {heroTheme ? (
              <>
                <h4 className="mt-1 text-lg font-semibold tracking-tight text-slate-100 capitalize">
                  {heroTheme[0]}
                </h4>
                <div className="mt-3 flex items-baseline gap-3">
                  <span className="text-2xl font-semibold text-emerald-400 tabular-nums">{heroTheme[1]}</span>
                  <span className="text-xs text-slate-400">mentions in praise</span>
                </div>
                {heroShare != null && (
                  <p className="mt-1 text-xs text-slate-400">
                    <span className="text-emerald-400 font-semibold">{heroShare}%</span> share of all
                    positive reviews
                  </p>
                )}
                <p className="mt-3 text-xs text-slate-500">
                  Consider featuring this dish in campaigns and upsell prompts — it is your strongest
                  reputation driver.
                </p>
              </>
            ) : (
              <p className="mt-2 text-xs text-slate-500">No standout hero theme detected yet.</p>
            )}
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <p className="text-xs text-slate-400 uppercase tracking-wide">Win-back opportunity</p>
            {churnCustomers ? (
              <>
                <div className="mt-3 flex items-baseline gap-3">
                  <span className="text-2xl font-semibold text-amber-400 tabular-nums">
                    {churnCustomers.matched ?? churnCustomers.customers?.length ?? 0}
                  </span>
                  <span className="text-xs text-slate-400">customers flagged churn-risk</span>
                </div>
                <p className="mt-1 text-xs text-slate-400">
                  Combined LTV at risk:{' '}
                  <span className="text-emerald-400 font-semibold">{formatINR(churnLtvTotal)}</span>
                </p>
                <p className="mt-3 text-xs text-slate-500">
                  Use Action Center to ask the agent for a win-back campaign — recovery offers are
                  policy-gated and capped per customer.
                </p>
              </>
            ) : (
              <div className="mt-3">
                <Spinner />
              </div>
            )}
          </div>
        </div>
      </section>

      <Drawer open={!!drawerTheme} onClose={() => setDrawerTheme(null)} title={drawerTheme}>
        {drawerLoading ? (
          <div className="flex items-center gap-2 text-slate-400 text-xs">
            <Spinner /> Loading reviews…
          </div>
        ) : drawerReviews.length === 0 ? (
          <p className="text-slate-500 text-xs">No reviews found for this theme.</p>
        ) : (
          <ul className="space-y-3">
            {drawerReviews.map((r) => (
              <li key={r.id} className="border border-slate-800 rounded-lg p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-amber-400 text-xs">{'★'.repeat(r.rating)}{'☆'.repeat(5 - r.rating)}</span>
                  <span className="text-[11px] text-slate-500">{formatDate(r.ts)}</span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">{r.text}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {(r.themes || []).map((t) => (
                    <Badge key={t} tone={ISSUE_THEMES.includes(t) ? 'rose' : 'emerald'}>
                      {t}
                    </Badge>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Drawer>
    </div>
  )
}
