import { useEffect, useState, useCallback } from 'react'
import { get } from './api'
import Sidebar from './components/shared/Sidebar'
import Overview from './components/Overview'
import IssuesOpportunities from './components/IssuesOpportunities'
import ReplyQueue from './components/ReplyQueue'
import RevenueIntelligence from './components/RevenueIntelligence'
import ActionCenter from './components/ActionCenter'
import AuditConsole from './components/AuditConsole'

const TITLES = {
  overview: 'Overview',
  issues: 'Issues & Opportunities',
  reply: 'Reply Queue',
  revenue: 'Revenue Intelligence',
  action: 'Action Center',
  audit: 'Audit Console',
}

const SUBTITLES = {
  overview: 'Review intelligence at a glance',
  issues: 'Detected problems and growth opportunities, with evidence',
  reply: 'Triaged reviews awaiting a response',
  revenue: 'Transactions, top items, and theme-revenue association',
  action: 'Run the agent, approve gated actions, track campaigns',
  audit: 'Live ops trail — every tool call, policy verdict, and outcome',
}

export default function App() {
  const [view, setView] = useState('overview')
  const [refresh, setRefresh] = useState(0)
  const [merchant, setMerchant] = useState(null)

  const bumpRefresh = useCallback(() => setRefresh((n) => n + 1), [])

  useEffect(() => {
    get('/api/merchant')
      .then(setMerchant)
      .catch(() => setMerchant(null))
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
          {view === 'overview' && <Overview refresh={refresh} />}
          {view === 'issues' && <IssuesOpportunities refresh={refresh} />}
          {view === 'reply' && <ReplyQueue refresh={refresh} bumpRefresh={bumpRefresh} />}
          {view === 'revenue' && <RevenueIntelligence refresh={refresh} />}
          {view === 'action' && <ActionCenter refresh={refresh} bumpRefresh={bumpRefresh} />}
          {view === 'audit' && <AuditConsole refresh={refresh} />}
        </div>
      </main>
    </div>
  )
}
