import re

# Language that signals someone weighing one product against another, even when
# they never name a competitor ("looking for an alternative", "quality has gone
# downhill"). Paired with the configured competitor names in
# matches_competitor_signal, this is what keeps competitor mode affordable.
SWITCH_TERMS = [
    "alternative", "alternatives", "instead of", "switch", "switching", "switched",
    "replace", "replacing", "replacement", "vs", "versus", "compared to", "comparison",
    "better than", "moving from", "move away from", "used to buy", "used to use",
    "disappointed", "quality dropped", "quality has dropped", "gone downhill",
    "not worth it anymore", "cancel", "cancelled my", "looking to leave",
]


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(t.lower())}\b", text) for t in terms)


def matches_keywords(title: str, body: str, keywords: list[str]) -> bool:
    """Cheap pre-filter: does this post contain any tracked keyword?
    Runs before any LLM call to cut API usage on irrelevant posts."""
    if not keywords:
        return True  # no keyword filter configured -> let everything through to AI stage
    text = f"{title} {body}".lower()
    return _contains_any(text, keywords)


def matches_competitor_signal(title: str, body: str, competitors: list[str]) -> bool:
    """Pre-filter for competitor mode: keep a post only if it names a tracked
    competitor or uses switching/comparison language.

    Competitor mode originally sent every post straight to the LLM, on the theory
    that its narrower subreddit coverage could absorb the volume. In practice it
    couldn't: a single 200-post run on the 70B model exhausted the whole Groq
    free-tier daily token budget. This keeps the indirect-mention cases that
    motivated the no-filter design (a post can still qualify on switch language
    alone, without naming anyone) while dropping the ~96% of posts that carry no
    competitor signal at all.
    """
    if not competitors:
        return True  # nothing configured to compare against -> don't filter
    text = f"{title} {body}".lower()
    return _contains_any(text, competitors) or _contains_any(text, SWITCH_TERMS)
