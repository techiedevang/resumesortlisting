"""
app.py
------
Flask application entry point for the AI-Based Resume Screening and
Candidate Shortlisting System.

Run with:
    python app.py

Then open http://localhost:5000 in a browser.

Tool 1: rank resumes for a job
------------------------------
POST   /api/jobs                       create a job posting
GET    /api/jobs                       list all job postings
GET    /api/jobs/<id>                  get one job posting
PATCH  /api/jobs/<id>                  set the selected / under-review thresholds
DELETE /api/jobs/<id>                  delete a job posting (+ its candidates)
POST   /api/jobs/<id>/candidates       upload resumes; parse, score, store
GET    /api/jobs/<id>/candidates       ranked candidate list for a job
GET    /api/jobs/<id>/analytics        funnel, score spread, common gaps
GET    /api/jobs/<id>/export.csv       shortlist as a CSV file
POST   /api/jobs/<id>/notify           message every candidate whose status changed
GET    /api/candidates/<id>            full detail + evidence for one candidate
PATCH  /api/candidates/<id>            recruiter override of the decision
DELETE /api/candidates/<id>            delete a candidate
GET    /api/candidates/<id>/other-roles    other open roles this resume fits
GET    /api/candidates/<id>/summary        plain-language summary (rules or LLM)
GET    /api/candidates/<id>/questions      interview questions from the evidence
GET    /api/candidates/<id>/message        draft message for the current decision
POST   /api/candidates/<id>/notify         send that message (recruiter approval)

Candidate status page
---------------------
GET    /status                         page where a candidate checks their status
POST   /api/status/lookup              look up by email + reference

Messages
--------
GET    /api/messages                   everything sent or saved to the outbox
GET    /api/mail/mode                  "outbox" (nothing sent) or "smtp"

Tool 2: find a resume's best role
---------------------------------
POST   /api/analyze                    best-fit role + skill priority per resume

Demo
----
POST   /api/demo/load                  create demo jobs and score the demo dataset
GET    /api/demo/analyze               profile the demo dataset, with accuracy vs labels

GET    /api/health                     liveness check
"""

import csv
import io
import logging
import os
import secrets

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from core import auth, bands, database
from core import explain, similarity
from core.contact import extract_email
from core.mailer import mail_mode, send_mail
from core.messages import build_message
from core.parser import ParsingError, SUPPORTED_EXTENSIONS, extract_text
from core.profiler import analyze_resume
from core.questions import build_questions
from core.scorer import score_resume

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("resume_screening")

MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB per request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

database.init_db()


