from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from notifications.domain.errors import InvalidContact


@dataclass(frozen=True, slots=True)
class Contact:
    customer_id: UUID
    name: str
    email: str

    def __post_init__(self) -> None:
        local, _, domain = self.email.partition("@")
        if not local or "." not in domain or any(ch.isspace() for ch in self.email):
            raise InvalidContact("e-mail address is invalid")
        if not self.name.strip():
            raise InvalidContact("name is required")

    @property
    def first_name(self) -> str:
        return self.name.strip().split()[0]
