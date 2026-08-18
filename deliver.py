"""Gmail SMTP delivery + a separate webhook channel for success/failure alerts.

The webhook is deliberately independent of email (SPEC.md §6.3) — if SMTP
itself is what's broken, email can't be the channel that tells anyone.
"""
import json
import logging
import os
import smtplib
from datetime import date
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from config import MAIL_TO, SMTP_HOST, SMTP_PORT

logger = logging.getLogger(__name__)
PRICE_LABELS = {"copper": "구리", "wti": "WTI", "usdkrw": "USDKRW"}


def _subject(report):
    d = date.fromisoformat(report["report_date"])
    items = {i["key"]: i for i in report["sections"]["prices"].get("items", [])}
    parts = [f"[일일 원자재] {d.month}/{d.day}"]
    for key, label in PRICE_LABELS.items():
        item = items.get(key)
        if not item:
            continue
        if key == "usdkrw" and item.get("price") is not None:
            parts.append(f"{label} {item['price']:,.2f}")
        elif item.get("change_pct") is not None:
            parts.append(f"{label} {item['change_pct']:+.1f}%")
    return " / ".join(parts)


def send_report(report, html):
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_APP_PASSWORD"]

    msg = MIMEMultipart("mixed")
    msg["Subject"] = _subject(report)
    msg["From"] = smtp_user
    msg["To"] = MAIL_TO
    msg.attach(MIMEText(html, "html", "utf-8"))

    attachment = MIMEApplication(json.dumps(report, ensure_ascii=False, indent=2, default=str).encode("utf-8"))
    attachment.add_header("Content-Disposition", "attachment", filename="report.json")
    msg.attach(attachment)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
    logger.info("report emailed to %s", MAIL_TO)


def notify_webhook(success, summary):
    webhook_url = os.environ.get("ALERT_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("ALERT_WEBHOOK_URL 미설정 — 알림 생략")
        return
    icon = "✅" if success else "\U0001f6a8"
    payload = {"text": f"{icon} 일일 원자재 리포트: {summary}"}
    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as exc:
        logger.error("webhook notify failed: %s", exc)
