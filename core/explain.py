"""
explain.py
----------
A short plain-language summary of why a candidate scored as they did.

Two sources:

* rules (default): written from the scoring evidence by fixed templates. Works
  offline, free, and always matches the numbers shown.
* llm: if ANTHROPIC_API_KEY is set, the same evidence is sent to Claude to be
  phrased more naturally. Only scores, skill names and flags are sent; the
  candidate's name, email and resume text are not. If the call fails or the
  reply looks wrong, the rules summary is used instead.

Neither source changes the score or the decision. The summary only describes.
"""

import json
import logging
import os
import urllib.request

logger = logging.getLogger("resume_screening.explain")

API_URL = "https://api.anthropic.com/v1/messages"
MAX_SUMMARY_CHARS = 700
_cache = {}


def _join(items) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def facts(candidate: dict, job_title: str) -> dict:
    """The only data the summary is allowed to use."""
    ev = candidate.get("evidence", {})
    return {
        "role": job_title,
        "score": round(candidate["final_score"]),
        "decision": candidate["status"],
        "rank": candidate.get("rank"),
        "of": candidate.get("job_candidate_count"),
        "skills_shown_in_work": ev.get("proven_skills", []),
        "skills_only_listed": ev.get("listed_skills", []),
        "skills_missing": candidate["missing_skills"],
        "depth_score": round(candidate.get("depth_score", 0)),
        "flags": [f["label"] for f in candidate.get("flags", [])],
    }


def rules_summary(f: dict) -> str:
    label = {"selected": "meets the bar for the next round",
             "review": "falls in the review band",
             "rejected": "is below the review band"}[f["decision"]]
    parts = [f"Scores {f['score']} for {f['role']}, which {label}."]
    if f["skills_shown_in_work"]:
        parts.append(f"Skills backed by project or job work: {_join(f['skills_shown_in_work'])}.")
    if f["skills_only_listed"]:
        parts.append(f"Listed without a project that shows them: {_join(f['skills_only_listed'])}.")
    if f["skills_missing"]:
        parts.append(f"Not found on the resume: {_join(f['skills_missing'])}.")
    if not f["skills_shown_in_work"] and not f["skills_only_listed"]:
        parts.append("None of the required skills were found.")
    if f["depth_score"] >= 70:
        parts.append("The resume describes its work in detail.")
    elif f["depth_score"] < 35:
        parts.append("The resume describes little concrete work.")
    for flag in f["flags"]:
        parts.append(f"Note: {flag}.")
    return " ".join(parts)


PROMPT = (
    "You help a recruiter read a resume-screening result. Using ONLY the JSON facts below, "
    "write 2 to 4 plain sentences describing the candidate's strengths and gaps for the role. "
    "Mention every flag. Do not add skills, experience, opinions about the person, or any "
    "hiring recommendation, and do not change the decision. Facts:\n"
)


def _ask_llm(f: dict) -> str:
    body = json.dumps({
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        "max_tokens": 300,
        "messages": [{"role": "user", "content": PROMPT + json.dumps(f)}],
    }).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "content-type": "application/json",
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


def _acceptable(text: str, f: dict) -> bool:
    """Reject empty or runaway replies, and replies that drop a flag the recruiter must see."""
    if not text or len(text) > MAX_SUMMARY_CHARS:
        return False
    return not f["flags"] or "copy" in text.lower() or "listed" in text.lower() or "heading" in text.lower()


def mode() -> str:
    return "llm" if os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("EXPLAIN_BACKEND", "llm") != "rules" else "rules"


def summarize(candidate: dict, job_title: str) -> dict:
    """Return {"text", "source"}; `source` is "llm" or "rules"."""
    f = facts(candidate, job_title)
    fallback = {"text": rules_summary(f), "source": "rules"}
    if mode() != "llm":
        return fallback
    key = json.dumps(f, sort_keys=True)
    if key in _cache:
        return _cache[key]
    try:
        text = _ask_llm(f)
    except Exception as exc:  # noqa: BLE001 - any failure falls back to rules
        logger.warning("LLM summary failed (%s). Using rules summary.", type(exc).__name__)
        return fallback
    result = {"text": text, "source": "llm"} if _acceptable(text, f) else fallback
    _cache[key] = result
    return result
