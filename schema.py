"""Report data contract (SPEC.md §3) + validation.

Plain dicts, not a class hierarchy — one JSON document in, one JSON document
out. Validation is manual (no pydantic in requirements.txt); every collector
and every AI-produced JSON must pass validate_report() before it's trusted.
"""

STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_FAILED = "failed"
VALID_STATUSES = {STATUS_OK, STATUS_STALE, STATUS_FAILED}


def _require(errors, condition, message):
    if not condition:
        errors.append(message)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_prices_section(section):
    errors = []
    _require(errors, section.get("status") in VALID_STATUSES, "prices.status invalid")
    for item in section.get("items", []):
        for key in ("key", "label", "price", "unit"):
            _require(errors, key in item, f"prices.items[].{key} missing")
        if "price" in item:
            _require(errors, _is_number(item["price"]), "prices.items[].price not numeric")
        # prev_price/change may legitimately be null (no prior snapshot yet)
        if item.get("change") is not None and item.get("prev_price") is not None:
            expected = round(item["price"] - item["prev_price"], 6)
            _require(
                errors,
                abs(expected - round(item["change"], 6)) < 1e-4,
                f"prices.items[{item.get('key')}].change != price - prev_price",
            )
    return errors


def validate_calendar_section(section):
    errors = []
    _require(errors, section.get("status") in VALID_STATUSES, "calendar.status invalid")
    for ev in section.get("events", []):
        for key in ("date", "country", "importance", "name"):
            _require(errors, key in ev, f"calendar.events[].{key} missing")
        _require(errors, ev.get("country") in ("US", "CN"), "calendar.events[].country not US/CN")
        _require(errors, ev.get("importance") in (2, 3), "calendar.events[].importance not 2/3")
    return errors


def validate_news_section(section):
    errors = []
    _require(errors, section.get("status") in VALID_STATUSES, "news.status invalid")
    for item in section.get("items", []):
        for key in ("title", "link", "summary"):
            _require(errors, key in item, f"news.items[].{key} missing")
        if "relevance" in item:
            _require(errors, item["relevance"] in range(1, 6), "news.items[].relevance not 1-5")
    return errors


def validate_inventory_section(section):
    """LME/COMEX rows must be numeric and change == current - prev (§4.4)."""
    errors = []
    _require(errors, section.get("status") in VALID_STATUSES, "inventory.status invalid")
    if section.get("status") != STATUS_OK:
        return errors
    for market in ("lme", "comex"):
        rows = section.get(market, [])
        _require(errors, len(rows) > 0, f"inventory.{market} empty for status=ok")
        for row in rows:
            for key in ("metal", "prev", "current", "change"):
                _require(errors, key in row, f"inventory.{market}[].{key} missing")
                if key in row:
                    _require(errors, _is_number(row[key]) or key == "metal", f"inventory.{market}[].{key} not numeric")
            if all(_is_number(row.get(k)) for k in ("prev", "current", "change")):
                _require(
                    errors,
                    row["change"] == row["current"] - row["prev"],
                    f"inventory.{market}[{row.get('metal')}].change != current - prev",
                )
    return errors


def validate_report(report):
    """Returns list of error strings; empty list == valid."""
    errors = []
    _require(errors, "report_date" in report, "report_date missing")
    _require(errors, "generated_at" in report, "generated_at missing")
    sections = report.get("sections", {})
    for name in ("prices", "calendar", "news", "inventory"):
        _require(errors, name in sections, f"sections.{name} missing")

    if "prices" in sections:
        errors += [f"sections.prices.{e}" for e in validate_prices_section(sections["prices"])]
    if "calendar" in sections:
        errors += [f"sections.calendar.{e}" for e in validate_calendar_section(sections["calendar"])]
    if "news" in sections:
        errors += [f"sections.news.{e}" for e in validate_news_section(sections["news"])]
    if "inventory" in sections:
        errors += [f"sections.inventory.{e}" for e in validate_inventory_section(sections["inventory"])]
    return errors


def _demo():
    """Self-check: a well-formed report passes, an inconsistent one fails."""
    good = {
        "report_date": "2026-08-18",
        "generated_at": "2026-08-18T16:00:00+09:00",
        "sections": {
            "prices": {"status": STATUS_OK, "items": [{"key": "copper", "label": "구리", "price": 4.5, "unit": "USD/lb"}]},
            "calendar": {"status": STATUS_OK, "events": [{"date": "2026-08-18", "country": "US", "importance": 3, "name": "CPI"}]},
            "news": {"status": STATUS_OK, "items": [{"title": "t", "link": "l", "summary": "s"}]},
            "inventory": {
                "status": STATUS_OK,
                "lme": [{"metal": "Copper", "prev": 100, "current": 110, "change": 10}],
                "comex": [{"metal": "Copper", "prev": 50, "current": 40, "change": -10}],
            },
        },
    }
    assert validate_report(good) == [], validate_report(good)

    bad = {**good, "sections": {**good["sections"]}}
    bad["sections"]["inventory"] = {
        "status": STATUS_OK,
        "lme": [{"metal": "Copper", "prev": 100, "current": 110, "change": 999}],  # wrong on purpose
        "comex": [],
    }
    errs = validate_report(bad)
    assert any("change != current - prev" in e for e in errs), errs
    print("schema self-check passed")


if __name__ == "__main__":
    _demo()
