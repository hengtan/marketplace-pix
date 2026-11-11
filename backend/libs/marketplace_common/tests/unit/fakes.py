from __future__ import annotations


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSleeper:
    def __init__(self, clock: FakeClock | None = None) -> None:
        self.delays: list[float] = []
        self._clock = clock

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        if self._clock is not None:
            self._clock.advance(seconds)
