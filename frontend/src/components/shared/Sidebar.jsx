const ICONS = {
  overview: (
    <path d="M3 13h4v7H3zM10 8h4v12h-4zM17 3h4v17h-4z" />
  ),
  issues: (
    <path d="M12 3l9 16H3zM12 9v4M12 16h.01" />
  ),
  reply: (
    <path d="M4 4h16v11H7l-3 3z" />
  ),
  demand: (
    <path d="M3 20V10M9 20V4M15 20v-8M21 20v-5" />
  ),
  revenue: (
    <path d="M3 17l5-5 4 4 8-8M14 8h6v6" />
  ),
  action: (
    <path d="M13 2L4 14h6l-1 8 9-12h-6z" />
  ),
  audit: (
    <path d="M4 5h16M4 10h16M4 15h10M4 20h6" />
  ),
}

const NAV_ITEMS = [
  { key: 'overview', label: 'Overview' },
  { key: 'issues', label: 'Issues & Opportunities' },
  { key: 'reply', label: 'Reply Queue' },
  { key: 'demand', label: 'Demand Planning' },
  { key: 'revenue', label: 'Revenue Intelligence' },
  { key: 'action', label: 'Action Center' },
  { key: 'audit', label: 'Audit Console' },
]

function NavIcon({ name }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0"
    >
      {ICONS[name]}
    </svg>
  )
}

export default function Sidebar({ active, onSelect, merchantName, merchantCity }) {
  return (
    <aside className="fixed inset-y-0 left-0 w-56 bg-slate-900 border-r border-slate-800 flex flex-col z-30">
      <div className="px-4 py-5 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <span className="text-sky-400">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 17l5-6 4 4 9-10" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M15 5h6v6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <h1 className="text-lg font-semibold tracking-tight text-slate-100">RevPulse</h1>
        </div>
        <p className="mt-1 text-xs text-slate-400 truncate">
          {merchantName || 'The Nandana Palace'}
          {merchantCity ? ` · ${merchantCity}` : ''}
        </p>
      </div>
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map((item) => {
          const isActive = active === item.key
          return (
            <button
              key={item.key}
              onClick={() => onSelect(item.key)}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] font-medium transition-colors ${
                isActive
                  ? 'bg-slate-800 text-slate-100'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
              }`}
            >
              <span className={isActive ? 'text-sky-400' : 'text-slate-500'}>
                <NavIcon name={item.key} />
              </span>
              <span className="truncate">{item.label}</span>
            </button>
          )
        })}
      </nav>
      <div className="px-4 py-3 border-t border-slate-800 text-[11px] text-slate-500">
        AI Growth Agent
      </div>
    </aside>
  )
}
