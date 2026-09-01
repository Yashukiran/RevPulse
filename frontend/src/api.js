// The API's address. Render supplies it at build time; locally it is unset and
// we fall back to the dev server. vite.config.js refuses to build if this value
// is malformed, so by the time it reaches here it is a reachable URL.
const RAW = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').trim()
export const API = /^https?:\/\//.test(RAW) ? RAW : `https://${RAW}`

// A local API is either running or it is not: nothing is listening on the port,
// the connection is refused immediately, and waiting will not change that. A
// hosted one is different — free hosting suspends it after ~15 minutes idle and
// takes up to a minute to wake, during which fetch throws a bare "Failed to
// fetch" and the host returns 502/503/504. Neither means the request was wrong.
//
// So the retry budget follows the target: two quick attempts locally, about a
// minute against a host that might be waking up. Retrying a refused localhost
// connection for sixty seconds only makes a missing backend look like a hang.
export const IS_LOCAL_API = /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/.test(API)
const RETRY_DELAYS_MS = IS_LOCAL_API
  ? [400, 800]
  : [1000, 2000, 4000, 8000, 12000, 16000, 20000]
const WAKING_STATUSES = new Set([502, 503, 504])

export class ApiError extends Error {
  constructor(message, { status = null, waking = false } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.waking = waking
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** Listeners notified while the API is being woken, so the UI can explain. */
const wakeListeners = new Set()
export function onApiWaking(fn) {
  wakeListeners.add(fn)
  return () => wakeListeners.delete(fn)
}
function announceWaking(isWaking) {
  for (const fn of wakeListeners) {
    try {
      fn(isWaking)
    } catch {
      // a broken listener must never break a request
    }
  }
}

async function readError(res) {
  try {
    const body = await res.json()
    return body?.detail || JSON.stringify(body)
  } catch {
    return ''
  }
}

async function request(path, init) {
  let announced = false
  let lastProblem = 'the server did not respond'

  for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt++) {
    let res
    try {
      res = await fetch(`${API}${path}`, init)
    } catch {
      // Network-level failure: server asleep, offline, or DNS not resolving.
      lastProblem = 'the server could not be reached'
      res = null
    }

    if (res) {
      if (res.ok) {
        if (announced) announceWaking(false)
        return res.status === 204 ? null : res.json()
      }
      // A real HTTP error (400/404/409/422/500) is the server answering. Do
      // not retry it — retrying a rejected request just repeats the rejection.
      if (!WAKING_STATUSES.has(res.status)) {
        if (announced) announceWaking(false)
        const detail = await readError(res)
        throw new ApiError(detail || `${res.status} ${res.statusText}`, {
          status: res.status,
        })
      }
      lastProblem = `the server returned ${res.status} while starting up`
    }

    if (attempt === RETRY_DELAYS_MS.length) break

    if (!announced) {
      announced = true
      announceWaking(true)
    }
    await sleep(RETRY_DELAYS_MS[attempt])
  }

  if (announced) announceWaking(false)
  throw new ApiError(
    IS_LOCAL_API
      ? `The API is not running. This dashboard reads everything from ` +
        `${API}, and nothing is answering there.\n\n` +
        `Start both servers by double-clicking start.bat — "npm run dev" ` +
        `only starts this dashboard. Or run the API yourself:\n` +
        `cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000`
      : `Could not reach the server — ${lastProblem}. Free hosting suspends ` +
        `the API when idle and it can take up to a minute to start. Reload in ` +
        `a moment; if it persists, the API service is down rather than asleep.`,
    { waking: !IS_LOCAL_API }
  )
}

// Switching tabs refetched everything from scratch, so returning to a screen
// paid the full round trip again. Reads are held briefly and served from
// memory; any write clears the whole cache, so an approval, a rejection, a
// scan or a new review can never leave a stale figure on screen.
const CACHE_TTL_MS = 30_000
const cache = new Map()

const copy = (v) =>
  typeof structuredClone === 'function' ? structuredClone(v) : JSON.parse(JSON.stringify(v))

export function get(path) {
  const hit = cache.get(path)
  if (hit && Date.now() - hit.at < CACHE_TTL_MS) {
    // Hand back a copy: callers sort and reshape what they receive, and that
    // must not edit what the next reader sees.
    return hit.promise.then(copy)
  }
  const promise = request(path, undefined)
  cache.set(path, { at: Date.now(), promise })
  // A failed read must not be remembered as the answer.
  promise.catch(() => {
    if (cache.get(path)?.promise === promise) cache.delete(path)
  })
  return promise.then(copy)
}

export function post(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  }).finally(() => cache.clear())
}

/** Drop cached reads — used when a live event says the data moved. */
export function invalidate() {
  cache.clear()
}

export function wsURL(path) {
  return `${API.replace(/^http/, 'ws')}${path}`
}

export function formatINR(n) {
  const v = Number(n || 0)
  return `₹${v.toLocaleString('en-IN')}`
}

export function formatDate(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
  } catch {
    return ts
  }
}

export function formatTime(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-GB', { hour12: false })
  } catch {
    return ts
  }
}

// Themes we treat as issues (rose) vs praise (emerald) across the dashboard.
export const ISSUE_THEMES = [
  'slow delivery/service',
  'packaging issue',
  'food quality issue',
  'portion size',
]

export function isIssueTheme(theme) {
  return ISSUE_THEMES.includes(theme)
}
