import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, loadEnv } from 'vite'

/** Refuse to build a bundle that cannot reach the API.
 *
 * A deploy once baked in `revpulse-api` — Render's bare service name rather
 * than its hostname — which is not resolvable, so every screen failed with
 * "Failed to fetch" while the build itself reported success. The cost of that
 * mistake is a broken site that looks deployed, so it is now a build error.
 */
function assertApiUrl(mode) {
  const raw = (loadEnv(mode, process.cwd(), '').VITE_API_URL || '').trim()

  // Unset is fine: api.js falls back to the local dev API.
  if (!raw) return 'http://127.0.0.1:8000 (local dev fallback)'

  const withScheme = /^https?:\/\//.test(raw) ? raw : `https://${raw}`
  let host
  try {
    host = new URL(withScheme).hostname
  } catch {
    throw new Error(`VITE_API_URL is not a valid URL: ${raw}`)
  }

  const isLocal = host === 'localhost' || host === '127.0.0.1'
  if (!isLocal && !host.includes('.')) {
    throw new Error(
      `VITE_API_URL resolves to the bare host "${host}", which browsers cannot ` +
      `reach. Set the full hostname, e.g. https://revpulse-api.onrender.com — ` +
      `do not use Render's fromService/property: host, which yields the ` +
      `service name only.`
    )
  }
  return withScheme
}

export default defineConfig(({ mode }) => {
  const api = assertApiUrl(mode)
  console.log(`[revpulse] dashboard will call: ${api}`)

  return {
    plugins: [react(), tailwindcss()],
    build: {
      // recharts pulls in a sizeable d3 dependency tree; this is a single-page
      // dashboard with no route-based code-splitting opportunity, so raise the
      // warning threshold rather than chase a false-positive warning.
      chunkSizeWarningLimit: 700,
    },
  }
})
