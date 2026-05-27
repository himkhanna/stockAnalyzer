# Mobile access via Tailscale

This guide gets the app on your phone from anywhere — home, office, mobile
data — without exposing anything to the public internet. Your data and the
backend stay on your laptop; Tailscale creates a private mesh network
between your devices.

Estimated time: 10 minutes.

## What you'll set up

```
  Phone (Tailscale)        Laptop (Tailscale)
     │                        │
     │     encrypted mesh     │
     └──────── via Tailscale ─┘
              │
              ▼
     http://<laptop-name>.tail-xyz.ts.net:5173  ← frontend (Vite)
                              │ proxies /api
                              ▼
                       localhost:8765          ← backend (uvicorn)
```

The phone hits Vite over Tailscale; Vite proxies `/api/*` to the backend
running on the same laptop. The backend itself does not need to be exposed
on any interface beyond `127.0.0.1`.

## Steps

### 1. Install Tailscale on the laptop

- Windows / Mac: download from <https://tailscale.com/download>
- Linux: `curl -fsSL https://tailscale.com/install.sh | sh`

Then sign in (Google / Microsoft / GitHub account works; free for personal
use). Once logged in, `tailscale status` should show the laptop's node name
and assigned IP (e.g. `100.x.y.z`).

### 2. Install Tailscale on the phone

App Store / Play Store → install **Tailscale** → sign in with the *same*
account you used on the laptop.

### 3. Note the laptop's Tailscale hostname

On the laptop:
```bash
tailscale status
```

Look for the line ending in `linux/mac/windows` and grab the hostname
(e.g. `mylaptop`). Tailscale also gives you a fully-qualified name like
`mylaptop.tail-XXXX.ts.net` — either works from the phone.

### 4. Start the servers on the laptop

```bash
# In one shell — backend (stays on 127.0.0.1)
uvicorn web.api.main:app --reload --port 8765

# In another shell — frontend (already configured to listen on all interfaces)
cd web/frontend
npm run dev
```

Vite will print something like:
```
  ➜  Local:   http://localhost:5173/
  ➜  Network: http://192.168.1.42:5173/
  ➜  Network: http://100.x.y.z:5173/   ← this is the Tailscale interface
```

### 5. Open the app on the phone

In the phone's browser, navigate to:

```
http://<your-laptop-name>:5173
```

For example: `http://mylaptop:5173` or `http://mylaptop.tail-XXXX.ts.net:5173`.

That's it.

## Why this is safe

- The Vite dev server listens on all interfaces, but Tailscale only routes
  traffic between devices on **your** tailnet — no one else on the public
  internet can reach it.
- The backend stays bound to `127.0.0.1`. It is not reachable from the
  Tailscale network directly; only via Vite's server-side proxy.
- Your ICICI Breeze credentials, holdings DB, etc. never leave your laptop.

## Troubleshooting

- **"Site can't be reached" on the phone**: make sure both devices show
  in `tailscale status` on the laptop, and that Tailscale is "Connected"
  in the phone's app.
- **Tables look squashed / unreadable on the phone**: this is the UI
  layer; the underlying app works. A separate mobile-responsive pass
  fixes that.
- **Vite is still bound to localhost only**: re-pull `vite.config.ts`
  (the `host: true` line is what binds it to all interfaces) and restart
  `npm run dev`.

## When you want 24/7 access without your laptop on

This setup needs your laptop awake and the servers running. If you want
the app live independent of your laptop, deploy to a small VPS (Hetzner /
DO €5/month). That's a separate guide.
