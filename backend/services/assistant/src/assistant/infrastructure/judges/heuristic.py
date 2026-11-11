import re
from decimal import Decimal

from assistant.application.judge import JudgeInput, JudgeVerdict, is_refusal
from assistant.domain.numbers import extract_numbers
from assistant.domain.text import content_tokens, normalize, stem
from assistant.domain.understanding import SynonymExpander
from assistant.infrastructure.embedders.hashing import HashingEmbedder

_CLAIMS = re.compile(r"(?<=[.!?])\s+|\n")


class HeuristicJudge:
    """Deterministic stand-in for an LLM judge. Faithfulness is the share of checkable claims
    (sentences with numbers or product names) whose numbers all exist in the evidence.
    Answer relevancy is lexical and semantic overlap with the question, and refusals are
    right only when the question cannot be answered from the catalog."""

    def __init__(self) -> None:
        self._embedder = HashingEmbedder(256)
        self._expander = SynonymExpander()

    async def judge(self, item: JudgeInput) -> JudgeVerdict:
        faithfulness, reasons = self._faithfulness(item)
        return JudgeVerdict(faithfulness, self._relevancy(item), tuple(reasons))

    def _faithfulness(self, item: JudgeInput) -> tuple[float, list[str]]:
        evidence = " ".join((*item.contexts, *item.evidence))
        allowed = (
            set(extract_numbers(evidence))
            | set(extract_numbers(item.question))
            | {Decimal(len(item.contexts))}
        )
        names = [normalize(n) for n in item.product_names]
        checked = supported = 0
        reasons: list[str] = []
        for raw in _CLAIMS.split(item.answer):
            claim = raw.strip(" -")
            if not claim:
                continue
            numbers = extract_numbers(claim)
            named = any(n in normalize(claim) for n in names)
            if not numbers and not named:
                continue
            checked += 1
            missing = [n for n in numbers if n not in allowed]
            if missing:
                reasons.append(f"unsupported number {missing[0]:f} in: {claim[:60]}")
            else:
                supported += 1
        return (supported / checked if checked else 1.0), reasons

    def _relevancy(self, item: JudgeInput) -> float:
        refusal = is_refusal(item.answer)
        if not item.answerable:
            return 1.0 if refusal else 0.0
        if refusal:
            return 0.0
        tokens = content_tokens(item.question)
        if not tokens:
            return 0.0
        answer_stems = {stem(t) for t in content_tokens(item.answer)}
        wanted = {stem(t) for t in tokens}
        related = {stem(t) for t in self._expander.expand(tokens)} - wanted
        weighted = len(wanted & answer_stems) + 0.5 * len(related & answer_stems)
        plain = min(1.0, weighted / len(wanted))
        enriched = " ".join([*tokens, *self._expander.expand(tokens)])
        semantic = _dot(self._embedder.embed_one(enriched), self._embedder.embed_one(item.answer))
        return round(min(1.0, max(plain, semantic * 2)), 4)


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))
