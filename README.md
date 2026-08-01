# Reddit Scanner

Finds Reddit posts worth replying to. Two modes:

- **Content mode** — scores posts for genuine buying intent against your product description.
- **Competitor mode** — spots people complaining about a named competitor and rolls them into leads.

FastAPI + Supabase backend, LLM classification via Gemini or Groq, and a static UI
built on the Modernist design system.

## Setup

1. `cd backend && pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in:
   - Reddit app creds from https://www.reddit.com/prefs/apps (create a "script" app)
   - Gemini API key from https://aistudio.google.com/apikey, or a Groq key
   - Supabase URL + service role key from Project Settings → API
3. Run `schema.sql` in the Supabase SQL editor to create the tables.
4. `uvicorn main:app --reload`
5. Open http://127.0.0.1:8000 — it redirects to onboarding.

`GET /health` verifies the Supabase, Reddit and LLM connections against your `.env`.

## Using it

Onboarding (`/ui/onboarding.html`) walks through three steps: create an account,
describe your company, add a scanner. Signing in stores the Supabase session in
`localStorage`, and the dashboard picks it up from there — same origin, so there's
no token to copy across.

Then run the ingestion worker to populate the dashboard:

```
cd backend && python -m workers.ingest
```

It polls each active scanner's subreddits, pre-filters by keyword (content mode only),
classifies with the configured LLM, and writes matches to `content_matches` /
leads to `leads` + `lead_signals`.

Results land in the dashboard (`/ui/dashboard.html`): content matches as scored
cards, competitor leads as a table with expandable per-signal detail and status
tracking (new → reviewed → contacted → dismissed).

## Configuration

Set in `.env`:

| Variable | Values | Notes |
| --- | --- | --- |
| `DATA_SOURCE` | `mock`, `arctic_shift`, `reddit` | `mock` needs no credentials; `arctic_shift` is free archived data with no auth, useful while Reddit API approval is pending |
| `LLM_PROVIDER` | `gemini`, `groq`, `ollama` | Groq's free tier is 30 req/min; `ollama` runs fully local against `ollama serve` |
| `GROQ_MODEL` | | Content mode — small and fast is fine |
| `GROQ_COMPETITOR_MODEL` | | Competitor mode gets a bigger model: no keyword pre-filter means more borderline posts, and small models hallucinate competitor mentions |
| `OLLAMA_MODEL` | | Only used when `LLM_PROVIDER=ollama` |

Only the API key for whichever `LLM_PROVIDER` you pick is required — `GEMINI_API_KEY` is optional when running on Groq or Ollama.

## Structure

```
backend/
  main.py                       # FastAPI app, /health, serves the UI under /ui
  config.py                     # env-based settings
  schema.sql                    # run this in the Supabase SQL editor
  routes/api.py                 # auth-protected REST API
  services/
    supabase_client.py
    auth.py                     # Supabase token verification + ownership checks
    reddit_client.py            # live Reddit via PRAW
    arctic_shift_client.py      # free archived posts, no auth
    mock_client.py              # hardcoded samples, zero dependencies
    gemini_client.py            # prompts for both modes live here
    groq_client.py              # same interface, reuses the Gemini prompts
    ollama_client.py            # same interface, local model via `ollama serve`
    prefilter.py                # keyword pre-filter
  workers/ingest.py             # the core loop; run manually for now
  ui/
    styles.css                  # Modernist design system (vendored, do not edit)
    app.css                     # app-layer patterns, built from DS tokens only
    app.js                      # shared session + API layer
    onboarding.html
    dashboard.html
```

## UI

`ui/styles.css` is the Modernist design system, vendored verbatim from the Claude
Design project. Treat it as read-only: it's the source of truth for color, type,
spacing and the component classes. Anything the system doesn't ship goes in
`app.css`, built from its tokens (`var(--color-*)`, `var(--space-*)`, …) — no raw
hex, no rounded corners, flush-left labels, 2px rules between sections.

Both pages are plain HTML with no build step.

## Not built yet

- Scheduling — `apscheduler` is a dependency but ingestion is still manual-only
- Digest delivery — `content_matches.sent_in_digest` is written by nothing
- Scanner editing — the API can create and list configs but not edit or delete
  them, and `is_active` can never be toggled
- Plan tiers — `companies.plan_tier` is never enforced
- Tests, CI, deploy config
