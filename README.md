# Screen — AI-Based Resume Screening & Candidate Shortlisting System

**Project ID:** P_101 / P_204 (HCL Industry Project Catalogue)
**Domain:** Education / Cross-Industry AI Tooling · HR-Tech
**Type:** Full Stack Development + AI/ML (LLM-track)

A working, end-to-end web application with two separate tools, chosen with a
switch at the top of the sidebar:

1. **Rank resumes for a job** (starts from a job description). Resumes are scored against a job description
   using text similarity and skill-gap analysis, with an explanation of *why*
   each candidate scored where they did. This is the core pattern of real
   Applicant Tracking Systems (ATS).
2. **Find a resume's best role** (starts from a resume, no job description).
   The system works
   out the best-fit role (software developer, backend, web, AI/ML, data
   analyst, DevOps) as percentages with a confidence level, and ranks the
   person's skills as Primary, Secondary or Mentioned by how often the
   resume uses them. This answers "which kind of developer is this, and
   which language is their strength: C, Java or something else?".

A demo dataset of 25 resumes and 5 job descriptions is included, and the app
loads it with one button. See `docs/DEMO_GUIDE.md` for a five-minute
walkthrough.

---

## 1. Problem statement

Recruiters manually screening hundreds of resumes per role is slow and
inconsistent. This system automates the first pass: a recruiter posts a
job description, uploads a batch of resumes (PDF/DOCX/TXT), and gets
back a ranked, explainable shortlist in seconds — with matched skills,
missing skills, and a transparent score breakdown for every candidate.

## 2. Architecture

```
                    ┌─────────────────────────┐
   Browser  ───────▶│   Flask app (app.py)     │
   (HTML/CSS/JS,     │   REST API + templates   │
    no build step)   └───────────┬─────────────┘
                                  │
                 ┌────────────────┼─────────────────┐
                 ▼                ▼                 ▼
        core/parser.py     core/scorer.py     core/database.py
        (extract text      (TF-IDF similarity  (SQLite: jobs,
         from PDF/DOCX/     + skill-gap         candidates)
         TXT)                analysis)
                                  │
                                  ▼
                          core/skills_db.py
                          (skill taxonomy)
```

- **Backend:** Flask (Python), REST JSON API
- **Storage:** SQLite (zero external DB server needed — file-based)
- **Frontend:** Plain HTML/CSS/JS, no build tooling, served directly by Flask
- **Resume parsing:** `pdfplumber` (PDF), `python-docx` (DOCX), stdlib (TXT)
- **Matching engine:** scikit-learn TF-IDF + cosine similarity, plus a
  curated skill taxonomy for explainable keyword coverage

## 3. How scoring works

Candidates tailor their resume to the job description, so listing the right
keywords proves little. The score therefore rewards **evidence**:

| Signal | Weight | What it measures |
|---|---|---|
| **Text similarity** | 30% | TF-IDF cosine similarity, rescaled, reduced when long phrases are copied word for word from the job description |
| **Skill evidence** | 55% | Each skill the JD asks for earns full credit if used in experience/projects, 0.4 if only listed under Skills. "Nice to have" skills count half |
| **Depth** | 15% | Lines of described work and results with numbers |

```
final = 0.30 × similarity + 0.55 × skill evidence + 0.15 × depth   (0–100)
```

Each candidate also gets proven skills, skills listed without evidence,
missing skills and flags (possible JD copying, unproven skills, no section
headings). In a development test, a resume that pasted the JD scored 81.7 under
the old two-signal model against 56.5 for an honest one; it now scores about 33.

### Decision bands, messages and the status page

| Score | Decision |
|---|---|
| 80 and up | Selected for the next round |
| 60 to 80 | Profile under review |
| below 60 | Not selected (message includes feedback and a better-fitting role if any) |

Thresholds are editable per role and any single decision can be overridden.
**Nothing is sent without recruiter approval.** By default the app runs in
*outbox mode*: messages are saved and shown on the Outbox page, nothing leaves
the machine. To send real email set `SMTP_HOST` (plus `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`, `SMTP_FROM`; `SMTP_TLS=false` to disable STARTTLS).
Candidates check their result at `/status` with the email on their resume and
their reference (for example SCR-1A2B3C). The page shows only what they were last told.

### Sign-in

The recruiter side is private. On first run, open the app and create the
recruiter account on the sign-in page (8+ characters); after that the page
only signs in. Passwords are stored as salted hashes, sessions use HttpOnly
SameSite cookies (set `COOKIE_SECURE=true` behind HTTPS and `SECRET_KEY` for a
fixed key), writes with a foreign Origin are refused, and failed sign-ins
(5 per 10 minutes) and candidate status lookups (10 per 10 minutes per IP) are
rate limited. The limiter lives in process memory. Only `/status`, `/login` and
`/api/health` are public. There is one shared recruiter account, no roles.

