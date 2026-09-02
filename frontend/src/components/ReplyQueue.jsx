import { useEffect, useMemo, useRef, useState } from 'react'
import { get, post, formatDate, ISSUE_THEMES } from '../api'
import Badge from './shared/Badge'
import Spinner from './shared/Spinner'

const TABS = [
  { key: 'urgent', label: 'Urgent', tone: 'rose' },
  { key: 'important', label: 'Important', tone: 'amber' },
  { key: 'routine', label: 'Routine', tone: 'sky' },
]

const TONES = ['professional', 'friendly', 'premium']

function sentimentTone(s) {
  if (s === 'positive') return 'emerald'
  if (s === 'negative') return 'rose'
  return 'slate'
}

function StarPicker({ value, onChange }) {
  return (
    <div className="flex items-center gap-1">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          onClick={() => onChange(n)}
          aria-label={`${n} star${n > 1 ? 's' : ''}`}
          className={`text-xl leading-none transition-colors ${
            n <= value ? 'text-amber-400' : 'text-slate-700 hover:text-slate-500'
          }`}
        >
          ★
        </button>
      ))}
    </div>
  )
}

function ReviewRow({ review, isNew }) {
  const [expanded, setExpanded] = useState(isNew)
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
    <div
      className={`border rounded-lg overflow-hidden ${
        isNew ? 'border-emerald-400/40 flash-emerald' : 'border-slate-800'
      }`}
    >
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left p-3 hover:bg-slate-800/40 transition-colors"
      >
        <div className="flex items-center justify-between gap-3">
          {isNew && <Badge tone="emerald">just arrived</Badge>}
          <span className="text-amber-400 text-xs shrink-0">
            {'★'.repeat(review.rating)}
            {'☆'.repeat(5 - review.rating)}
          </span>
          <span className="text-[11px] text-slate-500 shrink-0">{formatDate(review.ts)}</span>
          <span className="text-xs text-slate-300 truncate flex-1">{review.text}</span>
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {review.customer && <Badge tone="slate">{review.customer}</Badge>}
          {review.sentiment && <Badge tone={sentimentTone(review.sentiment)}>{review.sentiment}</Badge>}
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
                {draft.note || 'Posting is a gated action; an approved reply is recorded against the review, not sent to an external review platform.'}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** The customer-facing feedback page, kept here so a review can be received and
 *  answered in the same place. In production this is linked from the payment
 *  success screen, which is what ties every review to a real transaction. */
function FeedbackForm() {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [rating, setRating] = useState(0)
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const submit = (e) => {
    e.preventDefault()
    if (!rating || !text.trim() || submitting) return
    setSubmitting(true)
    setError(null)
    post('/api/reviews/submit', { name: name.trim() || 'Guest', rating, text: text.trim() })
      .then(() => {
        setName('')
        setRating(0)
        setText('')
      })
      .catch((e2) => setError(e2.message))
      .finally(() => setSubmitting(false))
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <span className="text-xs text-slate-300">
          <span className="font-semibold text-slate-100">Customer feedback page</span>
          <span className="text-slate-500"> — linked from the payment screen</span>
        </span>
        <span className="text-xs text-sky-400 font-semibold">{open ? 'Hide' : 'Open'}</span>
      </button>

      {open && (
        <form onSubmit={submit} className="border-t border-slate-800 p-4 space-y-3">
          <p className="text-xs text-slate-400">
            How was your order? Feedback arrives labelled and lands in the queue below.
          </p>
          <div className="flex items-center gap-3">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Your name (optional)"
              className="flex-1 bg-slate-950/60 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-400/50"
            />
            <StarPicker value={rating} onChange={setRating} />
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Tell us about your order…"
            rows={3}
            className="w-full bg-slate-950/60 border border-slate-800 rounded-lg p-3 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-400/50 resize-none"
          />
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting || !rating || !text.trim()}
              className="px-4 py-2 rounded-lg bg-emerald-500/90 hover:bg-emerald-500 disabled:opacity-50 text-slate-950 text-xs font-semibold flex items-center gap-2"
            >
              {submitting && <Spinner className="border-slate-950/40 border-t-slate-950" />}
              Submit feedback
            </button>
            {submitting && (
              <span className="text-xs text-slate-400">Labelling in real time&hellip;</span>
            )}
          </div>
          {error && <p className="text-xs text-rose-400">{error}</p>}
        </form>
      )}
    </div>
  )
}

export default function ReplyQueue({ refresh, incomingReview, reviewsConnected }) {
  const [tab, setTab] = useState('urgent')
  const [reviews, setReviews] = useState([])
  const [matched, setMatched] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [arrivals, setArrivals] = useState([])
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

  // Reviews arriving while the merchant is on this screen surface at the top,
  // already labelled and ready to answer, whichever queue they belong to.
  useEffect(() => {
    if (!incomingReview?.id) return
    setArrivals((prev) =>
      prev.some((r) => r.id === incomingReview.id) ? prev : [incomingReview, ...prev].slice(0, 8)
    )
  }, [incomingReview])

  const arrivalIds = useMemo(() => new Set(arrivals.map((r) => r.id)), [arrivals])
  const queue = useMemo(() => reviews.filter((r) => !arrivalIds.has(r.id)), [reviews, arrivalIds])

  return (
    <div className="space-y-4">
      <FeedbackForm />

      {arrivals.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-2">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                reviewsConnected ? 'bg-emerald-400 pulse-dot' : 'bg-slate-600'
              }`}
            />
            <h3 className="text-sm font-semibold tracking-tight text-slate-200">
              Just arrived
            </h3>
            <span className="text-[11px] text-slate-500">
              {reviewsConnected ? 'live' : 'reconnecting…'}
            </span>
            <button
              onClick={() => setArrivals([])}
              className="ml-auto text-[11px] text-slate-500 hover:text-slate-300"
            >
              Clear
            </button>
          </div>
          <div className="space-y-2">
            {arrivals.map((r) => (
              <ReviewRow key={`new-${r.id}`} review={r} isNew />
            ))}
          </div>
        </section>
      )}

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
      ) : queue.length === 0 ? (
        <p className="text-slate-500 text-xs">No reviews in this queue.</p>
      ) : (
        <div className="space-y-2">
          {queue.map((r) => (
            <ReviewRow key={r.id} review={r} />
          ))}
        </div>
      )}
    </div>
  )
}
