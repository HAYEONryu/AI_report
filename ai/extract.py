"""PDF inventory table extraction — unstructured page text → structured JSON (SPEC.md §5.1)."""
import logging

from ai.client import call_json
from config import AI_MODEL_EXTRACT
from schema import STATUS_OK, validate_inventory_section

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "원자재 리포트 텍스트에서 LME Stocks와 COMEX 재고 수치를 추출한다. "
    "지정된 JSON 스키마로만 응답하고 마크다운 코드펜스나 설명은 붙이지 않는다. "
    "텍스트에 없는 값은 절대 추측하지 말고 null로 둔다."
)

SCHEMA_HINT = (
    '{"lme": [{"metal": "Copper", "prev": <number|null>, "current": <number|null>, '
    '"change": <number|null>, "unit": "톤"}], '
    '"comex": [{"metal": "Copper", "prev": <number|null>, "current": <number|null>, '
    '"change": <number|null>, "unit": "숏톤"}]}'
)


def extract_inventory(page_text):
    """Returns {"lme": [...], "comex": [...]}, or None if the AI call or validation failed."""
    user = f"다음 스키마로만 응답하라:\n{SCHEMA_HINT}\n\n---\n{page_text}"
    try:
        result = call_json(SYSTEM_PROMPT, user, AI_MODEL_EXTRACT, max_tokens=1000)
    except Exception as exc:
        logger.error("extract_inventory call failed: %s", exc)
        return None
    if not isinstance(result, dict):
        return None

    errors = validate_inventory_section({"status": STATUS_OK, **result})
    if errors:
        logger.error("extract_inventory produced invalid data: %s", errors)
        return None
    return result
