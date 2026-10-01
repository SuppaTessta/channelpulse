# Deploy checklist

Deploying the public demo for the first time, in order. The topology is decisions D25:
- the dashboard on Vercel;
- the API on Render;
- a Supabase project holding only the `marts` schema, refreshed nightly by GitHub Actions.

The demo launches in **replay mode**: no model is ever called, and the Ask page shows the answers recorded by the last full eval run (D29). Everything here is done by you in your own accounts. Nothing in the repo creates accounts or holds credentials.

Placeholders: `<ref>` is the Supabase project ref, `<region>` its pooler host region, `<render-url>` and `<vercel-url>` the two service URLs.

## 0. Before anything is public
- [ ] **Identifying-information check.** Put every term that must never appear, one per line, in `.identity-patterns` at the repo root. That means real names, employer and client names, email addresses and domains, and anything else that identifies you. The file is gitignored; keep it that way.
  - Run `make identity-check`. It searches tracked files at every commit, commit messages, and author and committer identities.
  - It must end `OK`. It never prints the terms, so its output is safe to share.
- [ ] `git log --all --format='%an <%ae>' | sort -u` shows only the identity you mean to publish.
- [ ] Optional, but it gives replay mode something to show: run the eval (Part B) and commit `api/app/recordings/<model>.json`. Without it, the Ask page shows an honest "no recorded answers yet" state.

## 1. Supabase (database)
- [ ] Create a project. A region near India, such as Mumbai, keeps latency down. Save the database password you choose: it's the admin password.
- [ ] Copy the **Session pooler** connection string (Connect → Session pooler, port 5432).
  - Don't use the direct connection. On the free tier it's IPv6-only, and neither GitHub Actions nor Render can reach IPv6.
  - It looks like `postgresql://postgres.<ref>:<admin-password>@aws-0-<region>.pooler.supabase.com:5432/postgres`.
- [ ] Generate two strong, distinct passwords for the API's roles. For example, run `python -c "import secrets; print(secrets.token_urlsafe(24))"` twice. These are `AGENT_DB_PASSWORD` and `OPS_DB_PASSWORD`.

## 2. GitHub (code and the nightly refresh)
- [ ] Create the repository and push the branch you're deploying (merged into `main`).
- [ ] Add three repository secrets (Settings → Secrets and variables → Actions):
  - `SUPABASE_DB_URL`: the Session pooler string from step 1, with the admin user;
  - `AGENT_DB_PASSWORD` and `OPS_DB_PASSWORD`: the two passwords from step 1.

  Do **not** add any model key (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`) or an Ollama URL: no workflow may ever hold a model credential (a test enforces it).
- [ ] Run the refresh once by hand: Actions → daily → Run workflow. It builds the warehouse through yesterday (IST) in a throwaway Postgres, then publishes `marts` to Supabase and creates the two roles with your passwords. The "Freshness check" step must pass, showing the published date equal to yesterday.
- [ ] Note that GitHub turns off scheduled workflows in public repos after 60 days without activity. A commit or a manual run resets the clock.

## 3. Render (API)
- [ ] New → Blueprint → pick the repository. `render.yaml` defines `channelpulse-api`, a free Docker web service built from `api/`.
- [ ] Fill in the variables it asks for, each through the **Session pooler**, where the username carries the project ref:
  - `AGENT_DATABASE_URL`: `postgresql://channelpulse_agent.<ref>:<AGENT_DB_PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres`
  - `DATABASE_URL`: the same agent string. It's used only by `/health`, so it never needs admin rights.
  - `OPS_DATABASE_URL`: `postgresql://channelpulse_ops.<ref>:<OPS_DB_PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres`
  - `GEMINI_API_KEY`: leave it empty for replay only.
  - `CORS_ORIGINS`: leave it empty for now, and fill it in after step 4.
  - `ADMIN_TOKEN`: optional, and best left empty. Set, it lets the Agent traces page list live `/api/ask` traces, which are visitors' own questions, to a request carrying it (D40). Empty, the page shows only the eval's recorded traces.
- [ ] Keep `ASK_LIVE=0`, as the blueprint sets it: this is replay mode.
- [ ] Check that `https://<render-url>/health` returns `{"status":"ok","db":"ok"}`.
- [ ] Check that `https://<render-url>/api/ask/status` shows `"mode":"replay"`.
- [ ] Expect the free plan to sleep after about 15 idle minutes. The first request after a quiet spell can take up to a minute to wake it, so the first page view may show panels with "The API didn't answer in time". Retry once it's awake.

## 4. Vercel (dashboard)
- [ ] Add a new project from the repository, with **Root Directory** `web`. The framework is detected as Next.js; choose Node 24 if asked.
- [ ] Add the environment variable `NEXT_PUBLIC_API_URL=https://<render-url>`, then deploy.
  - This value is compiled into the browser code, so changing it later needs a redeploy.
  - Optionally, also set `CHANNELPULSE_API_URL` if the server-side calls should use a different base URL.
  - Only if you set `ADMIN_TOKEN` on Render: set the same value as `CHANNELPULSE_ADMIN_TOKEN`. It's read server-side only and never reaches the browser. Never put it in a `NEXT_PUBLIC_` variable.
- [ ] Back on Render, set `CORS_ORIGINS=https://<vercel-url>`.
  - It's only needed once live mode is on, since that's when the browser calls the API directly.
  - Setting it now saves forgetting later.
- [ ] If pages time out on Vercel before the API does, raise the project's function max duration. A dashboard page makes about 25 governed queries, four at a time.

## 5. Verify the deployed demo
- [ ] Run the smoke test against it from your machine:
  `SMOKE_URL=https://<vercel-url> SMOKE_API_URL=https://<render-url> SMOKE_REMOTE=1 make smoke`

  `SMOKE_REMOTE=1` skips the two checks that need a local build: the build-ID check and the fault-injection test.
- [ ] Open all six pages (the four dashboards, Weekly Brief and Agent traces) in "All regions" and one single region. The Ask page must show replay mode, or "no recorded answers yet", and never an error.
- [ ] The nightly refresh republishes `marts` around 00:30 IST. Queries during those few seconds can fail, and Retry fixes them.

## 6. Live mode (optional, later, costs money)
Live mode only turns on when you set both variables below.
- [ ] Pick the provider. The default is Gemini's free tier: set `GEMINI_API_KEY` (and `GEMINI_MODEL` if it isn't `gemini-3.5-flash-lite`). The free tier may use prompts to improve Google's products; that's acceptable here only because every row is synthetic. For Claude, set `CHANNELPULSE_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`, and set a monthly spend limit in the Anthropic Console as a second fence.
- [ ] On Render, set that key, then `ASK_LIVE=1`.
- [ ] Two limits in `render.yaml` then apply to every live question:
  - a per-IP rate limit, `ASK_RATE_PER_MIN=4`, with the client IP taken from `X-Forwarded-For` (`TRUST_PROXY=1`);
  - a daily spend cap, `DAILY_SPEND_CAP_USD=2.00`, computed from each question's traced cost. Past it, `/api/ask` answers 503 until the next UTC day.
- [ ] To go back to replay, set `ASK_LIVE=0`. No redeploy of the dashboard is needed.
