"""Hardcoded constants: URLs, symbols, search terms, recipients.
No secrets here — those come from environment variables (see .env.example).
"""
import os

from dotenv import load_dotenv

# Windows Task Scheduler doesn't inherit shell env vars, so the local daily
# run depends on this to pick up secrets from .env. Harmless no-op in CI,
# where the real env vars are already set by GitHub Actions.
load_dotenv()

# --- Timezone ---
KST = "Asia/Seoul"

# --- Prices (collectors/prices.py) ---
PRICE_SYMBOLS = {
    "copper": {"symbol": "HG=F", "label": "구리 선물 (COMEX HG)", "unit": "USD/lb"},
    "wti": {"symbol": "CL=F", "label": "WTI 원유", "unit": "USD/bbl"},
    "usdkrw": {"symbol": "KRW=X", "label": "USD-KRW 환율", "unit": "KRW"},
}
PRICE_SNAPSHOT_HOUR_KST = 15  # 15:00 KST snapshot
STOOQ_FALLBACK_URLS = {
    "copper": "https://stooq.com/q/d/l/?s=hg.f&i=d",
    "wti": "https://stooq.com/q/d/l/?s=cl.f&i=d",
    "usdkrw": "https://stooq.com/q/d/l/?s=usdkrw&i=d",
}
PRICE_HISTORY_CSV = "data/history/prices.csv"

# --- Economic calendar (collectors/calendar.py) ---
# Countries: US=5, China=37. Weekly view, Seoul timezone offset id=88 confirmed via spike.
INVESTING_CALENDAR_URL = (
    "https://sslecal2.investing.com/?"
    "columns=exc_flag,exc_currency,exc_importance,exc_actual,exc_forecast,exc_previous"
    "&features=datepicker,timezone"
    "&countries=5,37"
    "&calType=week"
    "&timeZone=88"
    "&lang=1"
)
INVESTING_MIN_IMPORTANCE = 2  # 2=medium, 3=high; icon-count based
CALENDAR_CACHE_TEMPLATE = "data/cache/calendar_{week_start}.json"

# --- News (collectors/news.py) ---
NAVER_NEWS_QUERIES = ["전기동", "구리 가격", "LME 구리", "구리 선물", "비철금속", "동가격"]
NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
NEWS_LOOKBACK_DAYS = 3
NEWS_MAX_CANDIDATES = 30
NEWS_MAX_FINAL = 10
NEWS_BLACKLIST_TERMS = ["구리시", "구리역", "구리도매시장", "남양주"]

# --- Inventory PDF (collectors/inventory.py) ---
NHF_BOARD_URL = "https://www.futures.co.kr/content/Getcontent.do?content=3000031"
NHF_BASE_URL = "https://www.futures.co.kr"

# --- AI models (OpenAI) ---
AI_MODEL_EXTRACT = "gpt-4o-mini"
AI_MODEL_SUMMARIZE = "gpt-4o-mini"
AI_MODEL_COMMENTARY = "gpt-4o"

# --- Delivery ---
# Correct host is mail.ihoban.co.kr (typo'd as mail.hoban.co.kr originally;
# mail.taihan.com was a dead-end guess based on the AD domain, wrong on the
# server side too). Port 587 is open here (25 also open, 465/995 closed) —
# matches the original STARTTLS port the user intended. Login/mailbox is
# @taihan.com, not @taihan.co.kr — confirmed live (235 auth success).
SMTP_HOST = "mail.ihoban.co.kr"
SMTP_PORT = 587
MAIL_TO = os.environ.get("MAIL_TO", "hayeon@taihan.com")

# --- Anomaly flagging (rule-based, not AI) ---
ANOMALY_CHANGE_PCT_THRESHOLD = 20.0

# --- HTTP ---
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}
