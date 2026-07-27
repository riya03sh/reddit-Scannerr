# Reddit Scanner — Backend

Phase 0 scaffolding: FastAPI app + Supabase schema + Reddit/Gemini client wrappers.

## Setup

1. `cd backend && pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in:
   - Reddit app creds from https://www.reddit.com/prefs/apps (create a "script" app)
   - Gemini API key from https://aistudio.google.com/apikey
   - Supabase URL + service role key from Project Settings -> API
3. Run `schema.sql` in the Supabase SQL editor to create tables.
4. `uvicorn main:app --reload`
5. Hit `GET /health` to confirm all three connections work.

## Manual ingestion test (Phase 1-2)

Once you've inserted a test `companies` row and a `scanner_configs` row (mode='content')
via the Supabase table editor:

```
python -m workers.ingest
```

This polls the configured subreddits, pre-filters by keyword, classifies with Gemini,
and writes matches to `content_matches`. Check the table in Supabase to confirm.

## Structure

```
backend/
  main.py                 # FastAPI app + /health check
  config.py                # env-based settings
  schema.sql                # run this in Supabase SQL editor
  services/
    supabase_client.py
    reddit_client.py
    gemini_client.py       # prompts for both modes live here
    prefilter.py            # keyword/competitor pre-filter
  workers/
    ingest.py               # Phase 1-2 core loop, run manually for now
```
