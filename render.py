"""Render a validated report dict to HTML via templates/report.html.j2.

Standalone-runnable: `python render.py` renders data/mock_report.json to
data/reports/preview.html for a visual check, without touching collectors.
"""
import json
import logging
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from schema import validate_report

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_report(report: dict) -> str:
    errors = validate_report(report)
    if errors:
        # Rendering a broken report is worse than crashing loudly here —
        # every upstream section is supposed to self-validate first.
        raise ValueError(f"report failed schema validation: {errors}")
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("report.html.j2")
    return template.render(report=report)


if __name__ == "__main__":
    mock_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "data" / "mock_report.json"
    report = json.loads(mock_path.read_text(encoding="utf-8"))
    html = render_report(report)
    out_path = Path(__file__).parent / "data" / "reports" / "preview.html"
    out_path.write_text(html, encoding="utf-8")
    logger.info("rendered preview to %s", out_path)
    print(f"rendered: {out_path}")
