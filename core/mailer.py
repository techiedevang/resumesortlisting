"""
mailer.py
---------
Delivers a message to a candidate.

Two modes, chosen by environment variables:

* outbox (default): nothing leaves the machine. The message is saved so it can
  be shown in the app's Outbox. This is the safe mode for demos and testing.
* smtp: set SMTP_HOST (and usually SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
  SMTP_PORT) to send real email. With Gmail, use an app password.
"""

import os
import smtplib
from email.message import EmailMessage


def mail_mode() -> str:
    return "smtp" if os.environ.get("SMTP_HOST") else "outbox"


def send_mail(to_addr: str, subject: str, body: str):
    """Return (delivery, error). delivery is 'saved', 'sent' or 'failed'."""
    if mail_mode() == "outbox":
        return "saved", ""

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM") or user

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            if os.environ.get("SMTP_TLS", "true").lower() != "false":
                server.starttls()
            if user:
                server.login(user, password)
            server.send_message(msg)
        return "sent", ""
    except Exception as exc:  # noqa: BLE001 - report any delivery failure
        return "failed", str(exc)
