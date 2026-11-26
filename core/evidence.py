"""
evidence.py
-----------
Signals that separate a resume that *shows* a skill from one that only
*lists* it. Candidates routinely tailor their resume to the job description,
so keyword coverage alone is 100% for almost everyone, and a resume that
simply echoes the JD can outscore one with real project work. These helpers
measure evidence instead.

1. split_sections()   resume text -> skills text / evidence text / other
2. jd_skill_weights() required skills weigh 1.0, "nice to have" skills 0.5
3. copy_ratio()       share of the resume's 5-word phrases copied from the JD
4. depth_signals()    experience/project lines and quantified results

Everything here is plain Python and deterministic.
"""

import re

# ------------------------------------------------------------------ sections

_SKILL_HEADERS = {
    "skills", "technical skills", "core skills", "key skills", "skills summary",
    "tech stack", "technologies", "soft skills", "skill set", "tools",
}
_EVIDENCE_HEADERS = {
    "experience", "work experience", "professional experience", "employment",
    "projects", "academic projects", "personal projects", "internship",
    "internships", "achievements", "highlights", "accomplishments",
}
_OTHER_HEADERS = {
    "summary", "profile", "objective", "career objective", "education",
    "coursework", "certifications", "certification", "interests", "strengths",
    "languages", "hobbies", "awards", "personal details", "declaration",
}
_ALL_HEADERS = _SKILL_HEADERS | _EVIDENCE_HEADERS | _OTHER_HEADERS


def _section_of(name: str) -> str:
    if name in _SKILL_HEADERS:
        return "skills"
    if name in _EVIDENCE_HEADERS:
        return "evidence"
    return "other"


def split_sections(text: str) -> dict:
    """
    Split resume text into three buckets by its section headers.

    Returns {"skills": str, "evidence": str, "other": str, "detected": bool}.
    `detected` is False when no recognised header was found; callers then
    cannot tell listed skills from demonstrated ones and should say so.

    A header is a short line that is only a known section name ("Skills",
    "Projects:"). A line such as "Skills: Python, Java" is treated as a one-line
    skills section.
    """
    buckets = {"skills": [], "evidence": [], "other": []}
    current = "other"
    detected = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        key = line.rstrip(":").strip().lower()
        if key in _ALL_HEADERS:
            current = _section_of(key)
            detected = True
            continue
        inline = re.match(r"^([a-z][a-z ]{1,24}):\s*(.+)$", line, re.IGNORECASE)
        if inline and inline.group(1).strip().lower() in _ALL_HEADERS:
            name = inline.group(1).strip().lower()
            detected = True
            buckets[_section_of(name)].append(inline.group(2))
            continue
        buckets[current].append(line)

    return {
        "skills": "\n".join(buckets["skills"]),
        "evidence": "\n".join(buckets["evidence"]),
        "other": "\n".join(buckets["other"]),
        "detected": detected,
    }


# ------------------------------------------------------- required vs optional

_OPTIONAL_MARKERS = re.compile(
    r"\b(bonus|nice to have|nice-to-have|is a plus|are a plus|a plus|preferred|"
    r"good to have|optional|desirable|advantage|exposure to|familiarity with)\b",
    re.IGNORECASE,
)


def jd_skill_weights(jd_text: str, skill_finder) -> dict:
    """
    Weight each skill the JD asks for: 1.0 if required, 0.5 if every mention
    sits in a clause marked as optional ("bonus", "nice to have", "a plus"...).

    `skill_finder(text) -> set of skills` is passed in to avoid a circular
    import with the scorer. Clauses are split on newlines, semicolons and
    sentence ends, so "Strong Java; C++ is a plus" marks only C++ optional.
    """
    required, optional = set(), set()
    for clause in re.split(r"[\n;]|(?<=[.!?])\s", jd_text):
        skills = skill_finder(clause)
        if not skills:
            continue
        (optional if _OPTIONAL_MARKERS.search(clause) else required).update(skills)

    weights = {s: 1.0 for s in required}
    for s in optional - required:
        weights[s] = 0.5
    return weights


# -------------------------------------------------------------- copy detection

_WORD = re.compile(r"[a-z0-9+#]+")
_SHINGLE = 5


def _shingles(text: str) -> set:
    words = _WORD.findall(text.lower())
    return {tuple(words[i:i + _SHINGLE]) for i in range(len(words) - _SHINGLE + 1)}


def copy_ratio(resume_text: str, jd_text: str) -> float:
    """
    Fraction (0 to 1) of the resume's 5-word phrases that also appear, word for
    word, in the job description. Genuine resumes share single words and short
    phrases with a JD; long identical runs mean the text was copied.
    """
    mine = _shingles(resume_text)
    if not mine:
        return 0.0
    return len(mine & _shingles(jd_text)) / len(mine)


# ------------------------------------------------------------------ depth

_QUANTIFIED = re.compile(r"\d[\d,.]*\s*(?:%|k\b|m\b|x\b|\+)", re.IGNORECASE)
_YEARS = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", re.IGNORECASE)


def depth_signals(sections: dict) -> dict:
    """
    How much work the resume describes, from its evidence sections:
    `lines` (lines of at least 5 words), `quantified` (results with a number
    such as 40% or 50k) and `years` (largest "N years" mentioned anywhere).
    """
    evidence = sections["evidence"]
    lines = [l for l in evidence.splitlines() if len(l.split()) >= 5]
    quantified = len(_QUANTIFIED.findall(evidence))
    years = 0.0
    for text in (sections["evidence"], sections["other"]):
        for m in _YEARS.finditer(text):
            years = max(years, float(m.group(1)))
    return {"lines": len(lines), "quantified": quantified, "years": years}


def depth_score(signals: dict) -> float:
    """0 to 100: 70 points for described work (6 lines is full, enough for
    three small projects), 30 for quantified results (3 is full)."""
    return min(signals["lines"], 6) / 6 * 70 + min(signals["quantified"], 3) / 3 * 30
