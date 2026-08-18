"""Daily commentary generated from the fully assembled report sections (SPEC.md §5.3)."""
import json
import logging

from ai.client import call_json
from config import AI_MODEL_COMMENTARY

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "전선/케이블 제조사 실무자를 위한 원자재 브리핑을 작성한다. "
    "headline 1줄, body 3~5문장, implication(원가 관점 시사점) 1줄로 구성한다. "
    "주어진 데이터에 없는 수치나 사건은 절대 언급하지 않는다. 숫자는 입력값을 그대로 인용한다. "
    'JSON으로만 응답한다. 형식: {"headline": "...", "body": ["...", "..."], "implication": "..."}'
)


def write_commentary(sections):
    """sections: the report's fully assembled `sections` dict (prices/calendar/news/inventory).
    Returns {"headline", "body", "implication"}, or None if the AI call failed —
    callers omit the commentary section entirely on failure (SPEC.md §5 AI-failure table)."""
    user = json.dumps(sections, ensure_ascii=False, default=str)
    try:
        result = call_json(SYSTEM_PROMPT, user, AI_MODEL_COMMENTARY, max_tokens=1000)
    except Exception as exc:
        logger.error("write_commentary call failed: %s", exc)
        return None
    if not isinstance(result, dict) or not all(k in result for k in ("headline", "body", "implication")):
        return None
    return result
