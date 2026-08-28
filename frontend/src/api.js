// Render supplies the API service's bare hostname, so add the scheme when one
// is missing. Locally VITE_API_URL is unset and we fall back to the dev API.
const RAW = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'
export const API = /^https?:\/\//.test(RAW) ? RAW : `https://${RAW}`

async function handle(res) {
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = body?.detail || JSON.stringify(body)
    } catch {
      // ignore parse errors, fall back to status text
    }
    throw new Error(detail || `${res.status} ${res.statusText}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export function get(path) {
  return fetch(`${API}${path}`).then(handle)
}

export function post(path, body) {
  return fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  }).then(handle)
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
