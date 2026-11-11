from __future__ import annotations

import asyncio

from argon2 import PasswordHasher as Argon2
from argon2 import Type
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2idHasher:
    def __init__(self, time_cost: int = 3, memory_kib: int = 65536, parallelism: int = 4) -> None:
        self._hasher = Argon2(
            time_cost=time_cost,
            memory_cost=memory_kib,
            parallelism=parallelism,
            type=Type.ID,
        )

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._hasher.hash, password)

    async def verify(self, password_hash: str, password: str) -> bool:
        def check() -> bool:
            try:
                return self._hasher.verify(password_hash, password)
            except (VerificationError, InvalidHashError):
                return False

        return await asyncio.to_thread(check)

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)
