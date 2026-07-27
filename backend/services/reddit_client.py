from functools import lru_cache
import praw
from config import settings


@lru_cache
def get_reddit() -> praw.Reddit:
    return praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
    )


def fetch_new_posts(subreddit_name: str, limit: int = 25):
    """Fetch the most recent posts from a subreddit. Read-only, no auth beyond app creds needed."""
    reddit = get_reddit()
    subreddit = reddit.subreddit(subreddit_name)
    posts = []
    for submission in subreddit.new(limit=limit):
        posts.append({
            "reddit_id": submission.id,
            "subreddit": subreddit_name,
            "author_username": str(submission.author) if submission.author else None,
            "title": submission.title,
            "body": submission.selftext,
            "url": f"https://reddit.com{submission.permalink}",
            "created_at": submission.created_utc,
        })
    return posts
