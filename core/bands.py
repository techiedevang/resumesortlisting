"""
bands.py
--------
Turns a score into a suggested decision. The recruiter can change the two
thresholds per job and can override any single candidate; nothing is sent to a
candidate until a recruiter approves it.
"""

SELECTED = "selected"
REVIEW = "review"
REJECTED = "rejected"
STATUSES = (SELECTED, REVIEW, REJECTED)

DEFAULT_SELECT_AT = 80.0
DEFAULT_REVIEW_AT = 60.0

# Wording for the recruiter, and for the candidate-facing page and emails.
RECRUITER_LABEL = {SELECTED: "Selected", REVIEW: "Under review", REJECTED: "Rejected"}
CANDIDATE_LABEL = {
    SELECTED: "Selected for the next round",
    REVIEW: "Profile under review",
    REJECTED: "Not selected for this role",
}


def decide(score: float, select_at: float = DEFAULT_SELECT_AT,
           review_at: float = DEFAULT_REVIEW_AT) -> str:
    """At or above `select_at`: selected. From `review_at` up to it: under review."""
    if score >= select_at:
        return SELECTED
    if score >= review_at:
        return REVIEW
    return REJECTED


def validate_thresholds(select_at, review_at):
    """Return an error message, or None when the pair is valid."""
    try:
        select_at, review_at = float(select_at), float(review_at)
    except (TypeError, ValueError):
        return "Thresholds must be numbers."
    if not (0 < review_at < select_at <= 100):
        return "Thresholds must satisfy 0 < review < selected <= 100."
    return None
