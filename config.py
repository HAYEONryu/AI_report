"""Hardcoded constants: URLs, symbols, search terms, recipients.
No secrets here — those come from environment variables (see .env.example).
"""
import os

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

# --- AI models ---
AI_MODEL_EXTRACT = "claude-haiku-4-5-20251001"
AI_MODEL_SUMMARIZE = "claude-haiku-4-5-20251001"
AI_MODEL_COMMENTARY = "claude-sonnet-5"

# --- Delivery ---
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
MAIL_TO = os.environ.get("MAIL_TO", "hannau416@gmail.com")

# --- Anomaly flagging (rule-based, not AI) ---
ANOMALY_CHANGE_PCT_THRESHOLD = 20.0

# --- HTTP ---
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}
