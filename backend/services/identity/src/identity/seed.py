from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from identity.application.auth import AuthService
from identity.application.errors import EmailAlreadyRegistered
from identity.config import load_settings
from identity.infrastructure.db.session import build_engine, build_session_factory
from identity.infrastructure.db.uow import SqlAlchemyUnitOfWork
from identity.infrastructure.security.jwt_issuer import JwtAccessTokenIssuer
from identity.infrastructure.security.keys import load_signing_keys
from identity.infrastructure.security.password import Argon2idHasher
from identity.interface.api import merchant_id_for_slug

logger = logging.getLogger(__name__)

SEED_DOMAIN = "marketplace-pix.local"
MERCHANTS = {
    "aurora-tech": "Aurora Tech",
    "casa-lume": "Casa Lume",
    "trilha-sports": "Trilha Sports",
}


async def seed(auth: AuthService, password: str) -> int:
    created = 0
    accounts: list[tuple[str, str, frozenset[str], UUID | None]] = [
        (f"admin@{SEED_DOMAIN}", "Administrador", frozenset({"admin"}), None)
    ]
    for slug, name in MERCHANTS.items():
        accounts.append(
            (f"{slug}@{SEED_DOMAIN}", name, frozenset({"merchant"}), merchant_id_for_slug(slug))
        )
    for email, name, roles, merchant_id in accounts:
        try:
            await auth.create_user(email, name, password, roles, merchant_id)
            created += 1
        except EmailAlreadyRegistered:
            continue
    return created


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    if not settings.identity_seed_password:
        logger.info("IDENTITY_SEED_PASSWORD not set, skipping seed")
        return
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    keys = load_signing_keys("", [], allow_ephemeral=True)
    auth = AuthService(
        lambda: SqlAlchemyUnitOfWork(factory),
        Argon2idHasher(
            settings.argon2_time_cost, settings.argon2_memory_kib, settings.argon2_parallelism
        ),
        JwtAccessTokenIssuer(keys, settings.issuer, settings.audience),
    )
    created = await seed(auth, settings.identity_seed_password)
    logger.info("seed finished: %d accounts created", created)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
