"""Standalone SMTP connect/auth test — iterate on credentials without
touching the full pipeline. One attempt per run, on purpose: repeated
auto-retries against a real corporate account risk locking it out, so this
never loops or guesses — you control each attempt.

Usage:
    python mailtest.py                # SMTP_USER from .env, as-is
    python mailtest.py hayeon         # try a different login username
                                       # (same SMTP_APP_PASSWORD from .env)
"""
import os
import sys
from email.mime.text import MIMEText
import smtplib

from config import MAIL_TO, SMTP_HOST, SMTP_PORT

smtp_user = sys.argv[1] if len(sys.argv) > 1 else os.environ["SMTP_USER"]
smtp_password = os.environ["SMTP_APP_PASSWORD"]

print(f"Connecting to {SMTP_HOST}:{SMTP_PORT} as '{smtp_user}' -> {MAIL_TO}")

msg = MIMEText("mailtest.py 연결 테스트입니다.", "plain", "utf-8")
msg["Subject"] = "[테스트] SMTP 연결 확인"
msg["From"] = smtp_user
msg["To"] = MAIL_TO

try:
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        server.set_debuglevel(1)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
    print("\nSUCCESS: 메일 발송 성공")
except Exception as exc:
    print(f"\nFAILED: {type(exc).__name__}: {exc}")
    raise
