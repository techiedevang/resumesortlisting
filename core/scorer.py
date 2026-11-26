"""
scorer.py
---------
The matching/ranking engine at the heart of the resume screening system.

Scoring model (v2: evidence-based)
==================================
Candidates tailor their resume to the job description, so listing the right
keywords proves little. A resume that only echoes the JD can outscore one with
real project work. The score therefore rewards evidence:

1. Text similarity (30%)   TF-IDF cosine similarity of resume and JD, rescaled
                           to 0-100 and reduced when the resume copies long
                           phrases from the JD word for word.
2. Skill evidence (55%)    Each skill the JD asks for earns full credit if the
                           resume uses it in experience or projects, and 0.4
                           credit if it only appears in a skills list. Skills
                           the JD marks "nice to have" count half as much.
3. Depth (15%)             How much work the resume describes: project and
                           experience lines, and results with numbers.

Final score = 0.30 x similarity + 0.55 x skill evidence + 0.15 x depth  (0-100)

Each candidate also gets proven skills, skills listed without evidence,
missing skills, and flags (for example "possible JD copying").

This module also owns skill detection (`extract_skills`) and mention
counting (`count_skill_mentions`), which core/profiler.py uses for
role-fit and skill-priority analysis.

Pluggable embeddings (production upgrade path)
================================================
`_similarity_score()` is isolated so the TF-IDF vectoriser can be swapped
for a real embedding model (Sentence-Transformers, OpenAI embeddings)
without touching skill extraction, weighting or ranking.
"""

import re
from dataclasses import dataclass, field

from .evidence import (
    copy_ratio as _copy_ratio,
    depth_score as _depth_score,
    depth_signals,
    jd_skill_weights,
    split_sections,
)
from . import similarity
from .skills_db import SKILLS_TAXONOMY

# ------------------------------------------------------------------
# Skill detection
# ------------------------------------------------------------------
# Every alias becomes one alternative in a single regex per skill. Plain
# aliases are matched as whole tokens: the lookbehind refuses a preceding
# letter, digit or dot (so the "js" inside "node.js" does not count as
# JavaScript) and the lookahead refuses a following letter or digit (so
# "java" does not match inside "javascript"). Longer aliases are tried
# first, so "react.js" is counted once, not as both "react.js" and "react".


def _alias_to_pattern(alias: str) -> str:
    if alias.startswith("regex:"):
        return alias[len("regex:"):]
    cleaned = alias.strip()
    return r"(?<![a-z0-9.])" + re.escape(cleaned) + r"(?![a-z0-9])"


def _compile_skill_patterns():
    compiled = {}
    for canonical, aliases in SKILLS_TAXONOMY.items():
        ordered = sorted(aliases, key=len, reverse=True)
        compiled[canonical] = re.compile(
            "|".join(_alias_to_pattern(a) for a in ordered)
        )
    return compiled


_SKILL_PATTERNS = _compile_skill_patterns()


def count_skill_mentions(text: str) -> dict:
    """Return {canonical_skill: number_of_mentions} for skills found in text."""
    text_lower = f" {text.lower()} "
    counts = {}
    for canonical, pattern in _SKILL_PATTERNS.items():
        n = len(pattern.findall(text_lower))
        if n:
            counts[canonical] = n
    return counts


def extract_skills(text: str) -> set:
    """Return the set of canonical skills found in a block of text."""
    return set(count_skill_mentions(text))


# Kept for backwards compatibility with earlier code and tests.
_extract_skills = extract_skills


# ------------------------------------------------------------------
# Scoring
# ------------------------------------------------------------------

@dataclass
class MatchResult:
    similarity_score: float          # 0-100, rescaled and copy-adjusted
    skill_coverage_score: float      # 0-100, evidence-weighted skill coverage
    final_score: float               # 0-100
    matched_skills: list = field(default_factory=list)   # proven + listed
    missing_skills: list = field(default_factory=list)
    extra_skills: list = field(default_factory=list)
    depth_score: float = 0.0         # 0-100
    proven_skills: list = field(default_factory=list)    # used in projects/experience
    listed_skills: list = field(default_factory=list)    # in a skills list only
    flags: list = field(default_factory=list)            # [{"code", "label"}]
    copy_ratio: float = 0.0
    raw_similarity: float = 0.0      # unscaled TF-IDF cosine, 0-100
    depth: dict = field(default_factory=dict)            # lines/quantified/years
    similarity_backend: str = "tfidf"

    def evidence(self) -> dict:
        """The part stored as JSON next to a candidate."""
        return {
            "proven_skills": self.proven_skills,
            "listed_skills": self.listed_skills,
            "flags": self.flags,
            "copy_ratio": round(self.copy_ratio, 3),
            "raw_similarity": round(self.raw_similarity, 2),
            "depth": self.depth,
            "similarity_backend": self.similarity_backend,
        }

    def to_dict(self):
        d = {
            "similarity_score": round(self.similarity_score, 2),
            "skill_coverage_score": round(self.skill_coverage_score, 2),
            "depth_score": round(self.depth_score, 2),
            "final_score": round(self.final_score, 2),
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "extra_skills": self.extra_skills,
        }
        d.update(self.evidence())
        return d


