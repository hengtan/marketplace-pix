from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RefreshTokenRecord:
    id: UUID
    family_id: UUID
    user_id: UUID
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    family_expires_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    access_jti: str | None = None

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at <= now or self.family_expires_at <= now
