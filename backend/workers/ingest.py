"""
Phase 1-2 ingestion worker.

For every active scanner_config:
  1. Pull new posts from its configured subreddits
  2. Content mode: pre-filter by keyword before classifying (keeps API volume down
     on high-traffic subreddits). Competitor mode: no pre-filter - every post goes
     to the LLM directly, since competitor-mode configs cover fewer subreddits and
     literal keyword matching misses misspellings/indirect references.
  3. Classify surviving posts with the configured LLM provider
  4. Store post + classification result

Run manually for now: python -m workers.ingest
Later this gets wrapped in an APScheduler job (Phase 2).
"""
from datetime import datetime, timezone

from services.supabase_client import get_supabase
from services.prefilter import matches_keywords, matches_competitor_signal
from config import settings
import time

if settings.llm_provider == "ollama":
    from services.ollama_client import classify_content_mode, classify_competitor_mode
elif settings.llm_provider == "groq":
    from services.groq_client import classify_content_mode, classify_competitor_mode
else:
    from services.gemini_client import classify_content_mode, classify_competitor_mode


class DailyQuotaReached(Exception):
    """The provider's daily token allowance is gone for now."""


def _is_quota_error(exc: Exception) -> bool:
    """Free-tier daily token limits are expected operating conditions here, not
    faults: one competitor-mode pass over a few hundred posts can exhaust Groq's
    daily allowance. Every run records what it classified, so stopping cleanly
    lets the next scheduled run resume instead of crashing and re-doing work.
    Matched on the message because each provider raises its own error type."""
    text = str(exc).lower()
    return "rate_limit" in text or "rate limit" in text or "quota" in text or "429" in text

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


def _already_classified(sb, config_id: str, post_id: str) -> bool:
    """Has this config already had the LLM judge this post?

    Both modes discard negatives (no competitor named / below the score
    threshold), so neither can tell from its own output table whether a post was
    already seen and rejected. This ledger is the only record.
    """
    return bool(
        sb.table("classified_posts").select("id")
        .eq("config_id", config_id).eq("post_id", post_id).execute().data
    )


def _record_classified(sb, config_id: str, post_id: str) -> None:
    """Record the judgement immediately after it happens, whatever the verdict,
    so an interrupted run (rate limit, crash) doesn't redo work on the retry."""
    sb.table("classified_posts").upsert(
        {"config_id": config_id, "post_id": post_id},
        on_conflict="config_id,post_id",
    ).execute()


def _upsert_lead(sb, company_id: str, username: str, score) -> str:
    """Create the lead for this reddit user, or refresh an existing one.

    Shared by both modes, so someone who both complains about a competitor and
    describes the problem you solve lands on one lead carrying the higher score
    rather than appearing twice.
    """
    existing = (
        sb.table("leads").select("*")
        .eq("reddit_username", username).eq("company_id", company_id).execute()
    )
    if existing.data:
        lead = existing.data[0]
        sb.table("leads").update({
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "aggregate_score": max(lead["aggregate_score"], score),
        }).eq("id", lead["id"]).execute()
        return lead["id"]

    created = sb.table("leads").insert({
        "reddit_username": username,
        "company_id": company_id,
        "aggregate_score": score,
    }).execute()
    return created.data[0]["id"]


