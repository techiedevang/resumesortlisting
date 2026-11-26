"""
seed.py
-------
Pre-populates the database with the default admin recruiter account
and demo job descriptions + scored candidates if not already present.
Executed before starting gunicorn on cloud deployments (e.g., Render).
"""
import sys
from core import database, auth

def seed():
    database.init_db()

    # 1. Ensure default admin user exists
    if database.count_users() == 0:
        database.create_user("admin", auth.hash_password("admin@123"))
        print("[SEED] Created default recruiter account: admin / admin@123")
    else:
        print("[SEED] Recruiter account already exists.")

    # 2. Ensure demo jobs and scored resumes are loaded
    jobs = database.list_jobs()
    if len(jobs) == 0:
        from app import app, load_demo
        with app.app_context():
            res, code = load_demo()
            print(f"[SEED] Loaded demo dataset: {res.get_json()} (status {code})")
    else:
        print(f"[SEED] Found {len(jobs)} existing jobs. Skipping demo data load.")

if __name__ == "__main__":
    seed()
