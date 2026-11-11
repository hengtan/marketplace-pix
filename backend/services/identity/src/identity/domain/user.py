from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from marketplace_common.security import Role

from identity.domain.errors import InvalidEmail, InvalidRoleAssignment, WeakPassword

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not EMAIL_PATTERN.match(email):
        raise InvalidEmail("email is invalid")
    return email


def validate_password(password: str, email: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(f"password must have at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPassword(f"password must have at most {MAX_PASSWORD_LENGTH} characters")
    if password.lower() == email or password.lower() == email.split("@")[0]:
        raise WeakPassword("password must not match the email")
    if len(set(password)) < 4:
        raise WeakPassword("password is too repetitive")


def validate_roles(roles: frozenset[str], merchant_id: UUID | None) -> None:
    valid = {r.value for r in Role}
    if not roles or not roles <= valid:
        raise InvalidRoleAssignment("roles must be a non-empty subset of customer, merchant, admin")
    if Role.MERCHANT.value in roles and merchant_id is None:
        raise InvalidRoleAssignment("merchant role requires a merchant id")
    if Role.MERCHANT.value not in roles and merchant_id is not None:
        raise InvalidRoleAssignment("merchant id requires the merchant role")


@dataclass(slots=True)
class User:
    id: UUID
    email: str
    name: str
    password_hash: str
    roles: frozenset[str]
    merchant_id: UUID | None = None
    disabled: bool = False
    failed_logins: int = 0
    locked_until: datetime | None = None
    created_at: datetime | None = None

    @classmethod
    def create(
        cls,
        email: str,
        name: str,
        password_hash: str,
        roles: frozenset[str],
        merchant_id: UUID | None = None,
    ) -> User:
        validate_roles(roles, merchant_id)
        return cls(
            id=uuid4(),
            email=email,
            name=name.strip(),
            password_hash=password_hash,
            roles=roles,
            merchant_id=merchant_id,
        )

    def is_locked(self, now: datetime) -> bool:
        return self.locked_until is not None and self.locked_until > now

    def record_failure(self, now: datetime, max_failures: int, lockout: timedelta) -> None:
        self.failed_logins += 1
        if self.failed_logins >= max_failures:
            self.locked_until = now + lockout
            self.failed_logins = 0

    def record_success(self) -> None:
        self.failed_logins = 0
        self.locked_until = None
