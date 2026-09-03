import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Admin dashboard (safety-officer control room UI).
//
// `allowedHosts` mirrors software/mobile_app/vite.config.js: when the dashboard
// is demoed through an HTTPS tunnel (ngrok / cloudflared / Codespaces / a
// sandbox preview URL) Vite's dev server otherwise rejects the request with
// "403 Blocked request. This host is not allowed." Dev/preview server only —
// it has no effect on `vite build` output.
const extraHosts = (process.env.VITE_ALLOWED_HOSTS || '')
  .split(',')
  .map((h) => h.trim())
  .filter(Boolean)

// A leading dot matches the domain and all of its subdomains.
const TUNNEL_HOSTS = [
  'localhost',
  '.ngrok-free.app',
  '.ngrok.io',
  '.ngrok.app',
  '.trycloudflare.com',
  '.loca.lt',
  '.github.dev',
  '.app.github.dev',
  '.gitpod.io',
  '.e2b.dev',
  '.sandbox.novita.ai',
]

const allowedHosts = extraHosts.length ? extraHosts : TUNNEL_HOSTS

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts,
  },
  preview: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts,
  },
})
