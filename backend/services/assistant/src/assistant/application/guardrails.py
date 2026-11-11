import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from assistant.application.prompt import SYSTEM_PROMPT
from assistant.domain.injection import InjectionDetector, canonical
from assistant.domain.models import Citation, Passage
from assistant.domain.numbers import extract_money, extract_numbers
from assistant.domain.pii import redact
from assistant.domain.text import normalize

logger = logging.getLogger(__name__)

_MARKER = re.compile(r"\s?\[(\d+)\]")
_MARKER_NUMBER = re.compile(r"\[(\d+)\]")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n")
_URL = re.compile(r"(?:https?://|www\.)[^\s)>\]]+", re.IGNORECASE)
_MARKUP = re.compile(r"!\[[^\]]*\]\([^)]*\)|<\s*(?:img|script|iframe|a)\b", re.IGNORECASE)
UNSAFE_FALLBACK = (
    "Não consegui montar uma resposta confiável com as informações que recuperei. "
    "Pode reformular a pergunta?"
)
INJECTION_REFUSAL = (
    "Não posso seguir esse tipo de instrução. Posso ajudar com produtos do catálogo, estoque, "
    "pedidos e políticas da loja."
)
LEAK_WINDOW = 6
BLOCK_THRESHOLD = 0.7


@dataclass(frozen=True)
class GuardResult:
    answer: str
    citations: list[Citation]
    grounded: bool
    issues: list[str]


def screen_user_message(message: str, detector: InjectionDetector | None = None) -> bool:
    """True when the message is a clear prompt injection attempt and must not reach the agent."""
    detection = (detector or InjectionDetector()).scan(message)
    if detection.score >= BLOCK_THRESHOLD:
        logger.warning(
            "prompt injection blocked score=%.2f categories=%s",
            detection.score,
            ",".join(detection.categories),
        )
        return True
    return False


def _passage_numbers(passage: Passage) -> set[Decimal]:
    numbers = set(extract_numbers(passage.content))
    numbers.add(Decimal(passage.price_cents) / 100)
    numbers.add(Decimal(str(passage.rating)))
    return {n.normalize() for n in numbers}


def _leaks_system_prompt(answer: str) -> bool:
    prompt_words = canonical(SYSTEM_PROMPT).split()
    windows = {
        " ".join(prompt_words[i : i + LEAK_WINDOW])
        for i in range(len(prompt_words) - LEAK_WINDOW + 1)
    }
    answer_words = canonical(answer).split()
    return any(
        " ".join(answer_words[i : i + LEAK_WINDOW]) in windows
        for i in range(len(answer_words) - LEAK_WINDOW + 1)
    )


class GroundingGuard:
    """Checks the model output against what was actually retrieved. Citation markers must point
    to a real passage, products of the catalog that were not retrieved cannot be mentioned, every
    number in a sentence has to exist in the passage it cites (or in the tool observations when
    it cites nothing), and the answer may not leak the system prompt, carry links that were not in
    the context or expose personal data."""

    def __init__(self, detector: InjectionDetector | None = None) -> None:
        self._detector = detector or InjectionDetector()

    def verify(
        self,
        answer: str,
        passages: Sequence[Passage],
        allowed_names: Iterable[str] = (),
        known_names: Iterable[str] = (),
        evidence: Sequence[str] = (),
        question: str = "",
    ) -> GuardResult:
        issues: list[str] = []
        output_issues = self._output_issues(answer, passages, evidence, question)
        if output_issues:
            logger.warning("output guard blocked answer issues=%s", ",".join(output_issues))
            return GuardResult(UNSAFE_FALLBACK, [], False, output_issues)

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

        cleaned, number_issues = self._verify_numbers(cleaned, passages, evidence, question)
        issues.extend(number_issues)
        if number_issues:
            logger.warning("numeric claims removed count=%d", len(number_issues))
            if not cleaned.strip():
                return GuardResult(UNSAFE_FALLBACK, [], False, issues)
            kept = {int(n) for n in _MARKER_NUMBER.findall(cleaned)}
            cited = [c for i, c in enumerate(cited, start=1) if i in kept or not kept]
        return GuardResult(cleaned, cited, not issues, issues)

    def _output_issues(
        self,
        answer: str,
        passages: Sequence[Passage],
        evidence: Sequence[str],
        question: str,
    ) -> list[str]:
        context = " ".join([*(p.content for p in passages), *evidence, question])
        issues: list[str] = []
        if _leaks_system_prompt(answer):
            issues.append("system prompt leak")
        known_urls = set(_URL.findall(context))
        if any(url not in known_urls for url in _URL.findall(answer)) or _MARKUP.search(answer):
            issues.append("link or markup not present in the context")
        if redact(answer) != answer and redact(context) == context:
            issues.append("personal data not present in the context")
        detection = self._detector.scan(answer)
        hijack = {"delimiter_spoof", "exfil_channel", "override_instructions"}
        if hijack & set(detection.categories) and not self._detector.scan(context).flagged:
            issues.append("answer carries injected instructions")
        return issues

    def _verify_numbers(
        self,
        answer: str,
        passages: Sequence[Passage],
        evidence: Sequence[str],
        question: str,
    ) -> tuple[str, list[str]]:
        always = {n.normalize() for n in extract_numbers(" ".join([*evidence, question]))}
        counts = {Decimal(len(passages)).normalize(), Decimal(len(passages) + 1).normalize()}
        everywhere = {n for p in passages for n in _passage_numbers(p)} | always
        kept: list[str] = []
        issues: list[str] = []
        for sentence in _SENTENCE_BREAK.split(answer):
            if not sentence.strip():
                continue
            markers = [int(m) for m in _MARKER_NUMBER.findall(sentence)]
            valid = [m for m in markers if 1 <= m <= len(passages)]
            supported = (
                {n for m in valid for n in _passage_numbers(passages[m - 1])} | always
                if valid
                else everywhere
            )
            money = {n.normalize() for n in extract_money(sentence)}
            wrong = [
                n
                for n in extract_numbers(sentence)
                if n.normalize() not in supported
                and (n.normalize() in money or n.normalize() not in counts)
            ]
            if wrong:
                issues.append(f"unsupported number {wrong[0]:f}")
                continue
            kept.append(sentence)
        return "\n".join(kept) if issues else answer, issues
