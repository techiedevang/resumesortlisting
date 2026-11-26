"""
messages.py
-----------
Drafts the message a candidate receives for each decision. The rejection
message carries feedback built from the scoring evidence (skills the role asked
for that the resume did not show) and, when one exists, a better-fitting role.
"""

from . import bands


def _first_name(name: str) -> str:
    return (name or "").split()[0] if (name or "").strip() else "there"


def _skills(items) -> str:
    return ", ".join(items)


def _feedback_lines(missing: list, listed_only: list) -> list:
    lines = []
    if missing:
        lines.append(f"- Skills the role asked for that we could not find on your resume: {_skills(missing)}.")
    if listed_only:
        lines.append(
            f"- Skills you listed without a project or job that shows them: {_skills(listed_only)}. "
            "Adding one concrete example for each makes a resume much stronger."
        )
    return lines


def build_message(candidate: dict, job_title: str, status: str, other_roles: list,
                  portal_url: str = "") -> dict:
    """
    Return {"subject", "body"} for the candidate's current status.

    `candidate` needs name, reference, missing_skills and evidence (with
    listed_skills). `other_roles` is a list of {"title", "score"} for roles the
    same resume suits better; it is used only in the rejection message.
    """
    name = _first_name(candidate.get("name", ""))
    ref = candidate.get("reference", "")
    evidence = candidate.get("evidence") or {}
    track = ""
    if portal_url:
        track = (f"\nYou can check your status any time at {portal_url}\n"
                 f"using this email address and the reference {ref}.\n")

    if status == bands.SELECTED:
        subject = f"You are selected for the next round: {job_title}"
        body = (f"Dear {name},\n\n"
                f"Thank you for applying for {job_title}. We are pleased to tell you that "
                "your profile has been selected for the next round.\n\n"
                "We will contact you shortly with the schedule and what to prepare."
                f"{track}\nBest regards,\nThe Hiring Team")

    elif status == bands.REVIEW:
        subject = f"Your application is under review: {job_title}"
        body = (f"Dear {name},\n\n"
                f"Thank you for applying for {job_title}. Your profile is under review. "
                "A member of our team is looking at it, and we will update you once a decision is made."
                f"{track}\nBest regards,\nThe Hiring Team")

    else:
        subject = f"Update on your application: {job_title}"
        parts = [f"Dear {name},\n",
                 f"Thank you for applying for {job_title} and for the time you put into your application. "
                 "After reviewing your profile, we will not be taking it forward for this role.\n"]
        feedback = _feedback_lines(candidate.get("missing_skills") or [],
                                   evidence.get("listed_skills") or [])
        if feedback:
            parts.append("Feedback that may help with your next application:")
            parts.extend(feedback)
            parts.append("")
        if other_roles:
            roles = "; ".join(f"{r['title']} (match {r['score']:.0f})" for r in other_roles)
            parts.append(f"Based on your resume you may be a better fit for: {roles}.\n")
        if track:
            parts.append(track.strip() + "\n")
        parts.append("We wish you every success.\n\nBest regards,\nThe Hiring Team")
        body = "\n".join(parts)

    return {"subject": subject, "body": body}
