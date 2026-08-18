"""Copper / WTI / USDKRW collector — a KST 15:00 intraday snapshot, not a daily close.

See SPEC.md §4.1. yfinance's `previousClose` (NY close) is a different basis
than our 15:00 KST snapshot and must never be used for the "전일 대비" figure.
"""
import csv
import io
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from config import (
    ANOMALY_CHANGE_PCT_THRESHOLD,
    DEFAULT_HEADERS,
    KST,
    PRICE_HISTORY_CSV,
    PRICE_SNAPSHOT_HOUR_KST,
    PRICE_SYMBOLS,
    STOOQ_FALLBACK_URLS,
)
from schema import STATUS_FAILED, STATUS_OK, STATUS_STALE

logger = logging.getLogger(__name__)
HISTORY_PATH = Path(PRICE_HISTORY_CSV)
CSV_FIELDS = ["date", "key", "price", "captured_at"]
BACKFILL_DAYS = 6  # yfinance 1m history covers ~7d; look back that far for gaps


def _read_history():
    if not HISTORY_PATH.exists():
        return []
    with HISTORY_PATH.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _append_history(rows):
    if not rows:
        return
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not HISTORY_PATH.exists()
    with HISTORY_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def _prev_snapshot(history, key, before_date_iso):
    """Most recent snapshot for `key` strictly before `before_date_iso` — handles weekends/holidays."""
    candidates = [r for r in history if r["key"] == key and r["date"] < before_date_iso]
    if not candidates:
        return None, None
    latest = max(candidates, key=lambda r: r["date"])
    return float(latest["price"]), latest["date"]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=30))
def _fetch_1m_history(symbol):
    return yf.Ticker(symbol).history(period="7d", interval="1m")


def _kst_snapshot(df, target_date_kst):
    """Last 1m bar at/before 15:00 KST on target_date_kst → (price, captured_at_iso)."""
    if df is None or df.empty:
        return None, None
    df_kst = df.tz_convert(ZoneInfo(KST))
    cutoff = datetime.combine(target_date_kst, datetime.min.time(), tzinfo=ZoneInfo(KST)).replace(
        hour=PRICE_SNAPSHOT_HOUR_KST
    )
    window = df_kst[(df_kst.index.date == target_date_kst) & (df_kst.index <= cutoff)]
    if window.empty:
        return None, None
    return float(window.iloc[-1]["Close"]), window.index[-1].isoformat()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=30))
def _fetch_stooq_daily(key):
    resp = requests.get(STOOQ_FALLBACK_URLS[key], headers=DEFAULT_HEADERS, timeout=15)
    resp.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    if not rows:
        return None, None
    last = rows[-1]
    return float(last["Close"]), last["Date"]


def _backfill_missing(df_by_symbol, history, today_kst):
    """Fill CSV gaps in the last BACKFILL_DAYS using 1m data already fetched — no extra API calls."""
    existing = {(r["key"], r["date"]) for r in history}
    new_rows = []
    for key, df in df_by_symbol.items():
        for offset in range(1, BACKFILL_DAYS + 1):
            day = today_kst - timedelta(days=offset)
            if (key, day.isoformat()) in existing:
                continue
            price, captured_at = _kst_snapshot(df, day)
            if price is not None:
                new_rows.append({"date": day.isoformat(), "key": key, "price": price, "captured_at": captured_at})
    _append_history(new_rows)
    history.extend({**r, "price": str(r["price"])} for r in new_rows)


def collect_prices(today_kst=None):
    """Returns (section_dict, errors_list) per SPEC.md §3 sections.prices contract."""
    today_kst = today_kst or datetime.now(ZoneInfo(KST)).date()
    cutoff_iso = datetime.combine(today_kst, datetime.min.time(), tzinfo=ZoneInfo(KST)).replace(
        hour=PRICE_SNAPSHOT_HOUR_KST
    ).isoformat()
    history = _read_history()
    errors = []
    items = []
    section_status = STATUS_OK

    # Phase 1: fetch 1m history for every symbol up front, then backfill CSV gaps
    # from it. Backfilling before computing today's prev_price means a cold-start
    # run (or a run after a multi-day outage) still gets a real comparison instead
    # of a spurious "비교 불가" — the history didn't exist on disk yet, but the
    # data to fill it was already in hand.
    df_by_symbol = {}
    today_snapshot = {}
    for key, meta in PRICE_SYMBOLS.items():
        try:
            df = _fetch_1m_history(meta["symbol"])
            df_by_symbol[key] = df
            today_snapshot[key] = _kst_snapshot(df, today_kst)
        except Exception as exc:
            logger.warning("yfinance 1m fetch failed for %s: %s", meta["symbol"], exc)
            df_by_symbol[key] = None
            today_snapshot[key] = (None, None)
    _backfill_missing(df_by_symbol, history, today_kst)

    for key, meta in PRICE_SYMBOLS.items():
        symbol = meta["symbol"]
        price, captured_at = today_snapshot[key]
        source_note = None

        if price is None:
            section_status = STATUS_STALE
            try:
                price, captured_at = _fetch_stooq_daily(key)
                source_note = "전일 종가 기준(대체)"
            except Exception as exc:
                logger.error("stooq fallback failed for %s: %s", symbol, exc)
                errors.append({"section": "prices", "reason": f"{key}: 시세 수집 실패 ({exc})", "fallback": "없음"})
                continue

        prev_price, prev_basis = _prev_snapshot(history, key, today_kst.isoformat())
        change = round(price - prev_price, 6) if prev_price is not None else None
        change_pct = round((change / prev_price) * 100, 4) if change and prev_price else (0.0 if change == 0 else None)

        item = {
            "key": key,
            "label": meta["label"],
            "price": round(price, 6),
            "unit": meta["unit"],
            "prev_price": prev_price,
            "prev_basis": prev_basis,
            "change": change,
            "change_pct": change_pct,
        }
        if source_note:
            item["source_note"] = source_note
        if change_pct is not None and abs(change_pct) > ANOMALY_CHANGE_PCT_THRESHOLD:
            item["anomaly"] = True
            errors.append({"section": "prices", "reason": f"{key}: 전일 대비 {change_pct}% 이상치", "fallback": None})
        items.append(item)

        already_recorded = any(r["date"] == today_kst.isoformat() and r["key"] == key for r in history)
        if captured_at and not already_recorded:
            _append_history([{"date": today_kst.isoformat(), "key": key, "price": price, "captured_at": captured_at}])
            history.append({"date": today_kst.isoformat(), "key": key, "price": str(price), "captured_at": captured_at})

    if not items:
        return {"status": STATUS_FAILED, "reason": "모든 시세 수집 실패", "items": []}, errors

    section = {
        "status": section_status,
        "source": "yfinance" if section_status == STATUS_OK else "stooq (fallback)",
        "as_of": cutoff_iso,
        "items": items,
    }
    return section, errors


if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to cp949
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    result_section, result_errors = collect_prices()
    print(json.dumps({"prices": result_section, "errors": result_errors}, ensure_ascii=False, indent=2, default=str))
