import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from assistant.domain.models import Citation, Passage
from assistant.domain.text import normalize

logger = logging.getLogger(__name__)

_MARKER = re.compile(r"\s?\[(\d+)\]")
UNSAFE_FALLBACK = (
    "Não consegui montar uma resposta confiável com as informações que recuperei. "
    "Pode reformular a pergunta?"
)


@dataclass(frozen=True)
class GuardResult:
    answer: str
    citations: list[Citation]
    grounded: bool
    issues: list[str]


class GroundingGuard:
    """Checks the model output against what was actually retrieved: citation markers must point
    to a real passage and known catalog products that were not retrieved cannot be mentioned."""

    def verify(
        self,
        answer: str,
        passages: Sequence[Passage],
        allowed_names: Iterable[str] = (),
        known_names: Iterable[str] = (),
    ) -> GuardResult:
        issues: list[str] = []
        cited: list[Citation] = []
        seen: set[int] = set()

        def replace(match: re.Match[str]) -> str:
            number = int(match.group(1))
            if not 1 <= number <= len(passages):
                issues.append(f"invalid citation [{number}]")
                return ""
            if number not in seen:
                seen.add(number)
                p = passages[number - 1]
                cited.append(Citation(p.product_id, p.slug, p.name, p.score))
            return match.group(0)

        cleaned = _MARKER.sub(replace, answer)

        allowed = {normalize(p.name) for p in passages} | {normalize(n) for n in allowed_names}
        normalized_answer = normalize(cleaned)
        for original in known_names:
            norm_name = normalize(original)
            if not norm_name:
                continue
            if norm_name in normalized_answer and norm_name not in allowed:
                issues.append(f"mentions product that was not retrieved: {original}")

        mentions = [i for i in issues if i.startswith("mentions")]
        if mentions:
            logger.warning("grounding violation issues=%d", len(issues))
            return GuardResult(UNSAFE_FALLBACK, [], False, issues)
        return GuardResult(cleaned, cited, not issues, issues)