def run_content_mode(sb, config: dict, company: dict):
    for subreddit in config["subreddits"]:
        posts = fetch_new_posts(subreddit, limit=100)
        for post in posts:
            if not matches_keywords(post["title"], post["body"], config["keywords"]):
                continue

            post_id = _upsert_post(sb, post)

            # Skip anything this config has already had judged. Checking
            # content_matches instead would only skip posts that scored above the
            # threshold - every rejected post would come back to the LLM on every
            # run, forever.
            if _already_classified(sb, config["id"], post_id):
                continue

            try:
                result = classify_content_mode(
                    business_context=company["product_description"] or "",
                    keywords=config["keywords"],
                    title=post["title"],
                    body=post["body"],
                )
            except Exception as e:
                if _is_quota_error(e):
                    raise DailyQuotaReached(str(e)) from e
                raise
            time.sleep(settings.llm_request_interval_seconds)
            _record_classified(sb, config["id"], post_id)

            score = result["intent_score"]
            if score / 100 >= config["min_score_threshold"]:
                sb.table("content_matches").insert({
                    "post_id": post_id,
                    "config_id": config["id"],
                    "intent_score": score,
                    "ai_reasoning": result["reasoning"],
                }).execute()
                print(f"[content] matched: r/{subreddit} '{post['title'][:60]}' score={score}")

                # A strong content match is a person with a problem you solve and a
                # username you can reach - the same thing competitor mode calls a
                # lead, so promote it into the lead list too.
                if score >= settings.lead_score_threshold and post["author_username"]:
                    lead_id = _upsert_lead(sb, company["id"], post["author_username"], score)
                    sb.table("lead_signals").upsert({
                        "lead_id": lead_id,
                        "post_id": post_id,
                        "source": "content",
                        "intent_score": score,
                        "ai_reasoning": result["reasoning"],
                    }, on_conflict="lead_id,post_id,source").execute()
                    print(f"[content] -> lead: u/{post['author_username']} score={score}")


def run_competitor_mode(sb, config: dict, company: dict):
    # Pre-filtered on competitor names OR switching language (see
    # prefilter.matches_competitor_signal). Sending every post to the LLM - the
    # original design - burned the entire Groq free-tier daily token budget in a
    # single 200-post run on the 70B model.
    for subreddit in config["subreddits"]:
        posts = fetch_new_posts(subreddit, limit=100)
        for post in posts:
            if not post["author_username"]:
                continue  # can't attribute a lead without a username

            if not matches_competitor_signal(post["title"], post["body"], config["competitors"]):
                continue

            post_id = _upsert_post(sb, post)
            if _already_classified(sb, config["id"], post_id):
                continue

            try:
                result = classify_competitor_mode(
                    company_name=company["name"],
                    product_description=company["product_description"] or "",
                    competitors=config["competitors"],
                    title=post["title"],
                    body=post["body"],
                )
            except Exception as e:
                if _is_quota_error(e):
                    raise DailyQuotaReached(str(e)) from e
                raise
            time.sleep(settings.llm_request_interval_seconds)

            _record_classified(sb, config["id"], post_id)

            if not result["competitor_mentioned"]:
                continue  # no competitor signal in this post - don't bother storing it

            lead_id = _upsert_lead(sb, company["id"], post["author_username"], result["score"])

            sb.table("lead_signals").upsert({
                "lead_id": lead_id,
                "post_id": post_id,
                "source": "competitor",
                "competitor_mentioned": result["competitor_mentioned"],
                "pain_point": result["pain_point"],
                "switch_intent": result["switch_intent"],
                "ai_reasoning": result["reasoning"],
            }, on_conflict="lead_id,post_id,source").execute()
            print(f"[competitor] lead signal: u/{post['author_username']} re: {result['competitor_mentioned']}")


def run_all():
    sb = get_supabase()
    configs = sb.table("scanner_configs").select("*").eq("is_active", True).execute().data

    for config in configs:
        company = sb.table("companies").select("*").eq("id", config["company_id"]).single().execute().data
        try:
            if config["mode"] == "content":
                run_content_mode(sb, config, company)
            elif config["mode"] == "competitor":
                run_competitor_mode(sb, config, company)
        except DailyQuotaReached as e:
            # Everything classified so far is already saved, so the next scheduled
            # run picks up where this one stopped. Stop the whole run rather than
            # continue to the next config - the quota is account-wide.
            print(f"[quota] daily LLM allowance reached, stopping early: {e}")
            return


if __name__ == "__main__":
    run_all()
