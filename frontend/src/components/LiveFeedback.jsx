import { useEffect, useRef, useState } from 'react'
import { get, post, formatTime, ISSUE_THEMES } from '../api'
import Badge from './shared/Badge'
import Spinner from './shared/Spinner'

function sentimentTone(s) {
  if (s === 'positive') return 'emerald'
  if (s === 'negative') return 'rose'
  return 'slate' // neutral, mixed, unextracted
}

function urgencyTone(u) {
  if (u === 'urgent') return 'rose'
  if (u === 'important') return 'amber'
  if (u === 'routine') return 'sky'
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
          className={`text-2xl leading-none transition-colors ${
            n <= value ? 'text-amber-400' : 'text-slate-700 hover:text-slate-500'
          }`}
        >
          ★
        </button>
      ))}
    </div>
  )
}

function StreamRow({ review, isNew }) {
  const name = review.customer || (review.customer_id ? `Customer #${review.customer_id}` : 'Guest')
  return (
    <div className={`border-b border-slate-800/60 px-3 py-2.5 ${isNew ? 'flash-emerald' : ''}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-slate-200 text-xs font-medium truncate">{name}</span>
        <span className="text-[11px] text-slate-500 shrink-0">{formatTime(review.ts)}</span>
      </div>
      <div className="mt-0.5 text-amber-400 text-[11px]">
        {'★'.repeat(review.rating)}
        {'☆'.repeat(5 - review.rating)}
      </div>
      <p className="mt-1 text-xs text-slate-300 leading-relaxed">{review.text}</p>
      <div className="mt-1.5 flex flex-wrap gap-1">
        {(review.themes || []).map((t) => (
          <Badge key={t} tone={ISSUE_THEMES.includes(t) ? 'rose' : 'emerald'}>
            {t}
          </Badge>
        ))}
        {review.churn_signal && <Badge tone="amber">churn risk</Badge>}
      </div>
    </div>
  )
}

export default function LiveFeedback({ incomingReview, reviewsConnected }) {
  // ---- submission form ----
  const [name, setName] = useState('')
  const [rating, setRating] = useState(0)
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)
  const [formError, setFormError] = useState(null)

  // ---- live stream ----
  const [reviews, setReviews] = useState([])
  const [streamLoading, setStreamLoading] = useState(true)
  const [streamError, setStreamError] = useState(null)
  const [freshIds, setFreshIds] = useState(() => new Set())

  const addToStream = (review) => {
    setReviews((prev) => {
      if (prev.some((r) => r.id === review.id)) return prev
      return [review, ...prev]
    })
    setFreshIds((prev) => {
      const next = new Set(prev)
      next.add(review.id)
      return next
    })
    setTimeout(() => {
      setFreshIds((prev) => {
        const next = new Set(prev)
        next.delete(review.id)
        return next
      })
    }, 1100)
  }

  useEffect(() => {
    setStreamLoading(true)
    setStreamError(null)
    get('/api/reviews?limit=8')
      .then((r) => setReviews(r.reviews || []))
      .catch((e) => setStreamError(e.message))
      .finally(() => setStreamLoading(false))
  }, [])

  const incomingRef = useRef(null)
  useEffect(() => {
    if (!incomingReview || incomingReview === incomingRef.current) return
    incomingRef.current = incomingReview
    addToStream(incomingReview)
  }, [incomingReview])

  const submit = (e) => {
    e.preventDefault()
    if (!rating || !text.trim() || submitting) return
    setSubmitting(true)
    setFormError(null)
    const body = { rating, text: text.trim() }
    if (name.trim()) body.name = name.trim()
    post('/api/reviews/submit', body)
      .then((res) => {
        setResult(res)
        addToStream(res)
        setName('')
        setRating(0)
        setText('')
      })
      .catch((e) => setFormError(e.message))
      .finally(() => setSubmitting(false))
  }

  return (
    <div className="grid grid-cols-2 gap-6 items-start">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 className="text-base font-semibold tracking-tight text-slate-100">How was your order?</h3>
        <p className="mt-0.5 text-xs text-slate-400">Biryani House · feedback linked to your payment</p>

        <form onSubmit={submit} className="mt-4 space-y-3">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Your name (optional)"
            className="w-full bg-slate-950/60 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-400/50"
          />

          <StarPicker value={rating} onChange={setRating} />

          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Tell us about your order…"
            rows={4}
            className="w-full bg-slate-950/60 border border-slate-800 rounded-lg p-3 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-400/50 resize-none"
          />

          <button
            type="submit"
            disabled={submitting || !rating || !text.trim()}
            className="px-4 py-2 rounded-lg bg-emerald-500/90 hover:bg-emerald-500 disabled:opacity-50 text-slate-950 text-xs font-semibold flex items-center gap-2"
          >
            {submitting && <Spinner className="border-slate-950/40 border-t-slate-950" />}
            Submit feedback
          </button>
        </form>

        {formError && <p className="mt-3 text-xs text-rose-400">{formError}</p>}

        {result && (
          <div className="mt-4 border-t border-slate-800 pt-4 space-y-2">
            <p className="text-[11px] text-sky-400 uppercase tracking-wide font-medium">
              Analyzed in real time
            </p>
            <div className="flex flex-wrap gap-1.5">
              {result.sentiment && <Badge tone={sentimentTone(result.sentiment)}>{result.sentiment}</Badge>}
              {result.urgency && <Badge tone={urgencyTone(result.urgency)}>{result.urgency}</Badge>}
              {result.churn_signal && <Badge tone="amber">churn risk</Badge>}
              {(result.themes || []).map((t) => (
                <Badge key={t} tone={ISSUE_THEMES.includes(t) ? 'rose' : 'emerald'}>
                  {t}
                </Badge>
              ))}
            </div>
          </div>
        )}

        <p className="mt-4 text-[11px] text-slate-500 leading-relaxed">
          In production this page is linked from the Razorpay payment-success screen, tying every review
          to a transaction.
        </p>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <h3 className="text-sm font-semibold tracking-tight">Live review stream</h3>
          <div className="flex items-center gap-2 text-[11px] text-slate-400">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                reviewsConnected ? 'bg-emerald-400' : 'bg-amber-400 pulse-dot'
              }`}
            />
            {reviewsConnected ? 'live' : 'reconnecting'}
          </div>
        </div>
        <div className="max-h-[520px] overflow-y-auto">
          {streamLoading ? (
            <div className="px-4 py-4 text-xs text-slate-400">Loading reviews…</div>
          ) : streamError ? (
            <div className="px-4 py-4 text-xs text-rose-400">Failed to load: {streamError}</div>
          ) : reviews.length === 0 ? (
            <div className="px-4 py-4 text-xs text-slate-500">No reviews yet.</div>
          ) : (
            reviews.map((r) => <StreamRow key={r.id} review={r} isNew={freshIds.has(r.id)} />)
          )}
        </div>
      </div>
    </div>
  )
}
