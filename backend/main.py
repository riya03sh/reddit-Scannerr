from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from services.supabase_client import get_supabase
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
    """Verifies Supabase plus whichever post-source and LLM provider are actually
    configured via DATA_SOURCE / LLM_PROVIDER - not every integration this project
    knows how to talk to, since most setups only use one of each."""
    results = {}

    try:
        sb = get_supabase()
        sb.table("companies").select("id").limit(1).execute()
        results["supabase"] = "ok"
    except Exception as e:
        results["supabase"] = f"error: {e}"

    if settings.data_source == "reddit":
        try:
            from services.reddit_client import get_reddit
            reddit = get_reddit()
            reddit.subreddit("test").display_name  # forces a lazy request
            results["reddit"] = "ok"
        except Exception as e:
            results["reddit"] = f"error: {e}"
    else:
        results["data_source"] = f"ok ({settings.data_source}, no external call needed)"

    try:
        if settings.llm_provider == "ollama":
            import httpx
            httpx.get("http://localhost:11434/api/tags", timeout=5.0).raise_for_status()
            results["llm"] = f"ok (ollama/{settings.ollama_model})"
        elif settings.llm_provider == "groq":
            from services.groq_client import get_client
            get_client().chat.completions.create(
                model=settings.groq_model,
                messages=[{"role": "user", "content": "Say 'ok' and nothing else."}],
            )
            results["llm"] = f"ok (groq/{settings.groq_model})"
        else:
            from services.gemini_client import get_model
            get_model().generate_content("Say 'ok' and nothing else.")
            results["llm"] = "ok (gemini)"
    except Exception as e:
        results["llm"] = f"error: {e}"

    if any(str(v).startswith("error") for v in results.values()):
        raise HTTPException(status_code=500, detail=results)
    return results
