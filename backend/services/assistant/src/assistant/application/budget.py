from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from assistant.domain.cost import CostModel
from assistant.domain.errors import AssistantError
from assistant.metrics import BUDGET_REJECTIONS


class BudgetExceeded(AssistantError):
    def __init__(self, scope: str, limit: str) -> None:
        super().__init__(f"{scope} budget exceeded ({limit})")
        self.scope = scope
        self.limit = limit


@dataclass(frozen=True)
class BudgetConfig:
    enabled: bool = True
    session_tokens: int = 20_000
    session_cost_usd: float = 0.05
    user_daily_tokens: int = 100_000
    user_daily_cost_usd: float = 0.25


@dataclass(frozen=True)
class Usage:
    tokens: int = 0
    cost_micro_usd: int = 0

    @property
    def cost_usd(self) -> float:
        return self.cost_micro_usd / 1_000_000


class UsageStore(Protocol):
    async def get(self, scope: str, key: str, window: str) -> Usage: ...

    async def add(
        self, scope: str, key: str, window: str, tokens: int, cost_micro: int
    ) -> None: ...


class BudgetManager:
    """Caps spending per session and per user per day. `reserve` runs before the model is called
    with the estimated size of the request; `record` books the real usage afterwards."""

    def __init__(
        self,
        store: UsageStore,
        config: BudgetConfig | None = None,
        cost: CostModel | None = None,
    ) -> None:
        self._store = store
        self._config = config or BudgetConfig()
        self._cost = cost or CostModel()

    @staticmethod
    def _day() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    async def reserve(self, session_id: str, user_id: str | None, prompt_tokens: int) -> None:
        cfg = self._config
        if not cfg.enabled:
            return
        estimated_cost = int(self._cost.cost_usd(prompt_tokens, 0) * 1_000_000)
        checks = [("session", session_id, "all", cfg.session_tokens, cfg.session_cost_usd)]
        if user_id:
            checks.append(
                ("user", user_id, self._day(), cfg.user_daily_tokens, cfg.user_daily_cost_usd)
            )
        for scope, key, window, max_tokens, max_cost in checks:
            used = await self._store.get(scope, key, window)
            if used.tokens + prompt_tokens > max_tokens:
                BUDGET_REJECTIONS.labels(scope, "tokens").inc()
                raise BudgetExceeded(scope, "tokens")
            if used.cost_micro_usd + estimated_cost > int(max_cost * 1_000_000):
                BUDGET_REJECTIONS.labels(scope, "cost").inc()
                raise BudgetExceeded(scope, "cost")

    async def record(
        self,
        session_id: str,
        user_id: str | None,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> int:
        tokens = prompt_tokens + completion_tokens
        cost_micro = int(self._cost.cost_usd(prompt_tokens, completion_tokens) * 1_000_000)
        if not self._config.enabled:
            return cost_micro
        await self._store.add("session", session_id, "all", tokens, cost_micro)
        if user_id:
            await self._store.add("user", user_id, self._day(), tokens, cost_micro)
        return cost_micro

    async def remaining(self, session_id: str, user_id: str | None) -> dict[str, int]:
        session = await self._store.get("session", session_id, "all")
        out = {"session_tokens": max(self._config.session_tokens - session.tokens, 0)}
        if user_id:
            user = await self._store.get("user", user_id, self._day())
            out["user_tokens"] = max(self._config.user_daily_tokens - user.tokens, 0)
        return out


class InMemoryUsageStore:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str, str], Usage] = {}

    async def get(self, scope: str, key: str, window: str) -> Usage:
        return self._data.get((scope, key, window), Usage())

    async def add(self, scope: str, key: str, window: str, tokens: int, cost_micro: int) -> None:
        current = self._data.get((scope, key, window), Usage())
        self._data[(scope, key, window)] = Usage(
            current.tokens + tokens, current.cost_micro_usd + cost_micro
        )
