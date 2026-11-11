from dataclasses import dataclass
from typing import Protocol

from assistant.domain.text import normalize

_REFUSALS = ("nao encontrei", "so consigo ajudar", "nao consegui", "me envie o codigo")


@dataclass(frozen=True)
class JudgeInput:
    question: str
    answer: str
    contexts: tuple[str, ...]
    evidence: tuple[str, ...]
    answerable: bool
    product_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class JudgeVerdict:
    faithfulness: float
    relevancy: float
    reasons: tuple[str, ...] = ()


class JudgeLlm(Protocol):
    async def judge(self, item: JudgeInput) -> JudgeVerdict: ...


def is_refusal(answer: str) -> bool:
    text = normalize(answer)
    return any(marker in text for marker in _REFUSALS)
