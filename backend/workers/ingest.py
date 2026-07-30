"""
Phase 1-2 ingestion worker.

For every active scanner_config:
  1. Pull new posts from its configured subreddits
  2. Pre-filter by keyword (content mode) or competitor mention (competitor mode)
  3. Classify surviving posts with Gemini
  4. Store post + classification result

Run manually for now: python -m workers.ingest
Later this gets wrapped in an APScheduler job (Phase 2).
"""
from datetime import datetime, timezone

from services.supabase_client import get_supabase
from services.prefilter import matches_keywords, matches_competitors
from config import settings
import time

if settings.llm_provider == "ollama":
    from services.ollama_client import classify_content_mode, classify_competitor_mode
elif settings.llm_provider == "groq":
    from services.groq_client import classify_content_mode, classify_competitor_mode
else:
    from services.gemini_client import classify_content_mode, classify_competitor_mode

def _get_fetch_function():
    """Selects the post-fetching backend based on config.data_source.
    Swap this one setting once Reddit API approval comes through - no other
    code in this file needs to change."""
    if settings.data_source == "reddit":
        from services.reddit_client import fetch_new_posts
    elif settings.data_source == "arctic_shift":
        from services.arctic_shift_client import fetch_new_posts
    else:
        from services.mock_client import fetch_new_posts
    return fetch_new_posts


fetch_new_posts = _get_fetch_function()
def _upsert_post(sb, post: dict) -> str:
    """Insert post if new, return its Supabase row id (post_id)."""
    existing = sb.table("posts").select("id").eq("reddit_id", post["reddit_id"]).execute()
    if existing.data:
        return existing.data[0]["id"]

    row = {
        "reddit_id": post["reddit_id"],
        "subreddit": post["subreddit"],
        "author_username": post["author_username"],
        "title": post["title"],
        "body": post["body"],
        "url": post["url"],
        "created_at": datetime.fromtimestamp(post["created_at"], tz=timezone.utc).isoformat(),
    }
    result = sb.table("posts").insert(row).execute()
    return result.data[0]["id"]


def run_content_mode(sb, config: dict, company: dict):
    for subreddit in config["subreddits"]:
        posts = fetch_new_posts(subreddit, limit=100)
        for post in posts:
            if not matches_keywords(post["title"], post["body"], config["keywords"]):
                continue

            post_id = _upsert_post(sb, post)

            # skip if already classified for this config
            already = sb.table("content_matches").select("id").eq("post_id", post_id).eq("config_id", config["id"]).execute()
            if already.data:
                continue

            result = classify_content_mode(
                business_context=company["product_description"] or "",
                keywords=config["keywords"],
                title=post["title"],
                body=post["body"],
            )
            time.sleep(4)
            if result["intent_score"] / 100 >= config["min_score_threshold"]:
                sb.table("content_matches").insert({
                    "post_id": post_id,
                    "config_id": config["id"],
                    "intent_score": result["intent_score"],
                    "ai_reasoning": result["reasoning"],
                }).execute()
                print(f"[content] matched: r/{subreddit} '{post['title'][:60]}' score={result['intent_score']}")


def run_competitor_mode(sb, config: dict, company: dict):
    for subreddit in config["subreddits"]:
        posts = fetch_new_posts(subreddit, limit=100)
        for post in posts:
            if not matches_competitors(post["title"], post["body"], config["competitors"]):
                continue
            if not post["author_username"]:
                continue  # can't attribute a lead without a username

            post_id = _upsert_post(sb, post)

            result = classify_competitor_mode(
                company_name=company["name"],
                product_description=company["product_description"] or "",
                competitors=config["competitors"],
                title=post["title"],
                body=post["body"],
            )
            time.sleep(4)
            
            if not result["competitor_mentioned"]:
                continue  # Gemini decided it wasn't actually relevant despite keyword match

            # upsert lead
            existing_lead = sb.table("leads").select("*").eq("reddit_username", post["author_username"]).eq("company_id", company["id"]).execute()
            if existing_lead.data:
                lead = existing_lead.data[0]
                new_score = max(lead["aggregate_score"], result["score"])  # simple strategy; refine later
                sb.table("leads").update({
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "aggregate_score": new_score,
                }).eq("id", lead["id"]).execute()
                lead_id = lead["id"]
            else:
                created = sb.table("leads").insert({
                    "reddit_username": post["author_username"],
                    "company_id": company["id"],
                    "aggregate_score": result["score"],
                }).execute()
                lead_id = created.data[0]["id"]

            sb.table("lead_signals").insert({
                "lead_id": lead_id,
                "post_id": post_id,
                "competitor_mentioned": result["competitor_mentioned"],
                "pain_point": result["pain_point"],
                "switch_intent": result["switch_intent"],
                "ai_reasoning": result["reasoning"],
            }).execute()
            print(f"[competitor] lead signal: u/{post['author_username']} re: {result['competitor_mentioned']}")


def run_all():
    sb = get_supabase()
    configs = sb.table("scanner_configs").select("*").eq("is_active", True).execute().data

    for config in configs:
        company = sb.table("companies").select("*").eq("id", config["company_id"]).single().execute().data
        if config["mode"] == "content":
            run_content_mode(sb, config, company)
        elif config["mode"] == "competitor":
            run_competitor_mode(sb, config, company)


if __name__ == "__main__":
    run_all()
