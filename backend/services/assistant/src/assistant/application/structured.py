import json
import logging
from dataclasses import replace

from pydantic import BaseModel, ValidationError

from assistant.application.ports import LlmClient, Prompt
from assistant.domain.errors import AssistantError
from assistant.metrics import GUARDRAIL_EVENTS

logger = logging.getLogger(__name__)


class StructuredOutputError(AssistantError):
    pass


def extract_json(raw: str) -> str:
    """Pulls the first balanced JSON object out of a model reply, tolerating code fences and
    text around it."""
    text = raw.strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object found")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("unterminated JSON object")


def _repair_prompt(prompt: Prompt, schema: dict[str, object], raw: str, error: str) -> Prompt:
    note = (
        "\n\nSua resposta anterior não é válida.\n"
        f"Erro: {error[:400]}\n"
        f"Resposta anterior: {raw[:400]}\n"
        "Responda somente com um objeto JSON válido que siga este esquema, sem texto extra:\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )
    return replace(prompt, text=prompt.text + note)


async def generate_structured[T: BaseModel](
    llm: LlmClient, prompt: Prompt, model: type[T], max_retries: int = 2
) -> T:
    """Asks the model for JSON, validates it against a pydantic model and, when it does not
    validate, sends the error back for a repair attempt, up to `max_retries` times."""
    schema = model.model_json_schema()
    current = prompt
    last_error = ""
    for attempt in range(max_retries + 1):
        raw = await llm.generate(current)
        try:
            return model.model_validate_json(extract_json(raw))
        except (ValueError, ValidationError) as exc:
            last_error = str(exc)
            GUARDRAIL_EVENTS.labels("structured_retry").inc()
            logger.warning(
                "structured output invalid attempt=%d error=%s", attempt + 1, type(exc).__name__
            )
            current = _repair_prompt(prompt, schema, raw, last_error)
    GUARDRAIL_EVENTS.labels("structured_failed").inc()
    raise StructuredOutputError(f"model never produced valid output: {last_error[:200]}")
