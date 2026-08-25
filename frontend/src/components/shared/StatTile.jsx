export default function StatTile({ label, value, sub, accent = 'text-slate-100' }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-1 min-w-0">
      <span className="text-xs text-slate-400 truncate">{label}</span>
      <span className={`text-2xl font-semibold tracking-tight ${accent}`}>{value}</span>
      {sub ? <span className="text-xs text-slate-500 truncate">{sub}</span> : null}
    </div>
  )
}
