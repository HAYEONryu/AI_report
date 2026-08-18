"""NH선물 일일금속시황 PDF → LME/COMEX inventory (SPEC.md §4.4).

Step 0 confirmed the board listing is plain HTML (no JS needed) and file
attachments (`BbsFileDown.do`) sit directly in each post's row, so this stays
on requests + BeautifulSoup — no Playwright. Table parsing is deliberately
NOT done with coordinates/regex (spec explicitly forbids it — a layout change
would silently produce wrong numbers); instead we hand the matched PDF page
text to ai.extract.extract_inventory() and validate its structured answer.
"""
import io
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pdfplumber
import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from ai.extract import extract_inventory
from config import DEFAULT_HEADERS, KST, NHF_BASE_URL, NHF_BOARD_URL
from schema import STATUS_FAILED, STATUS_OK, STATUS_STALE

logger = logging.getLogger(__name__)
_CACHE_PATH = Path("data/cache/inventory_latest.json")
_KEYWORD_RE = re.compile(r"LME Stock|COMEX", re.IGNORECASE)
_DATE8_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})(?!\d)")
_DATE_DOT_RE = re.compile(r"(20\d{2})[.\-](\d{2})[.\-](\d{2})")


def _load_cache():
    return json.loads(_CACHE_PATH.read_text(encoding="utf-8")) if _CACHE_PATH.exists() else None


def _save_cache(section):
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(section, ensure_ascii=False, indent=2), encoding="utf-8")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=30))
def _get(session, url):
    resp = session.get(url, headers=DEFAULT_HEADERS, timeout=20)
    resp.raise_for_status()
    return resp


def _list_posts(html):
    """Each post row carries its own PDF attachment links — return them in
    document order (newest first, per the board's own sort)."""
    soup = BeautifulSoup(html, "lxml")
    posts = []
    for row in soup.find_all("tr"):
        file_links = [a for a in row.find_all("a", href=True) if "BbsFileDown.do" in a["href"]]
        if not file_links:
            continue
        posts.append(
            {
                "row_text": row.get_text(" ", strip=True),
                "file_urls": [urljoin(NHF_BASE_URL, a["href"]) for a in file_links],
            }
        )
    return posts


def _extract_date(row_text, fallback):
    m = _DATE8_RE.search(row_text) or _DATE_DOT_RE.search(row_text)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else fallback


def _select_post(posts, today_kst):
    if not posts:
        return None
    today_markers = (today_kst.strftime("%Y.%m.%d"), today_kst.strftime("%Y%m%d"))
    for post in posts:
        if any(marker in post["row_text"] for marker in today_markers):
            return post
    return posts[0]


def _relevant_pdf_text(pdf_bytes):
    """Pages mentioning LME Stocks / COMEX only — never the whole PDF (keeps
    the AI call small and on-topic)."""
    matched = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if _KEYWORD_RE.search(text):
                matched.append(text)
    return "\n\n".join(matched)


def collect_inventory(today_kst=None):
    """Returns (section_dict, errors_list) per SPEC.md §3 sections.inventory contract."""
    today_kst = today_kst or datetime.now(ZoneInfo(KST)).date()
    cached = _load_cache()

    try:
        session = requests.Session()
        listing = _get(session, NHF_BOARD_URL)
        post = _select_post(_list_posts(listing.text), today_kst)
        if post is None:
            raise ValueError("게시물 목록에서 첨부파일이 있는 행을 찾지 못함")

        source_date = _extract_date(post["row_text"], fallback=today_kst.isoformat())
        page_text = ""
        matched_url = None
        for file_url in post["file_urls"]:
            pdf_bytes = _get(session, file_url).content
            page_text = _relevant_pdf_text(pdf_bytes)
            if page_text:
                matched_url = file_url
                break
        if not page_text:
            raise ValueError("첨부 PDF에서 'LME Stock'/'COMEX' 페이지를 찾지 못함")

        extracted = extract_inventory(page_text)
        if extracted is None:
            raise ValueError("AI 추출/검증 실패")

        section = {"status": STATUS_OK, "source_date": source_date, "source_url": matched_url, **extracted}
        _save_cache(section)
        return section, []

    except Exception as exc:
        logger.warning("inventory collection failed: %s", exc)
        if cached is not None:
            stale = {**cached, "status": STATUS_STALE}
            return stale, [{"section": "inventory", "reason": str(exc), "fallback": f"{cached.get('source_date')} 캐시 사용"}]
        return (
            {"status": STATUS_FAILED, "reason": str(exc), "lme": [], "comex": []},
            [{"section": "inventory", "reason": str(exc), "fallback": "캐시 없음"}],
        )


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to cp949
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    result_section, result_errors = collect_inventory()
    print(json.dumps({"inventory": result_section, "errors": result_errors}, ensure_ascii=False, indent=2))
