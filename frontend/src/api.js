// The API's address. Render supplies it at build time; locally it is unset and
// we fall back to the dev server. vite.config.js refuses to build if this value
// is malformed, so by the time it reaches here it is a reachable URL.
const RAW = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').trim()
export const API = /^https?:\/\//.test(RAW) ? RAW : `https://${RAW}`

// Free hosting suspends the API after ~15 minutes idle and takes up to a minute
// to wake. During that window fetch throws a bare "Failed to fetch" and the
// provider returns 502/503/504 — none of which mean the request was wrong. So
// transient failures are retried across roughly a minute before giving up, and
// the message the merchant sees says what is actually happening.
const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 12000, 16000, 20000]
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
    `Could not reach the server — ${lastProblem}. Free hosting suspends the ` +
    `API when idle and it can take up to a minute to start. Reload in a moment; ` +
    `if it persists, the API service is down rather than asleep.`,
    { waking: true }
  )
}

export function get(path) {
  return request(path, undefined)
}

export function post(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  })
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
