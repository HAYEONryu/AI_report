"""Shared Anthropic client + strict-JSON response parsing (SPEC.md §5).

Every caller in ai/ treats a None return as "AI layer unavailable" and
degrades the corresponding report section instead of raising — the pipeline
must keep going even if every AI call fails (SPEC.md §8 rule 1).
"""
import json
import logging
import re

import anthropic

logger = logging.getLogger(__name__)
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _strip_code_fence(text):
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return match.group(1) if match else text


def call_json(system, user, model, max_tokens=2000):
    """One call, one retry with a stricter system reminder if parsing fails.
    Returns the parsed JSON object, or None if both attempts fail."""
    client = _get_client()
    strict_system = system
    for attempt in range(2):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=strict_system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(block.text for block in response.content if block.type == "text")
            return json.loads(_strip_code_fence(text))
        except (json.JSONDecodeError, anthropic.AnthropicError) as exc:
            logger.warning("AI call attempt %d/2 failed: %s", attempt + 1, exc)
            strict_system = system + "\n\n반드시 순수 JSON만 응답하라. 코드펜스, 설명, 마크다운을 절대 포함하지 마라."
    return None
