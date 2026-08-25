export default function ToastStack({ toasts = [] }) {
  if (toasts.length === 0) return null
  return (
    <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 items-end pointer-events-none">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="toast-in pointer-events-auto flex items-center gap-2 bg-slate-900 border border-emerald-400/40 text-slate-100 text-xs rounded-lg px-4 py-2.5 shadow-lg shadow-emerald-950/40"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shrink-0" />
          {t.text}
        </div>
      ))}
    </div>
  )
}
