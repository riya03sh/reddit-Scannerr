"""
Arctic Shift (https://arctic-shift.photon-reddit.com) provides free, no-auth
access to archived Reddit posts. Useful stand-in while the official Reddit
Data API application is pending approval.

Returns the same shape as services.reddit_client.fetch_new_posts, so the
ingestion worker doesn't need to know which source it's using.

Note: this is historical/archived data, not live - fine for testing the
pre-filter -> Gemini -> Supabase pipeline and building the dashboard against
real post content, but swap back to reddit_client once official access lands.
"""
import httpx

BASE_URL = "https://arctic-shift.photon-reddit.com"


def fetch_new_posts(subreddit_name: str, limit: int = 25):
    """Fetch recent-ish archived posts from a subreddit via Arctic Shift.
    No API key required."""
    params = {
        "subreddit": subreddit_name,
        "limit": min(limit, 100),  # Arctic Shift caps at 100 per request
        "sort": "desc",  # most recent first
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{BASE_URL}/api/posts/search", params=params)
        response.raise_for_status()
        data = response.json()

    posts = []
    for item in data.get("data", []):
        posts.append({
            "reddit_id": item["id"],
            "subreddit": subreddit_name,
            "author_username": item.get("author"),
            "title": item.get("title", ""),
            "body": item.get("selftext", "") or "",
            "url": f"https://reddit.com/r/{subreddit_name}/comments/{item['id']}",
            "created_at": item["created_utc"],
        })
    return posts