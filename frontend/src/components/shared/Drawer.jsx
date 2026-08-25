export default function Drawer({ open, onClose, title, children }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-slate-950/70" onClick={onClose} />
      <div className="relative w-full max-w-md h-full bg-slate-900 border-l border-slate-800 shadow-2xl flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 shrink-0">
          <h3 className="font-semibold tracking-tight text-slate-100 text-sm">{title}</h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-100 text-lg leading-none w-6 h-6 flex items-center justify-center rounded hover:bg-slate-800"
          >
            &times;
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  )
}