### More recruiter features

* **Interview questions** for each candidate, from a fixed bank: claims to check first (skills listed without proof), then gaps, then depth questions on proven skills.
* **Compare** 2 or 3 candidates side by side with a skill matrix (shown / listed only / missing).
* **Plain-language summary** of each result (rules by default).

### Optional upgrades (off by default)

| Switch | Effect | Needs |
|---|---|---|
| `SIMILARITY_BACKEND=embeddings` | Similarity by meaning instead of word overlap. Falls back to TF-IDF if the model cannot load | `pip install sentence-transformers`, one-time model download (`EMBEDDING_MODEL`, default all-MiniLM-L6-v2) |
| `ANTHROPIC_API_KEY=...` | Summaries phrased by Claude. Only scores, skill names and flags are sent (no name, email or resume text). Falls back to the rules summary on any error. `EXPLAIN_BACKEND=rules` forces rules | An API key |

**Not run against the real services.** These two were developed in an environment
without package installs or internet access, so they were tested with stand-ins
(a toy encoder, a mocked HTTP call). The embedding score mapping (cosine 0.15 to
0.65 onto 0 to 100) is an untuned starting point: after switching it on, recheck
that the 80/60 bands still make sense on your data.

### Other recruiter features

Rejection feedback · cross-role suggestion · claimed vs proven skills · blind
mode (hides names, emails, phone numbers, college lines) · funnel dashboard ·
CSV shortlist export.

### Extending to real LLM embeddings (production upgrade path)

The TF-IDF step in `core/scorer.py::_similarity_score()` is intentionally
isolated so it can be swapped for a real embedding model without touching
anything else in the pipeline:

```python
# Replace TF-IDF + cosine similarity with, e.g., OpenAI embeddings:
from openai import OpenAI
client = OpenAI()

def _similarity_score(resume_text, jd_text):
    resp = client.embeddings.create(
        model="text-embedding-3-small",
        input=[jd_text, resume_text],
    )
    jd_vec, resume_vec = resp.data[0].embedding, resp.data[1].embedding
    sim = cosine_similarity([jd_vec], [resume_vec])[0][0]
    return max(0.0, min(1.0, sim)) * 100
```

This is exactly the two-stage pattern real ATS/HR-tech platforms use:
cheap lexical retrieval as a fast, free first pass, upgraded to dense
embeddings or LLM re-ranking when API budget allows. Mentioning this
explicitly in your viva shows you understand the production path, not
just a classroom version.

### Role detection and skill priority

Each role is a weighted skill list (`ROLE_PROFILES` in `core/skills_db.py`).
A resume's score for a role is the sum over its skills of
`weight × repeat factor`, where the repeat factor rises from 1.0 (one
mention) to 2.0 (five or more). Scores become percentages that sum to 100.
Confidence comes from the gap between the top two roles: 25 points or more
is High, 10 or more Medium, less is Low (a mixed profile). A resume with too
little technical content is left Unclassified.

Skill priority ranks skills by mention count. Compared with the most
mentioned skill, 60% or more is Primary, 30% or more is Secondary, and the
rest are Mentioned.

On the demo dataset the detected role matches the label for 23 of 25
resumes, and for all 22 where confidence was High or Medium. The resumes
are invented and were written to represent roles, so this is a regression
check on the rules, not a measure of real-world accuracy.

## 4. Setup & run

**Requirements:** Python 3.9+

```bash
# Option A — one-line launcher (creates venv, installs deps, runs)
./run.sh

# Option B — manual
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:5000** in a browser.

Press **Load demo data** in the app to try everything at once.

## 5. Running tests

```bash
python -m unittest discover -s tests -v
```

86 tests cover evidence scoring, decision bands, messages, mail delivery (mocked), sign-in and rate limiting, interview questions, the embeddings and LLM-summary switches (with stand-ins), the scoring engine, the parser, skill counting (including the
C language and Java vs JavaScript), role detection, skill priority, the demo
dataset, and the API (PDF and DOCX upload, demo loading, database migration).

## 6. API reference

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/jobs` | Create a job posting `{title, description}` |
| GET | `/api/jobs` | List all job postings |
| GET | `/api/jobs/<id>` | Get one job posting |
| DELETE | `/api/jobs/<id>` | Delete a job posting + its candidates |
| POST | `/api/jobs/<id>/candidates` | Upload resumes (multipart, field `resumes`) — parses, scores, stores |
| GET | `/api/jobs/<id>/candidates` | Ranked candidate list for a job |
| GET | `/api/candidates/<id>` | Full detail + explanation for one candidate |
| DELETE | `/api/candidates/<id>` | Delete a candidate |
| POST | `/api/analyze` | Job-independent analysis of uploaded resumes: best-fit role, role percentages, skill priority. Nothing is stored |
| PATCH | `/api/jobs/<id>` | Set `select_threshold` and `review_threshold` |
| PATCH | `/api/candidates/<id>` | Recruiter override `{status}` (empty to clear) |
| GET | `/api/candidates/<id>/other-roles` | Other open roles this resume fits |
| GET / POST | `/api/candidates/<id>/message` · `/notify` | Preview, then approve and send/save the message |
| POST | `/api/jobs/<id>/notify` | Message every candidate whose status changed |
| GET | `/api/jobs/<id>/analytics` | Funnel, score spread, common gaps |
| GET | `/api/jobs/<id>/export.csv` | Shortlist as CSV |
| GET | `/api/messages`, `/api/mail/mode` | Outbox and delivery mode |
| POST | `/api/status/lookup` | Candidate status by email + reference (page: `/status`) |
| POST | `/api/demo/load` | Create the 5 demo jobs and score the demo resumes (safe to repeat) |
| GET | `/api/demo/analyze` | Analyze the demo dataset and compare with its labels |
| GET | `/api/health` | Liveness check |

