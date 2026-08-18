"""Shared OpenAI client + strict-JSON response parsing (SPEC.md §5, adapted for OpenAI).

Every caller in ai/ treats a None return as "AI layer unavailable" and
degrades the corresponding report section instead of raising — the pipeline
must keep going even if every AI call fails (SPEC.md §8 rule 1).

OpenAI's `response_format={"type": "json_object"}` guarantees valid JSON
syntax natively, so unlike a code-fence-stripping approach there's no
markdown to strip — the only thing that can still go wrong is the JSON not
matching the shape callers expect, which they validate themselves.
"""
import json
import logging

from openai import OpenAI, OpenAIError

logger = logging.getLogger(__name__)
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def call_json(system, user, model, max_tokens=2000):
    """One call, one retry with a stricter system reminder if parsing fails.
    Returns the parsed JSON object, or None if both attempts fail."""
    client = _get_client()
    strict_system = system
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": strict_system},
                    {"role": "user", "content": user},
                ],
            )
            return json.loads(response.choices[0].message.content)
        except (json.JSONDecodeError, OpenAIError) as exc:
            logger.warning("AI call attempt %d/2 failed: %s", attempt + 1, exc)
            strict_system = system + "\n\n반드시 순수 JSON 객체만 응답하라. 설명이나 마크다운을 절대 포함하지 마라."
    return None
