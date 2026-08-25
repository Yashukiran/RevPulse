export default function Spinner({ className = '' }) {
  return (
    <span
      className={`inline-block h-4 w-4 rounded-full border-2 border-slate-700 border-t-emerald-400 animate-spin ${className}`}
    />
  )
}