## 7. Project structure

```
resume-screening-system/
├── app.py                   # Flask app + REST API
├── core/
│   ├── parser.py             # PDF/DOCX/TXT text extraction
│   ├── scorer.py              # Evidence-based scoring, skill detection and counting
│   ├── evidence.py            # Sections, copy detection, depth
│   ├── bands.py, messages.py, mailer.py, contact.py   # Decisions, drafts, delivery, email

│   ├── profiler.py             # Role detection + skill priority
│   ├── skills_db.py            # Skill taxonomy, aliases and role profiles
│   └── database.py              # SQLite persistence layer
├── templates/index.html      # Dashboard shell
├── static/
│   ├── style.css              # Visual design (paper/index-card theme)
│   └── script.js                # Frontend logic (vanilla JS, no build step)
├── data/
│   ├── sample_resumes/          # 25 invented resumes across 6 roles
│   ├── dataset_labels.csv         # Role each resume was written to represent
│   ├── job_descriptions/          # 5 job descriptions
│   ├── format_samples/            # 2 PDF + 2 DOCX resumes for upload tests
│   └── sample_jd.txt              # Original sample job description
├── docs/
│   ├── DEMO_GUIDE.md                               # Five-minute walkthrough for reviewers
│   ├── Screen_AI_Resume_Screening_Project_Report.pdf # Comprehensive Project Report Dossier
│   └── Screen_AI_Resume_Screening_Presentation.pptx # 12-Slide Project Viva Presentation Deck
├── tests/
│   ├── test_scorer.py         # Scoring engine
│   ├── test_parser.py           # Resume parsing
│   ├── test_profiler.py          # Role detection, skill priority, dataset
│   └── test_app.py                # API: uploads, demo loading, migration
├── requirements.txt
├── run.sh                    # One-line setup + launch
└── README.md
```

## 8. Known limitations (worth stating upfront in your report/viva)

- **Scanned/image PDFs** aren't supported — needs OCR (e.g. Tesseract),
  noted as a documented v2 extension rather than silently failing.
- **Demo mail mode sends nothing; the status page has no login or rate limiting; thresholds and weights were calibrated on constructed cases.**
- **TF-IDF is lexical, not semantic** — it won't catch a resume that
  says "built scalable APIs" as equivalent to "REST API development"
  the way a real embedding model would. This is exactly why the
  embeddings upgrade path (Section 3) is documented, not hidden.
- **Role detection is rule-based.** Role weights were set by hand and checked
  on invented resumes, not tuned on real recruiter labels. Mixed profiles
  are flagged Low confidence rather than forced into one role.
- **Skill taxonomy is curated, not exhaustive** — easy to extend by
  adding entries to `core/skills_db.py`; in production this would move
  to a database table maintained without a code deploy.
- **Single-process dev server** — `app.run()` is fine for a demo/local
  deployment; a production deployment would sit behind Gunicorn/uWSGI +
  Nginx, which is a one-line change (`gunicorn app:app`), not a redesign.

Being upfront about these in your submission is a strength, not a
weakness — it shows you understand the difference between a working
prototype and a hardened production system, which is exactly the kind
of judgement an HCL advisor is looking for.

## 9. Suggested demo flow for evaluation

See `docs/DEMO_GUIDE.md` for the full script. In short:

1. Press **Load demo data**: 5 jobs, each scored against 25 resumes.
2. Open the Java Developer job and click the top candidate: score
   breakdown and matched/missing skills.
3. Open the Frontend React job: the same resumes rank in a new order.
4. Switch to **Find a resume's best role** and try the demo set: resumes
   grouped by role, with confidence levels and Primary/Secondary skills.
5. Upload a PDF or DOCX from `data/format_samples/` in either tool.
6. Mention the embeddings upgrade path as the planned next step.
