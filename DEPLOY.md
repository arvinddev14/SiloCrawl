# Deploying SiloCrawl

SiloCrawl is two deployables:

- **Frontend** (`frontend/`, Next.js) → **Vercel**
- **Backend** (`app/`, FastAPI) → **Render** (it needs a real server: headless
  Chromium, in-process background crawls, a SQLite file, and long LLM calls —
  none of which run on Vercel's serverless functions)

Deploy the **backend first** so you have its URL for the frontend, then point
CORS back at the frontend once it's live. The repo already contains everything
these steps reference (`render.yaml`, both Dockerfiles, env examples).

---

## 1. Backend → Render

1. Push this repo to GitHub (already done: `arvinddev14/SiloCrawl`).
2. Render Dashboard → **New → Blueprint** → select this repo. Render reads
   [`render.yaml`](render.yaml) and creates the `silocrawl-api` web service.
3. Set the secret env vars when prompted (they're marked `sync: false`):
   - `HF_API_KEY` — your HuggingFace token
   - `HF_ENDPOINT_URL` — your gpt-oss inference endpoint
   - `CORS_ALLOW_ORIGINS` — leave blank for now; you'll set it in step 3.
4. Deploy. When it's live, note the URL, e.g. `https://silocrawl-api.onrender.com`.
   Check `https://<that-url>/health` → `{"status":"ok"}` and `/docs` for the API.

> **Free tier = ephemeral data.** Render's free plan has no persistent disk, so
> the SQLite file (crawl jobs, telemetry, deletion log) resets on every
> deploy/restart. For durable storage, upgrade the plan and enable the `disk`
> block in `render.yaml` (instructions are in the file), then set
> `DATABASE_URL=sqlite+aiosqlite:////data/silocrawl.db`.

---

## 2. Frontend → Vercel

1. Vercel Dashboard → **Add New → Project** → import this GitHub repo.
2. **Set Root Directory to `frontend`** (this is a monorepo; Vercel then
   auto-detects Next.js). This is the one setting people miss.
3. Add environment variables:
   - `NEXT_PUBLIC_API_URL` = your Render URL from step 1
     (e.g. `https://silocrawl-api.onrender.com`)
   - `NEXT_PUBLIC_API_KEY` = only if you enabled auth on the backend
4. Deploy. Note the URL, e.g. `https://silocrawl.vercel.app`.

---

## 3. Wire CORS back to the frontend

The backend rejects browser calls from unknown origins. In the Render
dashboard, set:

```
CORS_ALLOW_ORIGINS = https://silocrawl.vercel.app
```

(comma-separate multiple origins, e.g. a preview domain + a custom domain).
Save — Render redeploys. The frontend can now reach the API.

Verify end to end: open the Vercel URL → Playground → run a scrape. If the
browser console shows a CORS error, re-check the origin string matches exactly
(scheme + host, no trailing slash).

---

## Going to production (checklist)

- **Auth on:** in Render → your service → **Environment**, set `AUTH_ENABLED=true`
  and add `API_KEYS` = one or more comma-separated secrets (generate one with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Then on Vercel
  set `NEXT_PUBLIC_API_KEY` to one of those keys and redeploy the frontend.
  Without this, anyone who finds the API URL can run jobs (and spend your LLM
  budget). Leave `AUTH_ENABLED` unset/false and `API_KEYS` is ignored.
- **Persistent disk** on Render if you rely on stored jobs / the deletion log.
- **Custom domains:** add them on both platforms, then add the frontend's
  domain to `CORS_ALLOW_ORIGINS`.
- **Keep `ALLOW_PRIVATE_NETWORKS=false`** (the SSRF guard) on any public host.