def _secret_key() -> str:
    """SECRET_KEY from the environment, else a random key kept next to the database."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(os.path.dirname(os.path.abspath(database.DB_PATH)), ".secret_key")
    try:
        with open(path) as fh:
            return fh.read().strip()
    except FileNotFoundError:
        key = secrets.token_hex(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(key)
        return key


app.config.update(
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
    PERMANENT_SESSION_LIFETIME=8 * 3600,
)

login_limiter = auth.RateLimiter(limit=5, window=600)     # failed sign-ins per ip+user
lookup_limiter = auth.RateLimiter(limit=10, window=600)   # status lookups per ip

ALLOWED_EXTENSIONS = set(SUPPORTED_EXTENSIONS)


def _allowed_file(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


def _display_name(filename: str) -> str:
    return os.path.splitext(filename)[0].replace("_", " ").replace("-", " ").title()


def _body() -> dict:
    return request.get_json(silent=True) or {}


# ------------------------------------------------------------- Sign-in ----
# Everything is private to a signed-in recruiter except the candidate status
# page and its lookup, the login page and the health check.

PUBLIC_PATHS = {"/login", "/status", "/api/health", "/api/status/lookup",
                "/api/auth/login", "/api/auth/setup", "/api/auth/me", "/api/auth/logout"}


def _client_ip() -> str:
    return request.remote_addr or "unknown"


@app.before_request
def require_login():
    if request.endpoint == "static" or request.path in PUBLIC_PATHS:
        return None
    # Cross-site form posts are stopped by SameSite=Lax; this also rejects a
    # mismatched Origin header on anything that changes data.
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        origin = request.headers.get("Origin")
        if origin and origin.split("://", 1)[-1] != request.host:
            return jsonify({"error": "Cross-origin request refused."}), 403
    if session.get("user"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Sign in required."}), 401
    return redirect(url_for("login_page"))


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    return jsonify({"user": session.get("user"), "setup_needed": database.count_users() == 0})


@app.route("/api/auth/setup", methods=["POST"])
def auth_setup():
    """Create the first recruiter account. Refused once any account exists."""
    if database.count_users() > 0:
        return jsonify({"error": "An account already exists. Sign in instead."}), 403
    payload = _body()
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    error = auth.validate_new_account(username, password)
    if error:
        return jsonify({"error": error}), 400
    database.create_user(username, auth.hash_password(password))
    session.clear()
    session.permanent = True
    session["user"] = username
    return jsonify({"user": username}), 201


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    payload = _body()
    username = (payload.get("username") or "").strip()
    key = (_client_ip(), username.lower())
    if login_limiter.blocked(key):
        return jsonify({"error": "Too many failed attempts. Try again later.",
                        "retry_after": login_limiter.retry_after(key)}), 429
    user = database.get_user(username) if username else None
    # Verify against a dummy hash for unknown users so timing does not reveal them.
    ok = auth.verify_password(user["password_hash"] if user else _DUMMY_HASH, payload.get("password") or "")
    if not (user and ok):
        login_limiter.record(key)
        return jsonify({"error": "Wrong username or password."}), 401
    login_limiter.reset(key)
    session.clear()
    session.permanent = True
    session["user"] = user["username"]
    return jsonify({"user": user["username"]})


_DUMMY_HASH = auth.hash_password("not-a-real-password")


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"user": None})


# --------------------------------------------------------------- Pages ----

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/status")
def status_page():
    return render_template("status.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


# -------------------------------------------------------------- Jobs ------

@app.route("/api/jobs", methods=["POST"])
def create_job():
    payload = _body()
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()

    if not title or not description:
        return jsonify({"error": "Both 'title' and 'description' are required."}), 400
    if len(description) < 30:
        return jsonify({"error": "Job description looks too short to match against."}), 400

    job_id = database.create_job(title, description)
    logger.info("Created job %s (%s)", job_id, title)
    return jsonify(database.get_job(job_id)), 201


@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    return jsonify(database.list_jobs())


@app.route("/api/jobs/<int:job_id>", methods=["GET"])
def get_job(job_id):
    job = database.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


@app.route("/api/jobs/<int:job_id>", methods=["PATCH"])
def update_job(job_id):
    if not database.get_job(job_id):
        return jsonify({"error": "Job not found."}), 404
    payload = _body()
    error = bands.validate_thresholds(payload.get("select_threshold"),
                                      payload.get("review_threshold"))
    if error:
        return jsonify({"error": error}), 400
    database.update_job_thresholds(job_id, payload["select_threshold"], payload["review_threshold"])
    return jsonify(database.get_job(job_id))


@app.route("/api/jobs/<int:job_id>", methods=["DELETE"])
def delete_job(job_id):
    if not database.get_job(job_id):
        return jsonify({"error": "Job not found."}), 404
    database.delete_job(job_id)
    return jsonify({"deleted": True})


# --------------------------------------------------------- Candidates -----

def _ingest(job: dict, name: str, filename: str, text: str, profile: dict = None) -> int:
    """Score one parsed resume against a job and store it."""
    return database.create_candidate(
        job_id=job["id"],
        name=name,
        filename=filename,
        resume_text=text,
        match_result=score_resume(text, job["description"]),
        profile=profile if profile is not None else analyze_resume(text),
        email=extract_email(text),
    )


@app.route("/api/jobs/<int:job_id>/candidates", methods=["POST"])
def upload_candidates(job_id):
    job = database.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404

    files = request.files.getlist("resumes")
    if not files:
        return jsonify({"error": "No files uploaded under field 'resumes'."}), 400

    created, errors = [], []
    for file_storage in files:
        filename = secure_filename(file_storage.filename or "")
        if not filename:
            errors.append({"filename": file_storage.filename, "error": "Invalid filename."})
            continue
        if not _allowed_file(filename):
            errors.append({
                "filename": filename,
                "error": f"Unsupported type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            })
            continue
        try:
            text = extract_text(filename, file_storage.read())
        except ParsingError as exc:
            errors.append({"filename": filename, "error": str(exc)})
            continue

        candidate_id = _ingest(job, _display_name(filename), filename, text)
        created.append(database.get_candidate(candidate_id))
        logger.info("Scored candidate %s for job %s", filename, job_id)

    return jsonify({"created": created, "errors": errors}), (201 if created else 400)


@app.route("/api/jobs/<int:job_id>/candidates", methods=["GET"])
def list_candidates(job_id):
    if not database.get_job(job_id):
        return jsonify({"error": "Job not found."}), 404
    return jsonify(database.list_candidates_for_job(job_id))


@app.route("/api/candidates/<int:candidate_id>", methods=["GET"])
def get_candidate(candidate_id):
    candidate = database.get_candidate(candidate_id)
    if not candidate:
        return jsonify({"error": "Candidate not found."}), 404
    return jsonify(candidate)


@app.route("/api/candidates/<int:candidate_id>", methods=["PATCH"])
def override_status(candidate_id):
    if not database.get_candidate(candidate_id):
        return jsonify({"error": "Candidate not found."}), 404
    status = _body().get("status") or ""
    if status and status not in bands.STATUSES:
        return jsonify({"error": f"Status must be one of {', '.join(bands.STATUSES)}, or empty."}), 400
    database.set_status_override(candidate_id, status)
    return jsonify(database.get_candidate(candidate_id))


@app.route("/api/candidates/<int:candidate_id>", methods=["DELETE"])
def delete_candidate(candidate_id):
    if not database.get_candidate(candidate_id):
        return jsonify({"error": "Candidate not found."}), 404
    database.delete_candidate(candidate_id)
    return jsonify({"deleted": True})


# ----------------------------------------------------- Cross-role matching --

def _other_roles(candidate: dict, limit: int = 3) -> list:
    """
    Score this candidate's resume against every other job and return those it
    reaches that job's "under review" threshold for, best first. Used to tell
    a rejected candidate which open role suits them better.
    """
    found = []
    for job in database.list_jobs():
        if job["id"] == candidate["job_id"]:
            continue
        score = score_resume(candidate["resume_text"], job["description"]).final_score
        if score >= job["review_threshold"]:
            found.append({
                "job_id": job["id"],
                "title": job["title"],
                "score": round(score, 1),
                "status": bands.decide(score, job["select_threshold"], job["review_threshold"]),
            })
    found.sort(key=lambda r: -r["score"])
    return found[:limit]


@app.route("/api/candidates/<int:candidate_id>/other-roles", methods=["GET"])
def other_roles(candidate_id):
    candidate = database.get_candidate(candidate_id)
    if not candidate:
        return jsonify({"error": "Candidate not found."}), 404
    return jsonify({"roles": _other_roles(candidate)})


@app.route("/api/candidates/<int:candidate_id>/questions", methods=["GET"])
def interview_questions(candidate_id):
    candidate = database.get_candidate(candidate_id)
    if not candidate:
        return jsonify({"error": "Candidate not found."}), 404
    return jsonify({"questions": build_questions(
        candidate["evidence"], candidate["missing_skills"], candidate["flags"])})


@app.route("/api/candidates/<int:candidate_id>/summary", methods=["GET"])
def candidate_summary(candidate_id):
    candidate = database.get_candidate(candidate_id)
    if not candidate:
        return jsonify({"error": "Candidate not found."}), 404
    return jsonify(explain.summarize(candidate, candidate["job_title"]))


@app.route("/api/system", methods=["GET"])
def system_info():
    """Which optional backends are switched on (for the footer and the report)."""
    return jsonify({
        "similarity": similarity.requested_backend(),
        "summary": explain.mode(),
        "mail": mail_mode(),
    })


# ---------------------------------------------------------- Notifications --

def _draft(candidate: dict) -> dict:
    """The message this candidate would get for their current status."""
    roles = _other_roles(candidate) if candidate["status"] == bands.REJECTED else []
    msg = build_message(
        candidate, candidate["job_title"], candidate["status"], roles,
        portal_url=request.host_url.rstrip("/") + "/status",
    )
    msg["to"] = candidate["email"]
    msg["status"] = candidate["status"]
    return msg


def _deliver(candidate: dict) -> dict:
    """Send (or save) the drafted message and record what the candidate was told."""
    draft = _draft(candidate)
    delivery, error = send_mail(candidate["email"], draft["subject"], draft["body"])
    mode = mail_mode()
    database.create_message(candidate["id"], candidate["email"], draft["subject"],
                            draft["body"], mode, delivery, error, candidate["status"])
    if delivery != "failed":
        database.mark_notified(candidate["id"], candidate["status"])
    return {"delivery": delivery, "error": error, "mode": mode, "subject": draft["subject"]}


@app.route("/api/candidates/<int:candidate_id>/message", methods=["GET"])
def preview_message(candidate_id):
    candidate = database.get_candidate(candidate_id)
    if not candidate:
        return jsonify({"error": "Candidate not found."}), 404
    draft = _draft(candidate)
    draft["mode"] = mail_mode()
    draft["can_send"] = bool(candidate["email"])
    draft["reason"] = "" if candidate["email"] else "No email address was found on this resume."
    return jsonify(draft)


@app.route("/api/candidates/<int:candidate_id>/notify", methods=["POST"])
def notify_candidate(candidate_id):
    candidate = database.get_candidate(candidate_id)
    if not candidate:
        return jsonify({"error": "Candidate not found."}), 404
    if not candidate["email"]:
        return jsonify({"error": "No email address was found on this resume."}), 400
    result = _deliver(candidate)
    if result["delivery"] == "failed":
        return jsonify({"error": f"Email could not be sent: {result['error']}", **result}), 502
    return jsonify({**result, "candidate": database.get_candidate(candidate_id)})


@app.route("/api/jobs/<int:job_id>/notify", methods=["POST"])
def notify_job(job_id):
    """Message every candidate whose current status differs from what they were last told."""
    if not database.get_job(job_id):
        return jsonify({"error": "Job not found."}), 404
    summary = {"messaged": 0, "failed": 0, "no_email": 0, "up_to_date": 0, "mode": mail_mode()}
    for row in database.list_candidates_for_job(job_id):
        if row["notified_status"] == row["status"]:
            summary["up_to_date"] += 1
            continue
        if not row["email"]:
            summary["no_email"] += 1
            continue
        candidate = database.get_candidate(row["id"])
        result = _deliver(candidate)
        summary["failed" if result["delivery"] == "failed" else "messaged"] += 1
    return jsonify(summary)


@app.route("/api/messages", methods=["GET"])
def list_messages():
    return jsonify(database.list_messages())


@app.route("/api/mail/mode", methods=["GET"])
def get_mail_mode():
    return jsonify({"mode": mail_mode()})


# ---------------------------------------------------------- Status page ----

@app.route("/api/status/lookup", methods=["POST"])
def lookup_status():
    ip = _client_ip()
    if lookup_limiter.blocked(ip):
        return jsonify({"error": "Too many lookups. Try again in a few minutes."}), 429
    lookup_limiter.record(ip)
    payload = _body()
    email = (payload.get("email") or "").strip()
    reference = (payload.get("reference") or "").strip()
    app_row = database.find_application(email, reference) if email and reference else None
    if not app_row:
        # One message for both a wrong email and a wrong reference.
        return jsonify({"error": "No application found for that email and reference."}), 404

    told = app_row["notified_status"]
    return jsonify({
        "name": app_row["name"],
        "job_title": app_row["job_title"],
        "received": True,
        "status": told or "received",
        "label": bands.CANDIDATE_LABEL.get(told, "Application received"),
        "updated_at": app_row["notified_at"],
    })


# --------------------------------------------------------- Analytics -------

@app.route("/api/jobs/<int:job_id>/analytics", methods=["GET"])
def job_analytics(job_id):
    job = database.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    rows = database.list_candidates_for_job(job_id)

    counts = {s: 0 for s in bands.STATUSES}
    missing, unproven = {}, {}
    histogram = [0] * 10
    flagged = notified = 0
    for r in rows:
        counts[r["status"]] += 1
        histogram[min(int(r["final_score"] // 10), 9)] += 1
        flagged += bool(r["flags"])
        notified += bool(r["notified_status"])
        for s in r["missing_skills"]:
            missing[s] = missing.get(s, 0) + 1
        for s in r["evidence"].get("listed_skills", []):
            unproven[s] = unproven.get(s, 0) + 1

    def top(d, n=6):
        return [{"skill": k, "count": v} for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]

    total = len(rows)
    return jsonify({
        "total": total,
        "counts": counts,
        "funnel": [
            {"stage": "Applied", "count": total},
            {"stage": "Selected or under review", "count": counts[bands.SELECTED] + counts[bands.REVIEW]},
            {"stage": "Selected", "count": counts[bands.SELECTED]},
            {"stage": "Told the result", "count": notified},
        ],
        "average_score": round(sum(r["final_score"] for r in rows) / total, 1) if total else 0,
        "histogram": histogram,
        "top_missing": top(missing),
        "top_unproven": top(unproven),
        "flagged": flagged,
        "select_threshold": job["select_threshold"],
        "review_threshold": job["review_threshold"],
    })


# ------------------------------------------------------------- CSV export --

def _csv_safe(value):
    """Stop spreadsheet programs treating resume-derived text as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@app.route("/api/jobs/<int:job_id>/export.csv", methods=["GET"])
