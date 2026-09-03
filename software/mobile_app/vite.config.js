import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Field mobile app (installable PWA). Served over LAN/HTTPS so the phone
// camera (getUserMedia) is available; see README for the HTTPS requirement.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5174,
  },
  preview: {
    host: '0.0.0.0',
    port: 5174,
  },
})
