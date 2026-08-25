import { useEffect, useRef, useState } from 'react'
import { get, post, formatDate, ISSUE_THEMES } from '../api'
import Badge from './shared/Badge'
import Spinner from './shared/Spinner'

const TABS = [
  { key: 'urgent', label: 'Urgent', tone: 'rose' },
  { key: 'important', label: 'Important', tone: 'amber' },
  { key: 'routine', label: 'Routine', tone: 'sky' },
]

const TONES = ['professional', 'friendly', 'premium']

function ReviewRow({ review }) {
  const [expanded, setExpanded] = useState(false)
  const [tone, setTone] = useState('professional')
  const [drafting, setDrafting] = useState(false)
  const [draft, setDraft] = useState(null)
  const [error, setError] = useState(null)

  const requestDraft = () => {
    setDrafting(true)
    setError(null)
    post('/api/reviews/draft-reply', { review_id: review.id, tone })
      .then((res) => setDraft(res))
      .catch((e) => setError(e.message))
      .finally(() => setDrafting(false))
  }

  return (
    <div className="border border-slate-800 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left p-3 hover:bg-slate-800/40 transition-colors"
      >
        <div className="flex items-center justify-between gap-3">
          <span className="text-amber-400 text-xs shrink-0">
            {'★'.repeat(review.rating)}
            {'☆'.repeat(5 - review.rating)}
          </span>
          <span className="text-[11px] text-slate-500 shrink-0">{formatDate(review.ts)}</span>
          <span className="text-xs text-slate-300 truncate flex-1">{review.text}</span>
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {(review.themes || []).map((t) => (
            <Badge key={t} tone={ISSUE_THEMES.includes(t) ? 'rose' : 'emerald'}>
              {t}
            </Badge>
          ))}
          {review.churn_signal && <Badge tone="amber">churn risk</Badge>}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-slate-800 bg-slate-900/60 p-3 space-y-3">
          <p className="text-xs text-slate-300 leading-relaxed">{review.text}</p>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-slate-500">Tone:</span>
            {TONES.map((t) => (
              <button
                key={t}
                onClick={() => setTone(t)}
                className={`px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors ${
                  tone === t
                    ? 'bg-sky-400/10 border-sky-400/40 text-sky-400'
                    : 'border-slate-700 text-slate-400 hover:text-slate-200'
                }`}
              >
                {t}
              </button>
            ))}
            <button
              onClick={requestDraft}
              disabled={drafting}
              className="ml-auto px-3 py-1.5 rounded-lg bg-emerald-500/90 hover:bg-emerald-500 disabled:opacity-50 text-slate-950 text-[11px] font-semibold flex items-center gap-1.5"
            >
              {drafting && <Spinner className="border-slate-950/40 border-t-slate-950" />}
              Draft reply
            </button>
          </div>

          {error && <p className="text-rose-400 text-xs">{error}</p>}

          {draft && (
            <div className="border-l-2 border-sky-400/50 bg-slate-950/60 rounded-r-lg p-3">
              <p className="text-xs text-slate-200 italic leading-relaxed">&ldquo;{draft.draft}&rdquo;</p>
              <p className="mt-2 text-[11px] text-amber-400">
                {draft.note || 'Posting publicly requires approval (gated action).'}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function ReplyQueue({ refresh }) {
  const [tab, setTab] = useState('urgent')
  const [reviews, setReviews] = useState([])
  const [matched, setMatched] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const prevTab = useRef(null)

  useEffect(() => {
    // A tab switch (or the first mount) is a real navigation — show the
    // loader. A refresh-only trigger (e.g. a live review coming in) refetches
    // quietly, keeping the current rows on screen until the new ones arrive.
    const isFreshLoad = prevTab.current !== tab
    prevTab.current = tab
    if (isFreshLoad) setLoading(true)
    setError(null)
    get(`/api/reviews?urgency=${tab}&limit=20`)
      .then((r) => {
        setReviews(r.reviews || [])
        setMatched(r.matched || 0)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [tab, refresh])

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
              tab === t.key
                ? 'bg-slate-800 border-slate-700 text-slate-100'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            {t.label}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-slate-500">{matched} matching</span>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-slate-400 text-xs">
          <Spinner /> Loading reviews…
        </div>
      ) : error ? (
        <p className="text-rose-400 text-xs">{error}</p>
      ) : reviews.length === 0 ? (
        <p className="text-slate-500 text-xs">No reviews in this queue.</p>
      ) : (
        <div className="space-y-2">
          {reviews.map((r) => (
            <ReviewRow key={r.id} review={r} />
          ))}
        </div>
      )}
    </div>
  )
}