def export_csv(job_id):
    job = database.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "Rank", "Name", "Email", "Reference", "Score", "Top %", "Status", "Status set by",
        "Text similarity", "Skill evidence", "Depth", "Skills shown in projects",
        "Skills listed only", "Missing skills", "Flags", "Told", "Told at",
    ])
    for r in database.list_candidates_for_job(job_id):
        ev = r["evidence"]
        writer.writerow([_csv_safe(v) for v in [
            r["rank"], r["name"], r["email"], r["reference"], round(r["final_score"], 1),
            r["top_percent"], bands.RECRUITER_LABEL[r["status"]], r["status_source"],
            round(r["similarity_score"], 1), round(r["skill_coverage_score"], 1),
            round(r["depth_score"], 1),
            "; ".join(ev.get("proven_skills", [])), "; ".join(ev.get("listed_skills", [])),
            "; ".join(r["missing_skills"]), "; ".join(f["label"] for f in r["flags"]),
            bands.RECRUITER_LABEL.get(r["notified_status"], ""), r["notified_at"],
        ]])

    filename = "shortlist-" + "".join(ch if ch.isalnum() else "-" for ch in job["title"]).strip("-").lower() + ".csv"
    return Response(
        "﻿" + out.getvalue(),  # BOM so Excel reads UTF-8
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ----------------------------------------------------------- Analyzer -----

@app.route("/api/analyze", methods=["POST"])
def analyze_resumes():
    """
    Job-independent analysis. Nothing is stored: each uploaded resume is
    parsed and profiled (best-fit role, role-fit percentages, skill
    priority) so a recruiter can sort a pile of resumes into role buckets
    without having a job description yet.
    """
    files = request.files.getlist("resumes")
    if not files:
        return jsonify({"error": "No files uploaded under field 'resumes'."}), 400

    results, errors = [], []
    for file_storage in files:
        filename = secure_filename(file_storage.filename or "")
        if not filename or not _allowed_file(filename):
            errors.append({
                "filename": file_storage.filename,
                "error": f"Unsupported type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            })
            continue
        try:
            text = extract_text(filename, file_storage.read())
        except ParsingError as exc:
            errors.append({"filename": filename, "error": str(exc)})
            continue

        profile = analyze_resume(text)
        profile["filename"] = filename
        profile["name"] = _display_name(filename)
        results.append(profile)

    return jsonify({"results": results, "errors": errors}), (200 if results else 400)


# ------------------------------------------------------------- Demo data -----
# A synthetic dataset (invented people) shipped in data/ so the system can be
# demonstrated without preparing any files: resumes spanning software, backend,
# web, AI/ML, data and DevOps profiles, 5 job descriptions, and a labels file
# with the role each resume was written to represent.

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RESUME_DIR = os.path.join(DATA_DIR, "sample_resumes")
JD_DIR = os.path.join(DATA_DIR, "job_descriptions")
LABELS_CSV = os.path.join(DATA_DIR, "dataset_labels.csv")


def _load_demo_resumes() -> list:
    """Return [{'filename', 'name', 'text'}] for every demo resume."""
    items = []
    if not os.path.isdir(RESUME_DIR):
        return items
    for filename in sorted(os.listdir(RESUME_DIR)):
        if not _allowed_file(filename):
            continue
        with open(os.path.join(RESUME_DIR, filename), "rb") as fh:
            try:
                text = extract_text(filename, fh.read())
            except ParsingError:
                continue
        items.append({"filename": filename, "name": _display_name(filename), "text": text})
    return items


def _load_labels() -> dict:
    labels = {}
    if os.path.exists(LABELS_CSV):
        with open(LABELS_CSV, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                labels[row["file_stem"]] = row["expected_role"]
    return labels


@app.route("/api/demo/load", methods=["POST"])
def load_demo():
    """Create one job per demo job description and score every demo resume
    against each. Safe to press twice: jobs that already exist are skipped."""
    if not os.path.isdir(JD_DIR):
        return jsonify({"error": "Demo job descriptions not found in data/job_descriptions."}), 404

    resumes = _load_demo_resumes()
    if not resumes:
        return jsonify({"error": "Demo resumes not found in data/sample_resumes."}), 404
    for r in resumes:
        r["profile"] = analyze_resume(r["text"])

    existing_titles = {j["title"] for j in database.list_jobs()}
    created_jobs = 0
    for filename in sorted(os.listdir(JD_DIR)):
        if not filename.endswith(".txt"):
            continue
        with open(os.path.join(JD_DIR, filename), encoding="utf-8") as fh:
            jd_text = fh.read().strip()
        title = jd_text.splitlines()[0].strip()
        if title in existing_titles:
            continue
        job = {"id": database.create_job(title, jd_text), "description": jd_text}
        for r in resumes:
            _ingest(job, r["name"], r["filename"], r["text"], profile=r["profile"])
        created_jobs += 1

    logger.info("Demo load: %s new jobs x %s resumes", created_jobs, len(resumes))
    return jsonify({"created_jobs": created_jobs, "resumes": len(resumes)}), (201 if created_jobs else 200)


@app.route("/api/demo/analyze", methods=["GET"])
def analyze_demo():
    """Profile the whole demo dataset and compare each detected role with the
    role the resume was written to represent."""
    labels = _load_labels()
    results = []
    for r in _load_demo_resumes():
        profile = analyze_resume(r["text"])
        profile["filename"] = r["filename"]
        profile["name"] = r["name"]
        expected = labels.get(os.path.splitext(r["filename"])[0])
        if expected:
            profile["expected_role"] = expected
            profile["matches_expected"] = profile["best_role"] == expected
        results.append(profile)

    labelled = [r for r in results if "expected_role" in r]
    correct = sum(1 for r in labelled if r["matches_expected"])
    confident = [r for r in labelled if r["confidence"] in ("High", "Medium")]
    confident_correct = sum(1 for r in confident if r["matches_expected"])
    return jsonify({
        "results": results,
        "errors": [],
        "summary": {
            "labelled": len(labelled),
            "correct": correct,
            "confident": len(confident),
            "confident_correct": confident_correct,
        },
    })


# --------------------------------------------------------- Error handlers -

@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "Upload too large. Max total size is 10 MB per request."}), 413


@app.errorhandler(500)
def server_error(e):
    logger.exception("Unhandled server error")
    return jsonify({"error": "Internal server error."}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
