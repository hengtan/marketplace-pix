import random

import pytest
from prometheus_client import REGISTRY

from marketplace_common.resilience import (
    BulkheadFullError,
    CircuitOpenError,
    Deadline,
    DeadlineExceeded,
    RetryBudget,
    RetryPolicy,
    deadline_scope,
    is_idempotent_method,
    retry_async,
)
from marketplace_common.resilience.retry import full_jitter
from tests.unit.fakes import FakeClock, FakeSleeper


def event(name: str, kind: str) -> float:
    return (
        REGISTRY.get_sample_value("resilience_retry_events_total", {"name": name, "event": kind})
        or 0.0
    )


class Flaky:
    def __init__(self, failures: int, error: Exception | None = None) -> None:
        self.failures = failures
        self.calls = 0
        self.error = error or ConnectionError("down")

    async def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return "ok"


async def test_succeeds_after_transient_failures_with_backoff() -> None:
    flaky, sleeper = Flaky(2), FakeSleeper()
    result = await retry_async(
        flaky,
        name="r-ok",
        idempotent=True,
        policy=RetryPolicy(max_attempts=4, base_delay=0.1, max_delay=1.0),
        rng=random.Random(7),
        sleeper=sleeper,
    )
    assert result == "ok" and flaky.calls == 3
    assert len(sleeper.delays) == 2
    assert 0 <= sleeper.delays[0] <= 0.1 and 0 <= sleeper.delays[1] <= 0.2
    assert event("r-ok", "retried") == 2


async def test_gives_up_after_max_attempts_and_raises_the_last_error() -> None:
    flaky, sleeper = Flaky(99), FakeSleeper()
    with pytest.raises(ConnectionError):
        await retry_async(
            flaky,
            name="r-exhaust",
            idempotent=True,
            policy=RetryPolicy(max_attempts=3),
            sleeper=sleeper,
        )
    assert flaky.calls == 3 and len(sleeper.delays) == 2
    assert event("r-exhaust", "exhausted") == 1


async def test_non_idempotent_operations_run_exactly_once() -> None:
    flaky, sleeper = Flaky(99), FakeSleeper()
    with pytest.raises(ConnectionError):
        await retry_async(flaky, name="r-post", idempotent=False, sleeper=sleeper)
    assert flaky.calls == 1 and sleeper.delays == []


async def test_non_transient_errors_are_not_retried() -> None:
    flaky = Flaky(99, error=ValueError("bad input"))
    with pytest.raises(ValueError):
        await retry_async(flaky, name="r-value", idempotent=True, sleeper=FakeSleeper())
    assert flaky.calls == 1
    assert event("r-value", "not_retryable") == 1


@pytest.mark.parametrize(
    "error",
    [CircuitOpenError("x", 1.0), BulkheadFullError("x", "full"), DeadlineExceeded()],
)
async def test_resilience_errors_are_never_retried(error: Exception) -> None:
    flaky = Flaky(99, error=error)
    with pytest.raises(type(error)):
        await retry_async(
            flaky, name="r-never", idempotent=True, retry_on=lambda _: True, sleeper=FakeSleeper()
        )
    assert flaky.calls == 1


async def test_retries_on_bad_results_and_returns_the_last_one_when_exhausted() -> None:
    codes = iter([503, 503, 200])

    async def call() -> int:
        return next(codes)

    result = await retry_async(
        call,
        name="r-result",
        idempotent=True,
        retry_on_result=lambda c: c >= 500,
        sleeper=FakeSleeper(),
    )
    assert result == 200

    async def always_503() -> int:
        return 503

    last = await retry_async(
        always_503,
        name="r-result2",
        idempotent=True,
        policy=RetryPolicy(max_attempts=2),
        retry_on_result=lambda c: c >= 500,
        sleeper=FakeSleeper(),
    )
    assert last == 503


async def test_custom_retry_predicate() -> None:
    flaky = Flaky(1, error=KeyError("transient here"))
    assert (
        await retry_async(
            flaky,
            name="r-custom",
            idempotent=True,
            retry_on=lambda e: isinstance(e, KeyError),
            sleeper=FakeSleeper(),
        )
        == "ok"
    )


def test_full_jitter_stays_within_the_exponential_ceiling() -> None:
    policy = RetryPolicy(max_attempts=10, base_delay=0.1, max_delay=1.0, multiplier=2.0)
    rng = random.Random(1)
    assert [policy.ceiling(n) for n in range(1, 6)] == [0.1, 0.2, 0.4, 0.8, 1.0]
    samples = [full_jitter(policy, 4, rng) for _ in range(500)]
    assert min(samples) >= 0 and max(samples) <= 0.8
    assert max(samples) - min(samples) > 0.4


async def test_retry_budget_blocks_retry_storms() -> None:
    clock = FakeClock()
    budget = RetryBudget(ratio=0.1, min_retries=1, window_seconds=10.0, clock=clock)
    outcomes: list[bool] = []
    for _ in range(20):
        flaky = Flaky(1)
        try:
            await retry_async(
                flaky,
                name="r-budget",
                idempotent=True,
                policy=RetryPolicy(max_attempts=2),
                budget=budget,
                sleeper=FakeSleeper(),
            )
            outcomes.append(True)
        except ConnectionError:
            outcomes.append(False)
    assert outcomes.count(True) == 3
    assert event("r-budget", "budget_denied") == 17


def test_retry_budget_window_slides() -> None:
    clock = FakeClock()
    budget = RetryBudget(ratio=0.0, min_retries=2, window_seconds=10.0, clock=clock)
    assert budget.try_acquire() and budget.try_acquire()
    assert not budget.try_acquire()
    clock.advance(10.1)
    assert budget.try_acquire()
    assert budget.retries_in_window == 1


def test_retry_budget_scales_with_traffic() -> None:
    budget = RetryBudget(ratio=0.5, min_retries=0, window_seconds=10.0, clock=FakeClock())
    assert not budget.try_acquire()
    for _ in range(4):
        budget.record_request()
    assert budget.try_acquire() and budget.try_acquire() and not budget.try_acquire()


async def test_does_not_retry_when_the_deadline_cannot_fit_the_backoff() -> None:
    clock = FakeClock()
    flaky, sleeper = Flaky(99), FakeSleeper()
    with deadline_scope(Deadline.after(0.0001, clock)), pytest.raises(ConnectionError):
        await retry_async(
            flaky,
            name="r-deadline",
            idempotent=True,
            policy=RetryPolicy(max_attempts=5, base_delay=5.0, max_delay=5.0),
            rng=random.Random(3),
            sleeper=sleeper,
        )
    assert flaky.calls == 1 and sleeper.delays == []
    assert event("r-deadline", "deadline") == 1


def test_idempotent_method_rules() -> None:
    assert is_idempotent_method("get") and is_idempotent_method("HEAD")
    assert not is_idempotent_method("POST") and not is_idempotent_method("PUT")
    assert is_idempotent_method("PUT", strict=False) and not is_idempotent_method(
        "POST", strict=False
    )


@pytest.mark.parametrize(
    "bad", [{"max_attempts": 0}, {"base_delay": -1}, {"base_delay": 2, "max_delay": 1}]
)
def test_invalid_policy(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        RetryPolicy(**bad)  # type: ignore[arg-type]
