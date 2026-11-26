"""contact.py: pull the contact email out of resume text."""

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def extract_email(text: str) -> str:
    """Return the first email address in the text, lower-cased, or ''."""
    match = _EMAIL.search(text or "")
    return match.group(0).lower().rstrip(".") if match else ""
