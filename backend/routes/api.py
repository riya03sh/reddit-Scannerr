"""
Customer-facing + dashboard REST API.

Thin read/write layer over the Supabase tables in schema.sql - no separate
service layer, matching the directness of workers/ingest.py. Mounted in
main.py under /api.

Every route here is auth-protected (get_current_user validates the Supabase
access token). Company-scoped routes still take company_id as a query param
(so the existing dashboard/index.html company-selector UX keeps working
unchanged) but always verify the caller owns that company_id before touching
any data - a valid token for company A can never read or write company B.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from services.auth import get_current_user, get_owned_company, ensure_owns_company
from services.supabase_client import get_supabase

router = APIRouter(prefix="/api")

VALID_LEAD_STATUSES = {"new", "reviewed", "contacted", "dismissed"}
VALID_SCANNER_MODES = {"content", "competitor"}


def _ensure_owns_lead(sb, lead_id: str, user_id: str) -> dict:
    result = sb.table("leads").select("*").eq("id", lead_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="lead not found")
    lead = result.data[0]
    ensure_owns_company(sb, lead["company_id"], user_id)
    return lead


@router.get("/companies")
def list_companies(user: dict = Depends(get_current_user)):
    """The signed-in user's own company (empty list if they haven't onboarded yet)."""
    sb = get_supabase()
    return sb.table("companies").select("id, name").eq("user_id", user["id"]).order("name").execute().data


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1)
    product_description: str | None = None


@router.post("/companies")
def create_company(body: CompanyCreate, user: dict = Depends(get_current_user)):
    sb = get_supabase()
    existing = sb.table("companies").select("id").eq("user_id", user["id"]).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="this account already has a company")

    result = sb.table("companies").insert({
        "name": body.name.strip(),
        "product_description": body.product_description,
        "user_id": user["id"],
    }).execute()
    return result.data[0]


class ScannerConfigCreate(BaseModel):
    mode: str
    subreddits: list[str]
    keywords: list[str] = []
    competitors: list[str] = []
    min_score_threshold: float = 0.6


@router.post("/scanner-configs")
def create_scanner_config(body: ScannerConfigCreate, user: dict = Depends(get_current_user)):
    sb = get_supabase()
    company = get_owned_company(sb, user["id"])

    if body.mode not in VALID_SCANNER_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {sorted(VALID_SCANNER_MODES)}")

    subreddits = [s.strip() for s in body.subreddits if s.strip()]
    if not subreddits:
        raise HTTPException(status_code=422, detail="subreddits must contain at least one non-empty entry")

    keywords = [k.strip() for k in body.keywords if k.strip()]
    competitors = [c.strip() for c in body.competitors if c.strip()]
    if body.mode == "content" and not keywords:
        raise HTTPException(status_code=422, detail="content mode requires at least one keyword")
    if body.mode == "competitor" and not competitors:
        raise HTTPException(status_code=422, detail="competitor mode requires at least one competitor")

    if not (0 <= body.min_score_threshold <= 1):
        raise HTTPException(status_code=422, detail="min_score_threshold must be between 0 and 1")

    result = sb.table("scanner_configs").insert({
        "company_id": company["id"],
        "mode": body.mode,
        "subreddits": subreddits,
        "keywords": keywords,
        "competitors": competitors,
        "min_score_threshold": body.min_score_threshold,
    }).execute()
    return result.data[0]


class SuggestRequest(BaseModel):
    url: str = Field(min_length=4)


@router.post("/suggest")
def suggest_scanner(body: SuggestRequest, user: dict = Depends(get_current_user)):
    """Read a product's website and propose a scanner setup for it.

    Suggestions are checked against live Reddit before being returned - dead or
    misspelled subreddits are dropped, and the keywords come back with the
    fraction of real posts they actually select, so a useless set is visible
    before it's saved rather than after a week of empty results.
    """
    from services.suggest import suggest_from_url, SuggestionError

    try:
        return suggest_from_url(body.url.strip())
    except SuggestionError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/scanner-configs")
def list_scanner_configs(company_id: str, user: dict = Depends(get_current_user)):
    """A company's scanner configs, most recently created first."""
    sb = get_supabase()
    ensure_owns_company(sb, company_id, user["id"])

    return (
        sb.table("scanner_configs")
        .select("*")
        .eq("company_id", company_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )


@router.get("/matches")
def list_matches(company_id: str, user: dict = Depends(get_current_user)):
    """Content-mode matches for a company, most recent first, with the source post embedded."""
    sb = get_supabase()
    ensure_owns_company(sb, company_id, user["id"])

    configs = (
        sb.table("scanner_configs")
        .select("id")
        .eq("company_id", company_id)
        .eq("mode", "content")
        .execute()
        .data
    )
    config_ids = [c["id"] for c in configs]
    if not config_ids:
        return []

    return (
        sb.table("content_matches")
        .select("*, posts(*)")
        .in_("config_id", config_ids)
        .order("created_at", desc=True)
        .execute()
        .data
    )


@router.get("/leads")
def list_leads(company_id: str, user: dict = Depends(get_current_user)):
    """Competitor-mode leads for a company, most recently active first."""
    sb = get_supabase()
    ensure_owns_company(sb, company_id, user["id"])

    return (
        sb.table("leads")
        .select("*")
        .eq("company_id", company_id)
        .order("last_seen", desc=True)
        .execute()
        .data
    )


@router.get("/leads/{lead_id}/signals")
def list_lead_signals(lead_id: str, user: dict = Depends(get_current_user)):
    """All competitor-mention signals that rolled up into this lead, with the source post embedded."""
    sb = get_supabase()
    _ensure_owns_lead(sb, lead_id, user["id"])

    return (
        sb.table("lead_signals")
        .select("*, posts(*)")
        .eq("lead_id", lead_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )


@router.patch("/leads/{lead_id}/status")
def update_lead_status(lead_id: str, status: str, user: dict = Depends(get_current_user)):
    if status not in VALID_LEAD_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(VALID_LEAD_STATUSES)}")

    sb = get_supabase()
    _ensure_owns_lead(sb, lead_id, user["id"])

    result = sb.table("leads").update({"status": status}).eq("id", lead_id).execute()
    return result.data[0]
