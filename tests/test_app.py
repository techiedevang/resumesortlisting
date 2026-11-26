"""API tests using Flask's test client against a throw-away database."""

import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from helpers import sign_in  # noqa: E402
from core import database  # noqa: E402

database.DB_PATH = os.path.join(tempfile.mkdtemp(), "test.db")
import app as app_module  # noqa: E402

FORMATS = os.path.join(ROOT, "data", "format_samples")


class TestApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app_module.app.test_client()
        sign_in(cls.client)

    def _upload(self, url, paths_and_bytes):
        data = {"resumes": [(io.BytesIO(b), n) for n, b in paths_and_bytes]}
        return self.client.post(url, data=data, content_type="multipart/form-data")

    def test_analyze_txt_returns_role_and_skill_priority(self):
        txt = b"Skills: Java, C++, C, Data Structures, OOP. Java project using OOP. Java tests."
        r = self._upload("/api/analyze", [("someone.txt", txt)])
        self.assertEqual(r.status_code, 200)
        res = r.get_json()["results"][0]
        self.assertEqual(res["best_role"], "Software Developer")
        self.assertEqual(res["skill_priority"][0]["skill"], "java")
        self.assertEqual(res["skill_priority"][0]["level"], "Primary")

    def test_analyze_reads_pdf_and_docx(self):
        files = []
        for name in ("neha_gupta.pdf", "sneha_iyer.docx"):
            with open(os.path.join(FORMATS, name), "rb") as fh:
                files.append((name, fh.read()))
        r = self._upload("/api/analyze", files)
        self.assertEqual(r.status_code, 200)
        roles = {x["filename"]: x["best_role"] for x in r.get_json()["results"]}
        self.assertEqual(roles["neha_gupta.pdf"], "Web Developer")
        self.assertEqual(roles["sneha_iyer.docx"], "AI / ML Engineer")

    def test_analyze_rejects_unsupported_and_empty_files(self):
        r = self._upload("/api/analyze", [("a.exe", b"x"), ("empty.txt", b"   ")])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(r.get_json()["errors"]), 2)

    def test_analyze_without_files_is_400(self):
        self.assertEqual(self.client.post("/api/analyze").status_code, 400)

    def test_candidate_upload_stores_profile(self):
        job = self.client.post("/api/jobs", json={
            "title": "Java Dev",
            "description": "Java developer with OOP, SQL and data structures skills required."}).get_json()
        r = self._upload(f"/api/jobs/{job['id']}/candidates",
                         [("dev.txt", b"Java, OOP, SQL, data structures. Built Java apps.")])
        self.assertEqual(r.status_code, 201)
        cand = r.get_json()["created"][0]
        self.assertEqual(cand["profile"]["best_role"], "Software Developer")
        again = self.client.get(f"/api/candidates/{cand['id']}").get_json()
        self.assertEqual(again["profile"]["best_role"], "Software Developer")

    def test_demo_load_is_idempotent_and_ranks_sensibly(self):
        first = self.client.post("/api/demo/load")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.get_json()["created_jobs"], 5)
        second = self.client.post("/api/demo/load")
        self.assertEqual(second.get_json()["created_jobs"], 0)

        jobs = self.client.get("/api/jobs").get_json()
        java = next(j for j in jobs if j["title"].startswith("Java Developer"))
        ranked = self.client.get(f"/api/jobs/{java['id']}/candidates").get_json()
        self.assertEqual(ranked[0]["name"], "Tara Menon")
        bottom3 = {c["name"] for c in ranked[-3:]}
        self.assertTrue(bottom3 & {"Meera Joshi", "Tanya Arora", "Sneha Iyer", "Pooja Mishra"})

    def test_demo_analyze_reports_summary(self):
        s = self.client.get("/api/demo/analyze").get_json()["summary"]
        self.assertGreaterEqual(s["labelled"], 25)
        self.assertEqual(s["confident_correct"], s["confident"])

    def test_old_database_without_profile_column_is_migrated(self):
        import sqlite3
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                description TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE candidates (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL,
                name TEXT NOT NULL, filename TEXT NOT NULL, resume_text TEXT NOT NULL,
                similarity_score REAL NOT NULL, skill_coverage_score REAL NOT NULL,
                final_score REAL NOT NULL, matched_skills TEXT NOT NULL, missing_skills TEXT NOT NULL,
                extra_skills TEXT NOT NULL, created_at TEXT NOT NULL);
            INSERT INTO jobs VALUES (1,'J','desc','2026-01-01');
            INSERT INTO candidates VALUES (1,1,'Old','old.txt','text',1,1,1,'[]','[]','[]','2026-01-01');
        """)
        conn.commit(); conn.close()
        previous = database.DB_PATH
        try:
            database.DB_PATH = path
            database.init_db()
            cand = database.get_candidate(1)
            self.assertEqual(cand["profile"], {})
        finally:
            database.DB_PATH = previous


if __name__ == "__main__":
    unittest.main()
