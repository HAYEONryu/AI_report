"""Copper-related news via Naver News search — multi-query, one batched AI pass (SPEC.md §4.3).

A single "구리" query pulls mostly Gyeonggi-do Guri-si (a city, not the metal)
news — NAVER_NEWS_QUERIES in config.py exists specifically to avoid that trap.
"""
import html
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from ai.summarize import summarize_news
from config import NAVER_NEWS_QUERIES, NAVER_NEWS_URL, NEWS_BLACKLIST_TERMS, NEWS_LOOKBACK_DAYS, NEWS_MAX_CANDIDATES, NEWS_MAX_FINAL
from schema import STATUS_FAILED, STATUS_OK, STATUS_STALE

logger = logging.getLogger(__name__)
_TAG_RE = re.compile(r"<[^>]+>")
_CACHE_PATH = Path("data/cache/news_latest.json")


def _load_cache():
    return json.loads(_CACHE_PATH.read_text(encoding="utf-8")) if _CACHE_PATH.exists() else None


def _save_cache(items):
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean_text(raw):
    return html.unescape(_TAG_RE.sub("", raw)).strip()


def _press_from_link(item):
    domain = urlparse(item.get("originallink") or item["link"]).netloc
    return domain.removeprefix("www.")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=30))
def _fetch_query(query, client_id, client_secret):
    resp = requests.get(
        NAVER_NEWS_URL,
        headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
        params={"query": query, "display": 30, "sort": "date"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def _is_within_lookback(pub_date_raw, now_utc):
    try:
        pub_date = parsedate_to_datetime(pub_date_raw)
    except (TypeError, ValueError):
        return False
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=timezone.utc)
    return (now_utc - pub_date) <= timedelta(days=NEWS_LOOKBACK_DAYS)


def _is_blacklisted(title):
    return any(term in title for term in NEWS_BLACKLIST_TERMS)


def collect_news(now_utc=None):
    """Returns (section_dict, errors_list) per SPEC.md §3 sections.news contract."""
    now_utc = now_utc or datetime.now(timezone.utc)
    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    cached = _load_cache()
    if not client_id or not client_secret:
        reason = "NAVER_CLIENT_ID/SECRET 미설정"
        if cached is not None:
            return {"status": STATUS_STALE, "items": cached}, [{"section": "news", "reason": reason, "fallback": "캐시 사용"}]
        return {"status": STATUS_FAILED, "reason": reason, "items": []}, [{"section": "news", "reason": reason, "fallback": "없음"}]

    errors = []
    seen_links = set()
    candidates = []
    for query in NAVER_NEWS_QUERIES:
        try:
            raw_items = _fetch_query(query, client_id, client_secret)
        except Exception as exc:
            logger.warning("naver news query '%s' failed: %s", query, exc)
            errors.append({"section": "news", "reason": f"'{query}' 검색 실패: {exc}", "fallback": "해당 쿼리 제외"})
            continue

        for raw in raw_items:
            title = _clean_text(raw["title"])
            if raw["link"] in seen_links or _is_blacklisted(title):
                continue
            if not _is_within_lookback(raw["pubDate"], now_utc):
                continue
            seen_links.add(raw["link"])
            candidates.append(
                {
                    "title": title,
                    "link": raw["link"],
                    "description": _clean_text(raw["description"]),
                    "press": _press_from_link(raw),
                    "published_at": parsedate_to_datetime(raw["pubDate"]).isoformat(),
                }
            )

    if not candidates:
        if len(errors) == len(NAVER_NEWS_QUERIES):
            if cached is not None:
                errors.append({"section": "news", "reason": "모든 쿼리 실패", "fallback": "캐시 사용"})
                return {"status": STATUS_STALE, "items": cached}, errors
            return {"status": STATUS_FAILED, "items": []}, errors
        return {"status": STATUS_OK, "items": []}, errors

    candidates.sort(key=lambda c: c["published_at"], reverse=True)
    candidates = candidates[:NEWS_MAX_CANDIDATES]

    scored = summarize_news(candidates)
    if scored is None:
        logger.warning("summarize_news failed — falling back to title+link only")
        errors.append({"section": "news", "reason": "AI 요약 실패", "fallback": "제목/링크만 노출"})
        items = [{**c, "summary": ""} for c in candidates[:NEWS_MAX_FINAL]]
    else:
        by_index = {s["index"]: s for s in scored if isinstance(s, dict) and "index" in s}
        enriched = []
        for i, c in enumerate(candidates):
            s = by_index.get(i, {})
            enriched.append({**c, "relevance": s.get("relevance", 1), "summary": s.get("summary", "")})
        enriched.sort(key=lambda c: c["relevance"], reverse=True)
        items = enriched[:NEWS_MAX_FINAL]

    _save_cache(items)
    return {"status": STATUS_OK, "items": items}, errors


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to cp949
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    result_section, result_errors = collect_news()
    print(json.dumps({"news": result_section, "errors": result_errors}, ensure_ascii=False, indent=2))
