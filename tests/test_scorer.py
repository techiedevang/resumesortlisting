"""
Unit tests for core.scorer. Run with:
    python -m unittest discover -s tests -v
(no pytest dependency required, uses stdlib unittest)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.scorer import score_resume, rank_candidates, MatchResult  # noqa: E402


JD_BACKEND = """
Backend Engineer - Python/Django. Required: Python, Django, REST API,
SQL, Git, AWS. Nice to have: Docker, CI/CD, MongoDB.
"""

RESUME_STRONG = """
Backend developer with 2 years experience in Python and Django, building
REST APIs, working with PostgreSQL/SQL, using Git and deploying to AWS
with Docker and GitHub Actions CI/CD.
"""

RESUME_WEAK = """
Data analyst skilled in Excel, Power BI, Tableau and basic Python for
reporting. No backend development experience.
"""

RESUME_EMPTY_OVERLAP = """
Graphic designer with expertise in Photoshop, Illustrator, and branding.
"""


class TestScorer(unittest.TestCase):

    def test_strong_match_scores_higher_than_weak_match(self):
        strong = score_resume(RESUME_STRONG, JD_BACKEND)
        weak = score_resume(RESUME_WEAK, JD_BACKEND)
        self.assertGreater(strong.final_score, weak.final_score)

    def test_strong_match_has_matched_skills(self):
        result = score_resume(RESUME_STRONG, JD_BACKEND)
        self.assertIn("python", result.matched_skills)
        self.assertIn("django", result.matched_skills)
        self.assertIn("git", result.matched_skills)

    def test_missing_skills_detected(self):
        result = score_resume(RESUME_WEAK, JD_BACKEND)
        self.assertIn("django", result.missing_skills)
        self.assertIn("python", result.matched_skills)  # weak resume does mention python

    def test_score_bounds(self):
        for resume in (RESUME_STRONG, RESUME_WEAK, RESUME_EMPTY_OVERLAP):
            result = score_resume(resume, JD_BACKEND)
            self.assertGreaterEqual(result.final_score, 0)
            self.assertLessEqual(result.final_score, 100)

    def test_no_overlap_scores_low(self):
        result = score_resume(RESUME_EMPTY_OVERLAP, JD_BACKEND)
        self.assertLess(result.final_score, 30)

    def test_rank_candidates_orders_descending_and_assigns_rank(self):
        candidates = [
            {"name": "Weak", "match_result": score_resume(RESUME_WEAK, JD_BACKEND)},
            {"name": "Strong", "match_result": score_resume(RESUME_STRONG, JD_BACKEND)},
        ]
        ranked = rank_candidates(candidates)
        self.assertEqual(ranked[0]["name"], "Strong")
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertEqual(ranked[1]["rank"], 2)

    def test_match_result_to_dict(self):
        result = score_resume(RESUME_STRONG, JD_BACKEND)
        d = result.to_dict()
        self.assertIn("final_score", d)
        self.assertIn("matched_skills", d)
        self.assertIsInstance(d["matched_skills"], list)


if __name__ == "__main__":
    unittest.main()
