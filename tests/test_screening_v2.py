"""Tests for evidence-based scoring, decision bands, messages, mail and the new API."""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from helpers import sign_in  # noqa: E402
from core import bands, database  # noqa: E402
from core.contact import extract_email  # noqa: E402
from core.mailer import mail_mode, send_mail  # noqa: E402
from core.messages import build_message  # noqa: E402
from core.scorer import score_resume  # noqa: E402

database.DB_PATH = os.path.join(tempfile.mkdtemp(), "v2.db")
import app as app_module  # noqa: E402

with open(os.path.join(ROOT, "data", "job_descriptions", "java_developer.txt"), encoding="utf-8") as fh:
    JD = fh.read()


def _resume(name):
    with open(os.path.join(ROOT, "data", "sample_resumes", name), encoding="utf-8") as fh:
        return fh.read()


class TestEvidenceScoring(unittest.TestCase):

    def test_jd_echo_scores_below_genuine_resume(self):
        echo = "Skills\n" + JD + "\nExperience\n" + JD
        self.assertLess(score_resume(echo, JD).final_score,
                        score_resume(_resume("ananya_singh.txt"), JD).final_score)

    def test_echo_is_flagged_as_copy(self):
        codes = {f["code"] for f in score_resume("Experience\n" + JD, JD).flags}
        self.assertIn("jd_copy", codes)

    def test_tailored_resume_with_projects_reaches_selected_band(self):
        self.assertGreaterEqual(score_resume(_resume("tara_menon.txt"), JD).final_score, 80)

    def test_showcase_echo_resume_is_flagged_and_rejected(self):
        r = score_resume(_resume("rishi_bhatia.txt"), JD)
        self.assertLess(r.final_score, 60)
        self.assertTrue(r.flags)

    def test_listed_only_skills_are_reported_separately(self):
        r = score_resume("Skills\nJava, SQL, OOP\nProjects\nBuilt a Java billing app with OOP design and unit tests.", JD)
        self.assertIn("sql", r.listed_skills)
        self.assertIn("java", r.proven_skills)


class TestBands(unittest.TestCase):

    def test_default_bands(self):
        self.assertEqual(bands.decide(80), bands.SELECTED)
        self.assertEqual(bands.decide(79.9), bands.REVIEW)
        self.assertEqual(bands.decide(60), bands.REVIEW)
        self.assertEqual(bands.decide(59.9), bands.REJECTED)

    def test_threshold_validation(self):
        self.assertIsNone(bands.validate_thresholds(80, 60))
        self.assertIsNotNone(bands.validate_thresholds(50, 60))
        self.assertIsNotNone(bands.validate_thresholds("x", 60))


class TestMessagesAndMail(unittest.TestCase):

    CAND = {"name": "Meera Joshi", "reference": "SCR-ABC123",
            "missing_skills": ["java", "sql"], "evidence": {"listed_skills": ["git"]}}

    def test_rejection_has_feedback_and_better_role(self):
        m = build_message(self.CAND, "Java Developer", bands.REJECTED,
                          [{"title": "Data Analyst", "score": 78}], "http://x/status")
        self.assertIn("java, sql", m["body"])
        self.assertIn("git", m["body"])
        self.assertIn("Data Analyst", m["body"])
        self.assertIn("SCR-ABC123", m["body"])

    def test_selected_message_has_no_rejection_wording(self):
        m = build_message(self.CAND, "Java Developer", bands.SELECTED, [], "")
        self.assertIn("selected", m["subject"].lower())

    def test_extract_email(self):
        self.assertEqual(extract_email("Name\nEmail: a.b@example.com\nx"), "a.b@example.com")
        self.assertEqual(extract_email("no address here"), "")

    def test_outbox_mode_sends_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SMTP_HOST", None)
            with mock.patch("smtplib.SMTP") as smtp:
                self.assertEqual(send_mail("a@b.co", "s", "b"), ("saved", ""))
                smtp.assert_not_called()
                self.assertEqual(mail_mode(), "outbox")

    def test_smtp_mode_uses_smtplib_and_reports_failure(self):
        with mock.patch.dict(os.environ, {"SMTP_HOST": "smtp.test", "SMTP_FROM": "hr@test"}):
            with mock.patch("smtplib.SMTP") as smtp:
                self.assertEqual(send_mail("a@b.co", "s", "b")[0], "sent")
                smtp.assert_called_once()
            with mock.patch("smtplib.SMTP", side_effect=OSError("down")):
                delivery, err = send_mail("a@b.co", "s", "b")
                self.assertEqual(delivery, "failed")
                self.assertIn("down", err)


