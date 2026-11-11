from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]

monotonic: Clock = time.monotonic
sleep: Sleeper = asyncio.sleep
