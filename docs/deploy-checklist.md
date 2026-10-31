# Deploy checklist

Deploying the public demo for the first time, in order. The topology is decisions D25:
- the dashboard on Vercel;
- the API on Render;
- a Supabase project holding only the `marts` schema, refreshed nightly by GitHub Actions.

The demo launches with **live Ask** (D55). Each visitor gets 5 free questions a UTC day on your Anthropic key, and can bring their own key for more. Your spend stops at $1 a day and $10 a month. Everything here is done by you in your own accounts. Nothing in the repo creates accounts or holds credentials.

Placeholders: `<ref>` is the Supabase project ref, `<region>` its pooler host region, `<render-url>` and `<vercel-url>` the two service URLs.

## 0. Before anything is public
- [ ] **Secret scan** (D49): `docker run --rm -v "<repo>:/repo:ro" zricethezav/gitleaks:latest git /repo --redact --no-banner -v` must end "no leaks found". On Git Bash, prefix it with `MSYS_NO_PATHCONV=1`.
- [ ] **Identifying-information check.** Put every term that must never appear, one per line, in `.identity-patterns` at the repo root. That means real names, employer and client names, email addresses and domains, and anything else that identifies you. The file is gitignored; keep it that way.
  - Run `make identity-check`. It searches tracked files at every commit, commit messages, and author and committer identities.
  - It must end `OK`. It never prints the terms, so its output is safe to share.
- [ ] `git log --all --format='%an <%ae>' | sort -u` shows only the identity you mean to publish.
- [ ] Optional, but it gives replay mode something to show: run the eval (`make eval`, see the README) and commit `api/app/recordings/anthropic__<model>.json`. Without it, the Ask page shows an honest "no recorded answers yet" state.

## 1. Supabase (database)
- [ ] Create a project. A region near India, such as Mumbai, keeps latency down. Save the database password you choose: it's the admin password.
  - The Data API can stay off. The API connects to Postgres directly and never uses Supabase's REST endpoints.
- [ ] The free plan caps the database at 500 MB and goes read-only above it, which would stop the nightly refresh. The published `marts` measure about 356 MB (D49). Check Database → Reports → Database size now and then.
- [ ] Copy the **Session pooler** connection string (Connect → Session pooler, port 5432).
  - Don't use the direct connection. On the free tier it's IPv6-only, and neither GitHub Actions nor Render can reach IPv6.
  - It looks like `postgresql://postgres.<ref>:<admin-password>@aws-0-<region>.pooler.supabase.com:5432/postgres`.
- [ ] Generate two strong, distinct passwords for the API's roles. For example, run `python -c "import secrets; print(secrets.token_urlsafe(24))"` twice. These are `AGENT_DB_PASSWORD` and `OPS_DB_PASSWORD`.

## 2. GitHub (code and the nightly refresh)
- [ ] Create the repository and push the branch you're deploying (merged into `main`).
- [ ] Add three repository secrets (Settings → Secrets and variables → Actions):
  - `SUPABASE_DB_URL`: the Session pooler string from step 1, with the admin user;
  - `AGENT_DB_PASSWORD` and `OPS_DB_PASSWORD`: the two passwords from step 1.

  Do **not** add a model key (`ANTHROPIC_API_KEY`): no workflow may ever hold a model credential (a test enforces it).
- [ ] Run the refresh once by hand: Actions → daily → Run workflow. It builds the warehouse through yesterday (IST) in a throwaway Postgres, then publishes `marts` to Supabase and creates the two roles with your passwords. The "Freshness check" step must pass, showing the published date equal to yesterday.
- [ ] Note that GitHub turns off scheduled workflows in public repos after 60 days without activity. A commit or a manual run resets the clock.

## 3. Render (API)
- [ ] New → Blueprint → pick the repository. `render.yaml` defines `channelpulse-api`, a free Docker web service built from `api/`.
- [ ] Fill in the variables it asks for, each through the **Session pooler**, where the username carries the project ref:
  - `AGENT_DATABASE_URL`: `postgresql://channelpulse_agent.<ref>:<AGENT_DB_PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres`
  - `DATABASE_URL`: the same agent string. It's used only by `/health`, so it never needs admin rights.
  - `OPS_DATABASE_URL`: `postgresql://channelpulse_ops.<ref>:<OPS_DB_PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres`
  - `CORS_ORIGINS`: leave it empty for now, and fill it in after step 4.
  - `ADMIN_TOKEN`: optional, and best left empty. Set, it lets the Agent traces page list live `/api/ask` traces, which are visitors' own questions, to a request carrying it (D40). Empty, the page shows only the eval's recorded traces.
  - `ANTHROPIC_API_KEY`: the key that pays for the free questions.
    - In the Anthropic Console, create a workspace for this demo alone and set its monthly spend limit to $10. Then create the key inside that workspace. Anthropic limits spend per workspace, not per key, so this limit is the backstop behind the caps.
    - You enter it here, on Render, and nowhere else. It never goes into GitHub.
