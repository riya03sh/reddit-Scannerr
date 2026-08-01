import re


def matches_keywords(title: str, body: str, keywords: list[str]) -> bool:
    """Cheap pre-filter: does this post contain any tracked keyword?
    Runs before any Gemini call to cut API usage on irrelevant posts."""
    if not keywords:
        return True  # no keyword filter configured -> let everything through to AI stage
    text = f"{title} {body}".lower()
    return any(re.search(rf"\b{re.escape(kw.lower())}\b", text) for kw in keywords)
