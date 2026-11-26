"""Tests for role detection and skill priority (core.profiler) and the
labelled demo dataset. Run: python -m unittest discover -s tests -v"""

import csv
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from core.profiler import analyze_resume, skill_priority, role_fit  # noqa: E402
from core.scorer import count_skill_mentions  # noqa: E402

DATA = os.path.join(ROOT, "data")

JAVA_C_DEV = """Skills: Java, C++, C, Data Structures, OOP
Project: bank system in Java using OOP and data structures; Java unit tests.
Another Java project with C++ algorithms."""

WEB_DEV = """Frontend developer. Skills: HTML, CSS, JavaScript, React.
Built React components, JavaScript apps and responsive HTML/CSS pages."""

ML_DEV = """Machine learning engineer. PyTorch, TensorFlow, NLP, computer vision, deep learning.
Trained deep learning models in PyTorch for NLP and computer vision."""


class TestSkillCounting(unittest.TestCase):

    def test_repeated_mentions_are_counted(self):
        counts = count_skill_mentions("Java and Java and more Java")
        self.assertEqual(counts["java"], 3)

    def test_java_not_counted_inside_javascript(self):
        counts = count_skill_mentions("I write JavaScript daily")
        self.assertNotIn("java", counts)
        self.assertEqual(counts["javascript"], 1)

    def test_c_language_only_in_a_language_list(self):
        self.assertIn("c", count_skill_mentions("Skills: C, C++, Java"))
        self.assertNotIn("c", count_skill_mentions("Scored grade C in school; vitamin C"))

    def test_nodejs_is_not_javascript(self):
        counts = count_skill_mentions("Backend in Node.js")
        self.assertNotIn("javascript", counts)
        self.assertIn("node.js", counts)


class TestSkillPriority(unittest.TestCase):

    def test_levels_follow_ratio_to_top_skill(self):
        pr = {p["skill"]: p["level"] for p in skill_priority({"java": 10, "c": 5, "git": 1})}
        self.assertEqual(pr["java"], "Primary")
        self.assertEqual(pr["c"], "Secondary")
        self.assertEqual(pr["git"], "Mentioned")

    def test_ordered_by_mentions(self):
        pr = skill_priority({"c": 2, "java": 7, "sql": 4})
        self.assertEqual([p["skill"] for p in pr], ["java", "sql", "c"])

    def test_empty(self):
        self.assertEqual(skill_priority({}), [])


class TestRoleDetection(unittest.TestCase):

    def test_java_c_profile_is_software_developer(self):
        self.assertEqual(analyze_resume(JAVA_C_DEV)["best_role"], "Software Developer")

    def test_web_profile(self):
        self.assertEqual(analyze_resume(WEB_DEV)["best_role"], "Web Developer")

    def test_ml_profile(self):
        self.assertEqual(analyze_resume(ML_DEV)["best_role"], "AI / ML Engineer")

    def test_percentages_sum_to_100(self):
        fits = analyze_resume(JAVA_C_DEV)["role_fit"]
        self.assertAlmostEqual(sum(f["percent"] for f in fits), 100, delta=0.6)

    def test_non_technical_resume_is_unclassified(self):
        a = analyze_resume("B.Com graduate. Hardworking team player. Interests: reading.")
        self.assertEqual(a["best_role"], "Unclassified")
        self.assertEqual(a["role_fit"], [])

    def test_mixed_profile_gets_low_confidence(self):
        a = analyze_resume("Skills: Java, HTML, CSS, JavaScript, Python, machine learning, SQL")
        self.assertEqual(a["confidence"], "Low")

    def test_strong_profile_gets_high_confidence(self):
        self.assertEqual(analyze_resume(ML_DEV)["confidence"], "High")

    def test_role_fit_empty_below_evidence_threshold(self):
        self.assertEqual(role_fit({"git": 1}), [])


class TestDemoDataset(unittest.TestCase):
    """The shipped dataset is invented and written to represent known roles,
    so this is a regression check on the rules, not an independent benchmark."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(DATA, "dataset_labels.csv"), newline="") as fh:
            cls.rows = list(csv.DictReader(fh))
        cls.results = []
        for r in cls.rows:
            with open(os.path.join(DATA, "sample_resumes", r["file_stem"] + ".txt")) as fh:
                a = analyze_resume(fh.read())
            cls.results.append((r, a))

    def test_dataset_size(self):
        self.assertGreaterEqual(len(self.rows), 25)

    def test_every_label_has_a_resume(self):
        for r in self.rows:
            self.assertTrue(os.path.exists(
                os.path.join(DATA, "sample_resumes", r["file_stem"] + ".txt")), r["file_stem"])

    def test_overall_agreement_with_labels(self):
        correct = sum(a["best_role"] == r["expected_role"] for r, a in self.results)
        self.assertGreaterEqual(correct, 21, f"only {correct}/{len(self.results)} matched")

    def test_confident_predictions_are_correct(self):
        for r, a in self.results:
            if a["confidence"] in ("High", "Medium"):
                self.assertEqual(a["best_role"], r["expected_role"], r["file_stem"])

    def test_every_role_is_represented(self):
        found = {r["expected_role"] for r, _ in self.results}
        for role in ("Software Developer", "Backend Developer", "Web Developer",
                     "AI / ML Engineer", "Data Analyst", "DevOps / Cloud Engineer"):
            self.assertIn(role, found)


if __name__ == "__main__":
    unittest.main()
