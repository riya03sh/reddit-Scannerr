"""
Supabase Auth verification for the customer-facing API.

Every protected route depends on get_current_user, which validates the bearer
token against Supabase Auth (a real network round-trip - no local JWT-secret
verification, so no extra dependency to manage) and returns the caller's
{"id", "email"}. Company ownership is always resolved server-side from
companies.user_id starting from that id - callers never get to assert their
own company_id, so one user can never read or write another company's data.
"""
from fastapi import Header, HTTPException

from services.supabase_client import get_supabase


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()

    sb = get_supabase()
    try:
        response = sb.auth.get_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid or expired token")

    if not response or not response.user:
        raise HTTPException(status_code=401, detail="invalid or expired token")

    return {"id": response.user.id, "email": response.user.email}


def get_owned_company(sb, user_id: str) -> dict:
    """The signed-in user's own company row, or 404 if they haven't onboarded yet."""
    result = sb.table("companies").select("*").eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="no company found for this account - create one first")
    return result.data[0]


def ensure_owns_company(sb, company_id: str, user_id: str) -> None:
    result = sb.table("companies").select("id").eq("id", company_id).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=403, detail="not authorized for this company")
