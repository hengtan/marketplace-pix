import math
from dataclasses import dataclass


def estimate_tokens(text: str) -> int:
    """Rough token count (about four characters per token), good enough for budgets and
    dashboards when the provider does not report usage."""
    return max(1, math.ceil(len(text) / 4)) if text else 0


@dataclass(frozen=True)
class CostModel:
    prompt_per_1k_usd: float = 0.0005
    completion_per_1k_usd: float = 0.0015

    def cost_usd(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.prompt_per_1k_usd + completion_tokens * self.completion_per_1k_usd
        ) / 1000
