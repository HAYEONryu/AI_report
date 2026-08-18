"""Pipeline orchestration: collect ×4 → AI commentary → render → deliver.

SPEC.md §8 rule 1 is the load-bearing constraint here: a failing collector
degrades its own section (status stale/failed) and gets appended to
report.errors — it never raises past _run_collector. The goal is "a report
lands at 16:00", not a perfect one.
"""
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ai.commentary import write_commentary
from collectors.calendar import collect_calendar
from collectors.inventory import collect_inventory
from collectors.news import collect_news
from collectors.prices import collect_prices
from config import KST, PRICE_SNAPSHOT_HOUR_KST
from deliver import notify_webhook, send_report
from render import render_report
from schema import validate_report

logger = logging.getLogger(__name__)
DEFAULT_COMMENTARY = {"headline": "코멘터리 생성 실패", "body": [], "implication": ""}


def _sleep_until_target(target_hour_kst):
    """No-op once the target time has passed — otherwise a `workflow_dispatch`
    run (or local test) triggered after 15:00 KST would block for ~24h instead
    of running immediately (SPEC.md §7.2 assumes the cron always fires before
    the target; manual runs don't)."""
    now = datetime.now(ZoneInfo(KST))
    target = now.replace(hour=target_hour_kst, minute=0, second=0, microsecond=0)
    wait_seconds = (target - now).total_seconds()
    if wait_seconds > 0:
        logger.info("sleeping %.0fs until %s KST", wait_seconds, target.time())
        time.sleep(wait_seconds)


def _run_collector(name, fn):
    try:
        return fn()
    except Exception as exc:
        logger.error("collector %s raised unexpectedly: %s", name, exc)
        return {"status": "failed", "reason": f"수집기 예외: {exc}"}, [
            {"section": name, "reason": str(exc), "fallback": "없음"}
        ]


def build_report(today_kst=None, skip_sleep=False):
    if not skip_sleep:
        _sleep_until_target(PRICE_SNAPSHOT_HOUR_KST)

    today_kst = today_kst or datetime.now(ZoneInfo(KST)).date()
    errors = []
    sections = {}
    for name, fn in (
        ("prices", collect_prices),
        ("calendar", collect_calendar),
        ("news", collect_news),
        ("inventory", collect_inventory),
    ):
        section, section_errors = _run_collector(name, fn)
        sections[name] = section
        errors += section_errors

    commentary = write_commentary(sections)
    if commentary is None:
        errors.append({"section": "commentary", "reason": "AI 코멘터리 생성 실패", "fallback": "기본 문구 사용"})
        commentary = DEFAULT_COMMENTARY

    report = {
        "report_date": today_kst.isoformat(),
        "generated_at": datetime.now(ZoneInfo(KST)).isoformat(),
        "sections": sections,
        "commentary": commentary,
        "errors": errors,
    }

    validation_errors = validate_report(report)
    if validation_errors:
        logger.error("report failed schema validation: %s", validation_errors)
        report["errors"].append({"section": "schema", "reason": str(validation_errors), "fallback": "없음"})

    return report


def save_report(report):
    path = Path("data/reports") / f"{report['report_date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def _short_summary(report):
    items = {i["key"]: i for i in report["sections"]["prices"].get("items", [])}
    parts = []
    for key, label in (("copper", "구리"), ("wti", "WTI"), ("usdkrw", "USDKRW")):
        item = items.get(key)
        if item and item.get("change_pct") is not None:
            parts.append(f"{label} {item['change_pct']:+.1f}%")
    return " / ".join(parts) or "리포트 발송 완료"


def main():
    skip_sleep = "--now" in sys.argv
    report = build_report(skip_sleep=skip_sleep)
    save_report(report)

    try:
        html = render_report(report)
    except Exception as exc:
        logger.error("render failed: %s", exc)
        notify_webhook(success=False, summary=f"렌더링 실패: {exc}")
        return 1

    try:
        send_report(report, html)
    except Exception as exc:
        logger.error("send failed: %s", exc)
        notify_webhook(success=False, summary=f"메일 발송 실패: {exc}")
        return 1

    notify_webhook(success=True, summary=_short_summary(report))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to cp949
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    raise SystemExit(main())