SIMILARITY_WEIGHT = 0.30
EVIDENCE_WEIGHT = 0.55
DEPTH_WEIGHT = 0.15

SIMILARITY_SCALE = 2.5         # TF-IDF cosine is low even for good matches
LISTED_ONLY_CREDIT = 0.4       # skill in a skills list, no project/experience use
SINGLE_MENTION_CREDIT = 0.7    # no sections found, skill mentioned once
# Soft skills cannot be shown by a keyword in a project line, so a mention
# anywhere earns full credit.
SOFT_SKILLS = {"communication", "leadership", "problem solving", "project management"}
COPY_PENALTY_RATE = 2.0        # similarity falls by 2 points per point of copy ratio
COPY_PENALTY_MAX = 0.8
COPY_FLAG_AT = 0.20
UNPROVEN_FLAG_AT = 0.5


def _similarity_score(resume_text: str, jd_text: str) -> float:
    """TF-IDF cosine similarity between resume and job description, 0-100 (see core/similarity.py)."""
    return similarity.tfidf_similarity(resume_text, jd_text)


def score_resume(resume_text: str, jd_text: str) -> MatchResult:
    """Score one resume against a job description, with an evidence breakdown."""
    sections = split_sections(resume_text)
    scaled_sim, raw_sim, backend = similarity.compute(resume_text, jd_text)
    ratio = _copy_ratio(resume_text, jd_text)
    penalty = min(COPY_PENALTY_MAX, ratio * COPY_PENALTY_RATE)
    sim_score = scaled_sim * (1 - penalty)

    weights = jd_skill_weights(jd_text, extract_skills)
    in_resume = count_skill_mentions(resume_text)
    in_evidence = count_skill_mentions(sections["evidence"]) if sections["detected"] else {}

    proven, listed, missing = [], [], []
    earned = 0.0
    for skill, w in weights.items():
        if skill not in in_resume:
            missing.append(skill)
        elif skill in SOFT_SKILLS:
            proven.append(skill); earned += w
        elif sections["detected"]:
            if in_evidence.get(skill, 0) >= 1:
                proven.append(skill); earned += w
            else:
                listed.append(skill); earned += w * LISTED_ONLY_CREDIT
        else:
            # No headings: mentioned twice or more counts as used, once is weaker.
            if in_resume[skill] >= 2:
                proven.append(skill); earned += w
            else:
                listed.append(skill); earned += w * SINGLE_MENTION_CREDIT

    if weights:
        evidence_cov = earned / sum(weights.values()) * 100
    else:
        # JD names no skill from the taxonomy: fall back to similarity alone.
        evidence_cov = sim_score

    signals = depth_signals(sections)
    depth = _depth_score(signals)

    flags = []
    if ratio >= COPY_FLAG_AT:
        flags.append({
            "code": "jd_copy",
            "label": f"Possible copying from the job description ({ratio * 100:.0f}% of phrases match word for word)",
        })
    if sections["detected"] and len(weights) >= 3 and len(listed) / len(weights) >= UNPROVEN_FLAG_AT:
        flags.append({
            "code": "unproven_skills",
            "label": "Many required skills are listed but not shown in projects or experience",
        })
    if not sections["detected"]:
        flags.append({
            "code": "no_sections",
            "label": "No section headings found, so listed skills could not be checked against projects",
        })

    final = (SIMILARITY_WEIGHT * sim_score
             + EVIDENCE_WEIGHT * evidence_cov
             + DEPTH_WEIGHT * depth)

    return MatchResult(
        similarity_score=sim_score,
        skill_coverage_score=evidence_cov,
        final_score=final,
        matched_skills=sorted(proven + listed),
        missing_skills=sorted(missing),
        extra_skills=sorted(set(in_resume) - set(weights)),
        depth_score=depth,
        proven_skills=sorted(proven),
        listed_skills=sorted(listed),
        flags=flags,
        copy_ratio=ratio,
        raw_similarity=raw_sim,
        depth=signals,
        similarity_backend=backend,
    )


def rank_candidates(candidates: list) -> list:
    """Sort candidates (dicts with a 'match_result') by final score and add 'rank'."""
    ranked = sorted(
        candidates, key=lambda c: c["match_result"].final_score, reverse=True
    )
    for idx, c in enumerate(ranked, start=1):
        c["rank"] = idx
    return ranked
