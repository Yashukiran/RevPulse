const TONES = {
  emerald: 'bg-emerald-400/10 text-emerald-400 border-emerald-400/30',
  rose: 'bg-rose-400/10 text-rose-400 border-rose-400/30',
  amber: 'bg-amber-400/10 text-amber-400 border-amber-400/30',
  sky: 'bg-sky-400/10 text-sky-400 border-sky-400/30',
  slate: 'bg-slate-400/10 text-slate-400 border-slate-400/30',
}

export default function Badge({ children, tone = 'slate', className = '' }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-medium whitespace-nowrap ${TONES[tone] || TONES.slate} ${className}`}
    >
      {children}
    </span>
  )
}