- [ ] Leave the rest as the blueprint sets them: `ASK_LIVE=1`, the caps, and `VISITOR_SALT`, which Render generates.
- [ ] Check that `https://<render-url>/health` returns `{"status":"ok","db":"ok"}`.
- [ ] Expect the free plan to sleep after about 15 idle minutes. The first request after a quiet spell can take up to a minute to wake it. The dashboard shows "The API is waking up" and re-runs the page by itself every 15 seconds (D49). Measured at the free instance's 0.1 CPU, a full page then takes about 20–25 seconds.

## 4. Vercel (dashboard)
- [ ] Add a new project from the repository, with **Root Directory** `web`. The framework is detected as Next.js; choose Node 24 if asked.
- [ ] Add the environment variable `NEXT_PUBLIC_API_URL=https://<render-url>`, then deploy.
  - This value is compiled into the browser code, so changing it later needs a redeploy.
  - Optionally, also set `CHANNELPULSE_API_URL` if the server-side calls should use a different base URL.
  - Only if you set `ADMIN_TOKEN` on Render: set the same value as `CHANNELPULSE_ADMIN_TOKEN`. It's read server-side only and never reaches the browser. Never put it in a `NEXT_PUBLIC_` variable.
- [ ] Back on Render, set `CORS_ORIGINS=https://<vercel-url>`. The Ask page calls the API from the browser, so live questions fail without it.
- [ ] If pages time out on Vercel before the API does, raise the project's function max duration. A dashboard page makes about 25 governed queries, four at a time.

## 5. Verify the deployed demo
- [ ] Run the smoke test against it from your machine:
  `SMOKE_URL=https://<vercel-url> SMOKE_API_URL=https://<render-url> SMOKE_REMOTE=1 make smoke`

  `SMOKE_REMOTE=1` skips the two checks that need a local build: the build-ID check and the fault-injection test.
- [ ] Open all six pages (the four dashboards, Weekly Brief and Agent traces) in "All regions" and one single region. The Ask page must show the ask box first, with the scored examples collapsed underneath, and never an error.
- [ ] Verify live mode:
  - `https://<render-url>/api/ask/status` shows `"mode":"live"` and a `free` object with `"remaining":5`.
  - Ask one free question on the Ask page, with no key set. It gets an answer, and the allowance line drops to 4 of 5.
  - Ask one question with your own throwaway key: make it in a separate Anthropic workspace with a $1 spend limit, and revoke it afterwards. It gets an answer, and the line reads "Asking with your key".
- [ ] The nightly refresh republishes `marts` around 00:30 IST. Queries during those few seconds can fail, and Retry fixes them.

## 6. Switching live mode off, and how the caps behave
**Off:** set `ASK_LIVE=0` on Render (and in `render.yaml`, so the two agree). `/api/ask` then answers 503 `live_off` with or without a visitor's key, and the Ask page goes back to replay, with no redeploy of the dashboard. To stop only the free questions and keep visitors' own keys working, remove `ANTHROPIC_API_KEY` instead; the page then says free questions aren't offered here.

**The caps** (D55). Every question is traced with who paid for it, and the caps count only what you paid:
- **Free questions:** 5 per visitor per UTC day (`FREE_QUESTIONS_PER_DAY`). A visitor is a salted hash of the UTC date and their IP, so the IP itself is never stored. The 6th answers 429 until 00:00 UTC, and the page offers "use your own key".
- **Your spend:** $1 since 00:00 UTC (`DAILY_SPEND_CAP_USD`) and $10 since the 1st of the month, UTC (`MONTHLY_SPEND_CAP_USD`), from each question's traced cost. Past either, free questions pause (503) until the day or the month turns. Each free question reserves $0.30 of the caps before the model is called, so questions running at the same time can't spend past them; its real cost replaces the reservation when it ends.
- **Fail closed:** if the trace table can't be read, free questions pause. Unknown spend is not an allowance. They pause too when Anthropic refuses your key over a rate, spend or credit limit.
- **Visitors' own keys** count toward neither, and keep working while free questions are paused.
- **Everyone** is under the per-IP rate limit, `ASK_RATE_PER_MIN=4`, with the client IP taken from `X-Forwarded-For` (`TRUST_PROXY=1`).
- **Known limit:** a visitor who forges `X-Forwarded-For` can get past 5 free questions, but not past the $1 daily cap.
- **Backstop:** the workspace's $10 monthly spend limit in the Anthropic Console holds whatever the caps miss.

Both paths call `claude-sonnet-5-5` unless `CHANNELPULSE_MODEL` says otherwise.