class TestApiV2(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ.pop("SMTP_HOST", None)
        database.init_db()
        cls.c = app_module.app.test_client()
        sign_in(cls.c)
        cls.c.post("/api/demo/load")
        jobs = cls.c.get("/api/jobs").get_json()
        cls.java = next(j for j in jobs if j["title"].startswith("Java"))["id"]

    def rows(self):
        return self.c.get(f"/api/jobs/{self.java}/candidates").get_json()

    def test_candidates_have_status_rank_and_email(self):
        top = self.rows()[0]
        self.assertEqual(top["status"], "selected")
        self.assertEqual(top["rank"], 1)
        self.assertTrue(top["email"].endswith("@example.com"))
        self.assertTrue(top["reference"].startswith("SCR-"))

    def test_thresholds_patch_changes_decisions_and_validates(self):
        bad = self.c.patch(f"/api/jobs/{self.java}", json={"select_threshold": 50, "review_threshold": 60})
        self.assertEqual(bad.status_code, 400)
        self.c.patch(f"/api/jobs/{self.java}", json={"select_threshold": 95, "review_threshold": 30})
        try:
            self.assertEqual(self.rows()[0]["status"], "review")
        finally:
            self.c.patch(f"/api/jobs/{self.java}", json={"select_threshold": 80, "review_threshold": 60})

    def test_override_and_reset(self):
        cid = self.rows()[-1]["id"]
        r = self.c.patch(f"/api/candidates/{cid}", json={"status": "selected"}).get_json()
        self.assertEqual((r["status"], r["status_source"]), ("selected", "recruiter"))
        r = self.c.patch(f"/api/candidates/{cid}", json={"status": ""}).get_json()
        self.assertEqual(r["status_source"], "score")
        self.assertEqual(self.c.patch(f"/api/candidates/{cid}", json={"status": "bogus"}).status_code, 400)

    def test_notify_saves_to_outbox_and_status_page_shows_it(self):
        row = self.rows()[0]
        self.assertEqual(self.c.get("/api/mail/mode").get_json()["mode"], "outbox")
        out = self.c.post(f"/api/candidates/{row['id']}/notify").get_json()
        self.assertEqual(out["delivery"], "saved")
        before = self.c.post("/api/status/lookup", json={"email": row["email"], "reference": row["reference"]}).get_json()
        self.assertEqual(before["status"], "selected")
        self.assertEqual(before["label"], bands.CANDIDATE_LABEL["selected"])
        self.assertTrue(any(m["candidate_id"] == row["id"] for m in self.c.get("/api/messages").get_json()))

    def test_status_lookup_requires_matching_email_and_reference(self):
        row = self.rows()[1]
        self.assertEqual(self.c.post("/api/status/lookup", json={"email": "x@y.zz", "reference": row["reference"]}).status_code, 404)
        self.assertEqual(self.c.post("/api/status/lookup", json={"email": row["email"], "reference": "SCR-000000"}).status_code, 404)

    def test_unnotified_candidate_sees_received_only(self):
        row = self.rows()[2]
        r = self.c.post("/api/status/lookup", json={"email": row["email"], "reference": row["reference"]}).get_json()
        self.assertEqual(r["status"], "received")

    def test_no_email_cannot_be_notified(self):
        job = self.c.post("/api/jobs", json={"title": "Tmp", "description": "Java developer with SQL and OOP skills needed."}).get_json()
        import io
        self.c.post(f"/api/jobs/{job['id']}/candidates", data={"resumes": [(io.BytesIO(b"Java SQL OOP"), "x.txt")]},
                    content_type="multipart/form-data")
        cid = self.c.get(f"/api/jobs/{job['id']}/candidates").get_json()[0]["id"]
        self.assertEqual(self.c.post(f"/api/candidates/{cid}/notify").status_code, 400)

    def test_rejection_draft_suggests_better_role(self):
        meera = next(r for r in self.rows() if r["name"] == "Pooja Mishra")  # data analyst
        self.assertEqual(meera["status"], "rejected")
        roles = self.c.get(f"/api/candidates/{meera['id']}/other-roles").get_json()["roles"]
        self.assertTrue(any("Data Analyst" in r["title"] for r in roles))
        draft = self.c.get(f"/api/candidates/{meera['id']}/message").get_json()
        self.assertIn("Data Analyst", draft["body"])

    def test_analytics_and_csv_export(self):
        a = self.c.get(f"/api/jobs/{self.java}/analytics").get_json()
        self.assertEqual(a["total"], 25)
        self.assertEqual(sum(a["counts"].values()), 25)
        self.assertEqual(sum(a["histogram"]), 25)
        r = self.c.get(f"/api/jobs/{self.java}/export.csv")
        self.assertEqual(r.mimetype, "text/csv")
        self.assertEqual(len(r.data.decode("utf-8-sig").strip().splitlines()), 26)

    def test_csv_export_neutralises_formulas(self):
        self.assertEqual(app_module._csv_safe("=1+1"), "'=1+1")
        self.assertEqual(app_module._csv_safe("Plain"), "Plain")

    def test_status_page_renders(self):
        self.assertEqual(self.c.get("/status").status_code, 200)


class TestQuestions(unittest.TestCase):

    def test_listed_skill_gets_prove_it_question_first(self):
        from core.questions import build_questions
        qs = build_questions({"listed_skills": ["sql"], "proven_skills": ["java"]}, ["docker"])
        self.assertEqual([q["kind"] for q in qs], ["prove", "gap", "depth"])
        self.assertIn("query", qs[0]["question"].lower())

    def test_copy_flag_adds_integrity_question_and_unknown_skill_has_fallback(self):
        from core.questions import build_questions
        qs = build_questions({"listed_skills": ["cobol"], "proven_skills": []}, [], [{"code": "jd_copy"}])
        self.assertEqual(qs[0]["kind"], "integrity")
        self.assertIn("cobol", qs[1]["question"])

    def test_every_taxonomy_skill_has_a_question(self):
        from core.questions import BANK
        from core.skills_db import SKILLS_TAXONOMY
        self.assertEqual(set(SKILLS_TAXONOMY) - set(BANK), set())


class TestAuth(unittest.TestCase):

    def setUp(self):
        self.anon = app_module.app.test_client()
        app_module.login_limiter._events.clear()
        app_module.lookup_limiter._events.clear()

    def test_private_api_requires_sign_in(self):
        self.assertEqual(self.anon.get("/api/jobs").status_code, 401)
        self.assertEqual(self.anon.post("/api/demo/load").status_code, 401)
        self.assertEqual(self.anon.get("/api/messages").status_code, 401)
        self.assertEqual(self.anon.get("/api/jobs/1/export.csv").status_code, 401)

    def test_private_page_redirects_to_login(self):
        r = self.anon.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_public_routes_stay_open(self):
        for path in ("/login", "/status", "/api/health"):
            self.assertEqual(self.anon.get(path).status_code, 200, path)

    def test_setup_is_refused_once_an_account_exists(self):
        sign_in(self.anon)
        again = app_module.app.test_client().post("/api/auth/setup", json={"username": "second", "password": "another pass"})
        self.assertEqual(again.status_code, 403)

    def test_wrong_password_and_unknown_user_give_the_same_error(self):
        sign_in(self.anon)
        fresh = app_module.app.test_client()
        a = fresh.post("/api/auth/login", json={"username": "recruiter", "password": "nope nope"})
        b = fresh.post("/api/auth/login", json={"username": "ghost", "password": "nope nope"})
        self.assertEqual((a.status_code, b.status_code), (401, 401))
        self.assertEqual(a.get_json(), b.get_json())

    def test_login_is_rate_limited_after_five_failures(self):
        sign_in(self.anon)
        fresh = app_module.app.test_client()
        for _ in range(5):
            fresh.post("/api/auth/login", json={"username": "recruiter", "password": "bad bad bad"})
        r = fresh.post("/api/auth/login", json={"username": "recruiter", "password": "correct horse"})
        self.assertEqual(r.status_code, 429)

    def test_logout_ends_the_session(self):
        c = app_module.app.test_client()
        sign_in(c)
        self.assertEqual(c.get("/api/jobs").status_code, 200)
        c.post("/api/auth/logout")
        self.assertEqual(c.get("/api/jobs").status_code, 401)

    def test_status_lookup_is_rate_limited(self):
        codes = [self.anon.post("/api/status/lookup", json={"email": "a@b.co", "reference": "SCR-000000"}).status_code
                 for _ in range(11)]
        self.assertEqual(codes[:10], [404] * 10)
        self.assertEqual(codes[10], 429)

    def test_cross_origin_write_is_refused(self):
        c = app_module.app.test_client()
        sign_in(c)
        r = c.post("/api/jobs", json={"title": "x", "description": "Java developer needed with SQL skills."},
                   headers={"Origin": "http://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_password_rules_and_hashing(self):
        from core import auth
        self.assertIsNotNone(auth.validate_new_account("ab", "longenough"))
        self.assertIsNotNone(auth.validate_new_account("alice", "short"))
        self.assertIsNone(auth.validate_new_account("alice", "long enough"))
        h = auth.hash_password("secret pass")
        self.assertNotIn("secret pass", h)
        self.assertTrue(auth.verify_password(h, "secret pass"))
        self.assertFalse(auth.verify_password(h, "other"))

    def test_rate_limiter_window(self):
        from core.auth import RateLimiter
        now = [0.0]
        rl = RateLimiter(2, 10, clock=lambda: now[0])
        rl.record("k"); rl.record("k")
        self.assertTrue(rl.blocked("k"))
        now[0] = 11
        self.assertFalse(rl.blocked("k"))


class TestSimilarityBackends(unittest.TestCase):

    CONCEPTS = [("api", "rest"), ("scalable", "large"), ("database", "sql")]

    def stub_encoder(self, texts):
        """Tiny stand-in for a sentence model: each concept is one dimension, synonyms share it."""
        return [[float(any(w in t.lower() for w in group)) for group in self.CONCEPTS] + [0.01] for t in texts]

    def tearDown(self):
        from core import similarity
        os.environ.pop("SIMILARITY_BACKEND", None)
        similarity.set_encoder(None)
        similarity._encoder_failed = False

    def test_default_is_tfidf(self):
        r = score_resume("Built Java apps.", JD)
        self.assertEqual(r.similarity_backend, "tfidf")

    def test_embeddings_match_meaning_where_tfidf_cannot(self):
        from core import similarity
        jd, cv = "Needs REST experience", "I built scalable API services"
        tfidf, _, _ = similarity.compute(cv, jd)
        similarity.set_encoder(self.stub_encoder)
        os.environ["SIMILARITY_BACKEND"] = "embeddings"
        emb, raw, backend = similarity.compute(cv, jd)
        self.assertEqual(backend, "embeddings")
        self.assertGreater(emb, tfidf)
        self.assertGreater(raw, 50)

    def test_missing_model_falls_back_to_tfidf(self):
        from core import similarity
        similarity._encoder_failed = True
        os.environ["SIMILARITY_BACKEND"] = "embeddings"
        self.assertEqual(similarity.compute("java", "java developer")[2], "tfidf")

    def test_embedding_score_is_scaled_into_range(self):
        from core import similarity
        similarity.set_encoder(self.stub_encoder)
        os.environ["SIMILARITY_BACKEND"] = "embeddings"
        r = score_resume("Experience\nBuilt a REST API with a SQL database for large systems.", JD)
        self.assertEqual(r.similarity_backend, "embeddings")
        self.assertTrue(0 <= r.similarity_score <= 100)


class TestSummary(unittest.TestCase):

    CAND = {"final_score": 55.4, "status": "rejected", "missing_skills": ["sql"], "depth_score": 20,
            "rank": 4, "job_candidate_count": 25,
            "evidence": {"proven_skills": ["java"], "listed_skills": ["git"]},
            "flags": [{"code": "jd_copy", "label": "Possible copying from the job description"}]}

    def tearDown(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from core import explain
        explain._cache.clear()

    def test_rules_summary_uses_only_the_evidence(self):
        from core import explain
        out = explain.summarize(self.CAND, "Java Developer")
        self.assertEqual(out["source"], "rules")
        for word in ("55", "java", "git", "sql", "copying"):
            self.assertIn(word, out["text"].lower())

    def test_llm_prompt_carries_no_identity(self):
        from core import explain
        cand = dict(self.CAND, name="Secret Name", email="secret@x.co", resume_text="PRIVATE TEXT")
        self.assertNotIn("Secret", str(explain.facts(cand, "Java Developer")))
        self.assertNotIn("PRIVATE", str(explain.facts(cand, "Java Developer")))

    def test_llm_reply_is_used_when_valid(self):
        from core import explain
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        with mock.patch.object(explain, "_ask_llm", return_value="Strong Java work, but SQL is missing. Possible copying was flagged.") as ask:
            out = explain.summarize(self.CAND, "Java Developer")
            explain.summarize(self.CAND, "Java Developer")
        self.assertEqual(out["source"], "llm")
        ask.assert_called_once()  # second call served from cache

    def test_llm_failure_and_bad_reply_fall_back_to_rules(self):
        from core import explain
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        with mock.patch.object(explain, "_ask_llm", side_effect=OSError("down")):
            self.assertEqual(explain.summarize(self.CAND, "J")["source"], "rules")
        explain._cache.clear()
        with mock.patch.object(explain, "_ask_llm", return_value="x" * 2000):
            self.assertEqual(explain.summarize(self.CAND, "J")["source"], "rules")
        explain._cache.clear()
        with mock.patch.object(explain, "_ask_llm", return_value="Good candidate overall."):  # drops the flag
            self.assertEqual(explain.summarize(self.CAND, "J")["source"], "rules")

    def test_request_is_sent_to_the_api_with_key_header(self):
        from core import explain
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        fake = mock.MagicMock()
        fake.__enter__.return_value = io.BytesIO(json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode())
        with mock.patch("urllib.request.urlopen", return_value=fake) as uo:
            self.assertEqual(explain._ask_llm({"flags": []}), "ok")
        req = uo.call_args[0][0]
        self.assertEqual(req.get_header("X-api-key"), "test-key")
        self.assertIn("anthropic.com", req.full_url)

    def test_summary_and_system_endpoints(self):
        c = app_module.app.test_client()
        sign_in(c)
        c.post("/api/demo/load")
        jid = c.get("/api/jobs").get_json()[0]["id"]
        cid = c.get(f"/api/jobs/{jid}/candidates").get_json()[0]["id"]
        self.assertEqual(c.get(f"/api/candidates/{cid}/summary").get_json()["source"], "rules")
        self.assertEqual(c.get("/api/system").get_json()["similarity"], "tfidf")
        self.assertEqual(c.get(f"/api/candidates/{cid}/questions").status_code, 200)


if __name__ == "__main__":
    unittest.main()
