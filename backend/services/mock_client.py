"""Hardcoded sample posts for testing the pipeline with zero external dependencies."""

_SAMPLE_POSTS = [
    {
        "reddit_id": "mock001",
        "subreddit": "productivity",
        "author_username": "throwaway_pm_2024",
        "title": "Looking for a better way to manage my team's tasks, Asana is too clunky",
        "body": "We've been using Asana for 6 months and honestly it's become a mess. Too many clicks to do simple things. Anyone found a lighter alternative that still handles dependencies well?",
        "url": "https://reddit.com/r/productivity/comments/mock001",
        "created_at": 1721990400,
    },
    {
        "reddit_id": "mock002",
        "subreddit": "SaaS",
        "author_username": "indie_hacker_99",
        "title": "What's your favorite productivity app for a 3-person startup?",
        "body": "Just me and two cofounders, need something simple for task tracking and maybe light CRM. Budget conscious.",
        "url": "https://reddit.com/r/SaaS/comments/mock002",
        "created_at": 1721994000,
    },
    {
        "reddit_id": "mock003",
        "subreddit": "productivity",
        "author_username": "random_user_44",
        "title": "What did you have for breakfast today",
        "body": "Just curious what everyone eats before work",
        "url": "https://reddit.com/r/productivity/comments/mock003",
        "created_at": 1721997600,
    },
]


def fetch_new_posts(subreddit_name: str, limit: int = 25):
    return [p for p in _SAMPLE_POSTS if p["subreddit"] == subreddit_name][:limit]
