import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // recharts pulls in a sizeable d3 dependency tree; this is a single-page
    // dashboard with no route-based code-splitting opportunity, so raise the
    // warning threshold rather than chase a false-positive warning.
    chunkSizeWarningLimit: 700,
  },
})
