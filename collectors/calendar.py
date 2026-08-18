"""US/China weekly economic calendar via investing.com's official iframe widget (SPEC.md §4.2).

The general investing.com API returns 403 (Cloudflare). Plain `requests`/`curl`
against the widget host *also* 403 here — Cloudflare bot management blocks on
TLS fingerprint (JA3) alone, independent of headers. `curl_cffi` impersonates a
real Chrome TLS handshake to get past that, and it works reliably from a local
machine — but from GitHub Actions' IP range, EVERY impersonated profile still
got 403'd (confirmed live: chrome124/136/146, firefox147 all blocked). That
points at IP reputation, not TLS fingerprint — GH Actions IPs are well-known
scraping infrastructure. So in production this goes through a tiny Cloudflare
Worker (cloudflare-worker/calendar-proxy.js) that fetches investing.com from
Cloudflare's own edge and hands the HTML back; GH Actions just calls our own
worker over plain `requests`, no impersonation needed for that leg. Locally
(CALENDAR_PROXY_URL unset), it falls back to the direct curl_cffi path.
Neither path executes JS or renders a DOM, so neither crosses the "no
Playwright" line.

Verified against a real fetch: the events table is `#ecEventsTable`, the date
separator's `theDay` class sits on a child `<td>` (not the `<tr>` itself —
easy to get wrong, and the first version of this file did), and importance
icons are `grayFullBullishIcon` (filled) vs `grayEmptyBullishIcon` (empty) —
both carry "gray", so "Full" vs "Empty" is the only reliable signal, not the
color. If _parse_events() ever returns 0 events from a 200 response, that's
still treated as a parse failure and falls back to cache, in case the markup
changes again later.
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config import CALENDAR_CACHE_TEMPLATE, INVESTING_CALENDAR_URL, INVESTING_MIN_IMPORTANCE, KST
from schema import STATUS_FAILED, STATUS_OK, STATUS_STALE

logger = logging.getLogger(__name__)
CURRENCY_TO_COUNTRY = {"USD": "US", "CNY": "CN"}

# Cloudflare's TLS-fingerprint blocklist shifts over time (chrome124 got
# blocked from GitHub Actions' IP range even though it passed locally) — try
# a few current profiles rather than betting the whole collector on one.
# Only used as the local/dev fallback; production goes through the proxy below.
_IMPERSONATE_PROFILES = ("chrome136", "chrome146", "firefox147")


def _fetch_html():
    proxy_url = os.environ.get("CALENDAR_PROXY_URL")
    if proxy_url:
        return _fetch_via_proxy(proxy_url)

    last_exc = None
    for profile in _IMPERSONATE_PROFILES:
        try:
            return _fetch_with_profile(profile)
        except Exception as exc:
            logger.warning("investing.com fetch failed with impersonate=%s: %s", profile, exc)
            last_exc = exc
    raise last_exc


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=30))
def _fetch_via_proxy(proxy_url):
    resp = requests.get(proxy_url, timeout=30)
    resp.raise_for_status()
    return resp.text


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, max=15))
def _fetch_with_profile(profile):
    resp = cf_requests.get(INVESTING_CALENDAR_URL, impersonate=profile, timeout=30)
    resp.raise_for_status()
    return resp.text


def _importance_from_icons(td):
    """Importance = count of *filled* bull icons among the 3 rendered per row."""
    if td is None:
        return None
    icons = td.find_all("i")
    if not icons:
        return None
    filled = [i for i in icons if "full" in " ".join(i.get("class", [])).lower()]
    return len(filled) or None


def _cell_text(row, *, td_id_prefix=None, css_class=None):
    td = None
    if td_id_prefix:
        td = row.find("td", id=lambda v: v and v.startswith(td_id_prefix))
    if td is None and css_class:
        td = row.find("td", class_=css_class)
    if td is None:
        return None
    text = td.get_text(strip=True)
    return text if text and text not in ("\xa0",) else None


def _parse_events(html):
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="ecEventsTable") or soup
    current_date = None
    events = []

    for row in table.find_all("tr"):
        # The "theDay" class sits on a <td> inside the row, not on the <tr> itself.
        day_cell = row.find("td", class_="theDay")
        if day_cell is not None:
            m = re.search(r"([A-Za-z]+ \d{1,2}, \d{4})", day_cell.get_text(strip=True))
            if m:
                current_date = datetime.strptime(m.group(1), "%B %d, %Y").date()
            continue

        row_id = row.get("id") or ""
        if not row_id.startswith("eventRowId_") or current_date is None:
            continue

        currency = _cell_text(row, css_class="flagCur")
        country = CURRENCY_TO_COUNTRY.get(currency)
        if country is None:
            continue

        importance = _importance_from_icons(row.find("td", class_="sentiment"))
        if importance is None or importance < INVESTING_MIN_IMPORTANCE:
            continue

        name = _cell_text(row, css_class="event")
        if not name:
            continue

        events.append(
            {
                "date": current_date.isoformat(),
                "time_kst": _cell_text(row, css_class="time") or "00:00",
                "country": country,
                "importance": min(importance, 3),
                "name": name,
                "actual": _cell_text(row, td_id_prefix="eventActual_"),
                "forecast": _cell_text(row, td_id_prefix="eventForecast_"),
                "previous": _cell_text(row, td_id_prefix="eventPrevious_"),
                "is_released": _cell_text(row, td_id_prefix="eventActual_") is not None,
            }
        )
    return events


def _week_bounds(today_kst):
    monday = today_kst - timedelta(days=today_kst.weekday())
    return monday, monday + timedelta(days=6)


def _cache_path(week_start):
    return Path(CALENDAR_CACHE_TEMPLATE.format(week_start=week_start.isoformat()))


def _load_cache(week_start):
    path = _cache_path(week_start)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _save_cache(week_start, events):
    path = _cache_path(week_start)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_calendar(today_kst=None, force_full_fetch=None):
    """Monday: full-week (re)fetch. Other weekdays: refresh only `actual` values
    against the cached weekly schedule — this week's events rarely change, so
    most weekday failures just mean "keep yesterday's schedule, retry actual
    values tomorrow" instead of losing the whole section (SPEC.md §4.2)."""
    today_kst = today_kst or datetime.now(ZoneInfo(KST)).date()
    week_start, week_end = _week_bounds(today_kst)
    is_monday = today_kst.weekday() == 0
    need_full_fetch = is_monday if force_full_fetch is None else force_full_fetch
    errors = []
    cached = _load_cache(week_start)

    try:
        fresh_events = _parse_events(_fetch_html())
        if not fresh_events:
            raise ValueError("파싱된 이벤트 0건 — investing.com 마크업 구조 변경 가능성")
    except Exception as exc:
        logger.warning("calendar fetch/parse failed: %s", exc)
        if cached is None:
            return (
                {"status": STATUS_FAILED, "week_start": week_start.isoformat(), "week_end": week_end.isoformat(), "events": []},
                [{"section": "calendar", "reason": str(exc), "fallback": "캐시 없음"}],
            )
        return (
            {"status": STATUS_STALE, "week_start": week_start.isoformat(), "week_end": week_end.isoformat(), "events": cached},
            [{"section": "calendar", "reason": str(exc), "fallback": f"{week_start.isoformat()} 캐시 사용"}],
        )

    if need_full_fetch or cached is None:
        _save_cache(week_start, fresh_events)
        final_events = fresh_events
    else:
        # Patch `actual` into the cached schedule by (date, name); keep the rest as-is.
        fresh_by_key = {(e["date"], e["name"]): e for e in fresh_events}
        final_events = []
        for e in cached:
            match = fresh_by_key.get((e["date"], e["name"]))
            final_events.append({**e, "actual": match["actual"], "is_released": match["is_released"]} if match else e)
        _save_cache(week_start, final_events)

    section = {"status": STATUS_OK, "week_start": week_start.isoformat(), "week_end": week_end.isoformat(), "events": final_events}
    return section, errors


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to cp949; Korean error text has non-cp949 punctuation
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    result_section, result_errors = collect_calendar()
    print(json.dumps({"calendar": result_section, "errors": result_errors}, ensure_ascii=False, indent=2))
