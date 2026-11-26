"""
profiler.py
-----------
Job-independent resume analysis. Given only a resume, it answers:

1. Which role does this person fit best?  (role-fit percentages)
2. Which skills are their real strengths? (skill priority)

Role fit
========
Each role in ROLE_PROFILES is a weighted set of skills. A resume's score for
a role is the sum, over the skills it mentions, of

    weight(skill, role) * repeat_factor(mentions)

where repeat_factor rises from 1.0 (one mention) to 2.0 (five or more), so a
skill that the candidate actually used across projects counts for more than
one that sits once in a skills list. Scores are then normalised to
percentages that sum to 100.

Skill priority
==============
Skills are ranked by how many times the resume mentions them. Relative to the
most-mentioned skill, each one is labelled:

    Primary    mentioned at least 60% as often as the top skill
    Secondary  at least 30%
    Mentioned  anything less

This separates "built three projects in Java" from "listed Java once".
"""

from .scorer import count_skill_mentions
from .skills_db import ROLE_PROFILES

PRIMARY_RATIO = 0.60
SECONDARY_RATIO = 0.30
MIN_ROLE_EVIDENCE = 3.0  # below this total score, the resume is "Unclassified"


def _repeat_factor(mentions: int) -> float:
    return 1.0 + 0.25 * (min(mentions, 5) - 1)


def skill_priority(mention_counts: dict) -> list:
    """Return skills ranked by mentions, each labelled Primary/Secondary/Mentioned."""
    if not mention_counts:
        return []
    top = max(mention_counts.values())
    ranked = sorted(mention_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    result = []
    for skill, n in ranked:
        ratio = n / top
        if ratio >= PRIMARY_RATIO:
            level = "Primary"
        elif ratio >= SECONDARY_RATIO:
            level = "Secondary"
        else:
            level = "Mentioned"
        result.append({"skill": skill, "mentions": n, "level": level})
    return result


def role_fit(mention_counts: dict) -> list:
    """Return [{'role', 'percent'}] sorted high to low, percentages summing to 100."""
    raw = {}
    for role, weights in ROLE_PROFILES.items():
        raw[role] = sum(
            weights[s] * _repeat_factor(n)
            for s, n in mention_counts.items() if s in weights
        )
    total = sum(raw.values())
    if total < MIN_ROLE_EVIDENCE:
        return []
    fits = [{"role": r, "percent": round(v / total * 100, 1)} for r, v in raw.items() if v > 0]
    return sorted(fits, key=lambda f: -f["percent"])


def analyze_resume(resume_text: str) -> dict:
    """Full job-independent profile of one resume."""
    counts = count_skill_mentions(resume_text)
    fits = role_fit(counts)
    priority = skill_priority(counts)

    if fits:
        best = fits[0]
        runner_up = fits[1]["percent"] if len(fits) > 1 else 0.0
        margin = best["percent"] - runner_up
        # A narrow lead means a mixed profile: say so rather than overclaim.
        confidence = "High" if margin >= 25 else "Medium" if margin >= 10 else "Low"
        best_role = best["role"]
    else:
        best_role, confidence = "Unclassified", "None"

    return {
        "best_role": best_role,
        "confidence": confidence,
        "role_fit": fits,
        "skill_priority": priority,
    }
