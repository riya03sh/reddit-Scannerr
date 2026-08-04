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


# Dropped when matching a multi-word keyword. Someone tracking "ga4 not tracking"
# means the concepts, not that exact string with "not" in that position.
_FILLER_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "for", "from", "in", "is", "it",
    "my", "not", "of", "on", "or", "our", "the", "to", "with", "your",
}


def _contains_word(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _matches_term(text: str, term: str) -> bool:
    """A single keyword against the post text.

    Single words match on a word boundary. Multi-word keywords match when all
    their significant words appear somewhere in the post - NOT as a literal
    phrase. People type keywords as descriptions of a problem ("meta pixel
    broken", "wasted ad spend"), but nobody writes that exact string; they write
    "my meta pixel stopped working". Requiring the literal phrase silently
    matched zero posts out of 800 on a real scanner - the scanner looked
    configured and active while never producing anything.
    """
    words = term.split()
    if len(words) == 1:
        return _contains_word(text, words[0])

    significant = [w for w in words if w not in _FILLER_WORDS] or words
    return all(_contains_word(text, w) for w in significant)


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(_matches_term(text, t.lower()) for t in terms)


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
