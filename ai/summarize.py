"""Batch news relevance scoring + Korean 2-sentence summaries — one call for all candidates (SPEC.md §5.2)."""
import json
import logging

from ai.client import call_json
from config import AI_MODEL_SUMMARIZE

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "구리/전기동 시황 관련성을 1~5로 평가하고, 관련 기사에 한해 한국어 2문장 요약을 작성한다. "
    "경기도 구리시 등 지명 '구리'와 무관한 기사는 relevance를 1로 매기고 summary는 빈 문자열로 둔다. "
    'JSON 배열로만 응답한다. 형식: [{"index": <int>, "relevance": <1-5>, "summary": "<string>"}]'
)


def summarize_news(candidates):
    """candidates: list of {title, description, press}. Returns a list of
    {index, relevance, summary} aligned by index, or None if the AI call failed —
    callers fall back to title+link only (SPEC.md §5 AI-failure table)."""
    if not candidates:
        return []
    payload = [
        {"index": i, "title": c["title"], "description": c.get("description", ""), "press": c.get("press", "")}
        for i, c in enumerate(candidates)
    ]
    try:
        result = call_json(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False), AI_MODEL_SUMMARIZE, max_tokens=4000)
    except Exception as exc:
        logger.error("summarize_news call failed: %s", exc)
        return None
    return result if isinstance(result, list) else None
