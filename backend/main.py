from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from services.supabase_client import get_supabase
from services.reddit_client import get_reddit
from services.gemini_client import get_model
from routes.api import router as api_router

app = FastAPI(title="Reddit Scanner API")

# Dashboard is a standalone static HTML file (opened via file:// or served from any
# port), so origin is unpredictable - wide open CORS is fine for this internal tool.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# Serve the UI from the same origin as the API, so onboarding and the dashboard
# share a localStorage session (file:// pages each get their own opaque origin,
# which is why the old dashboard made you paste the access token in by hand).
UI_DIR = Path(__file__).resolve().parent / "ui"
app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")


@app.get("/")
def root():
    return RedirectResponse(url="/ui/onboarding.html")


@app.get("/status")
def status():
    return {"status": "ok", "service": "reddit-scanner-backend"}


@app.get("/health")
def health():
    """Verifies all three external connections are reachable with current credentials.
    Run this right after Phase 0 setup to confirm .env is wired correctly."""
    results = {}

    try:
        sb = get_supabase()
        sb.table("companies").select("id").limit(1).execute()
        results["supabase"] = "ok"
    except Exception as e:
        results["supabase"] = f"error: {e}"

    try:
        reddit = get_reddit()
        reddit.subreddit("test").display_name  # forces a lazy request
        results["reddit"] = "ok"
    except Exception as e:
        results["reddit"] = f"error: {e}"

    try:
        model = get_model()
        model.generate_content("Say 'ok' and nothing else.")
        results["gemini"] = "ok"
    except Exception as e:
        results["gemini"] = f"error: {e}"

    if any("error" in v for v in results.values()):
        raise HTTPException(status_code=500, detail=results)
    return results
