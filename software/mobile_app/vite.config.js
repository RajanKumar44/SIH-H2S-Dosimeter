import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Field mobile app (installable PWA).
//
// The phone camera (`getUserMedia`) only works in a SECURE CONTEXT, i.e.
// https:// or localhost. On a real handset that means the dev server has to be
// reached through an HTTPS tunnel (ngrok / cloudflared / Codespaces / a sandbox
// preview URL). Vite's dev server rejects requests whose Host header it does
// not recognise, so every one of those tunnel URLs returned:
//
//   403  Blocked request. This host (...) is not allowed.
//
// ...which broke the camera demo entirely: the only way to get HTTPS was
// through a host Vite refused to serve. `allowedHosts` below fixes that.
//
// Scope: this affects the DEV SERVER only (never `vite build` output), and the
// tunnel hostnames are random per session, so they cannot be hard-coded. Set
// VITE_ALLOWED_HOSTS to pin an explicit list if you prefer.
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
    port: 5174,
    allowedHosts,
  },
  preview: {
    host: '0.0.0.0',
    port: 5174,
    allowedHosts,
  },
})
