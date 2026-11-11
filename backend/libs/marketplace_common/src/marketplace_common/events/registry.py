from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from marketplace_common.events.models import (
    EventModel,
    LedgerTransactionPostedV1,
    LedgerTransactionReversedV1,
    OrderCancelledV1,
    OrderCreatedV1,
    OrderCreatedV2,
    OrderPaidV1,
    PaymentCancelledV1,
    PaymentConfirmedV1,
    PaymentCreatedV1,
    PaymentExpiredV1,
    PaymentRefundedV1,
    PaymentRefundRequestedV1,
    StockCommittedV1,
    StockRejectedV1,
    StockReleasedV1,
    StockReservedV1,
)

logger = logging.getLogger(__name__)

Payload = dict[str, Any]
Migration = Callable[[Payload], Payload]


class UnknownEvent(Exception):
    pass


class EventRegistry:
    """Modelos versionados por tipo de evento e as migrações entre versões vizinhas."""

    def __init__(self) -> None:
        self._models: dict[str, dict[int, type[EventModel]]] = {}
        self._upcasters: dict[tuple[str, int], Migration] = {}
        self._downcasters: dict[tuple[str, int], Migration] = {}

    def register(self, model: type[EventModel]) -> type[EventModel]:
        versions = self._models.setdefault(model.event_type, {})
        if model.version in versions:
            raise ValueError(f"{model.event_type} v{model.version} already registered")
        versions[model.version] = model
        return model

    def upcaster(self, event_type: str, from_version: int) -> Callable[[Migration], Migration]:
        def decorate(fn: Migration) -> Migration:
            self._upcasters[(event_type, from_version)] = fn
            return fn

        return decorate

    def downcaster(self, event_type: str, from_version: int) -> Callable[[Migration], Migration]:
        def decorate(fn: Migration) -> Migration:
            self._downcasters[(event_type, from_version)] = fn
            return fn

        return decorate

    def types(self) -> list[str]:
        return sorted(self._models)

    def versions(self, event_type: str) -> list[int]:
        try:
            return sorted(self._models[event_type])
        except KeyError:
            raise UnknownEvent(event_type) from None

    def latest(self, event_type: str) -> int:
        return self.versions(event_type)[-1]

    def model(self, event_type: str, version: int) -> type[EventModel]:
        try:
            return self._models[event_type][version]
        except KeyError:
            raise UnknownEvent(f"{event_type} v{version}") from None

    def upcast(self, event_type: str, payload: Payload, version: int | None = None) -> Payload:
        """Leva o payload à versão mais nova conhecida, uma versão por vez."""
        current = version if version is not None else int(payload.get("schema_version", 1))
        latest = self.latest(event_type)
        if current > latest:
            logger.warning(
                "%s v%d is newer than the newest known version v%d, reading it as v%d",
                event_type,
                current,
                latest,
                latest,
            )
            return {**payload, "schema_version": latest}
        result = dict(payload)
        while current < latest:
            migrate = self._upcasters.get((event_type, current))
            if migrate is None:
                raise UnknownEvent(f"no upcaster for {event_type} v{current}")
            result = migrate(result)
            current += 1
            result["schema_version"] = current
        return result

    def downcast(self, event_type: str, payload: Payload, to_version: int) -> Payload:
        current = int(payload.get("schema_version", 1))
        result = dict(payload)
        while current > to_version:
            migrate = self._downcasters.get((event_type, current))
            if migrate is None:
                raise UnknownEvent(f"no downcaster for {event_type} v{current}")
            result = migrate(result)
            current -= 1
            result["schema_version"] = current
        return result

    def parse(self, event_type: str, payload: Payload, version: int | None = None) -> EventModel:
        upcasted = self.upcast(event_type, payload, version)
        return self.model(event_type, int(upcasted["schema_version"])).model_validate(upcasted)

    def parse_as(self, event_type: str, payload: Payload, version: int) -> EventModel:
        """Lê o payload com o modelo de uma versão específica (consumidor antigo, dado novo)."""
        return self.model(event_type, version).model_validate(
            {**payload, "schema_version": version}
        )


def build_default_registry() -> EventRegistry:
    registry = EventRegistry()
    for model in (
        OrderCreatedV1,
        OrderCreatedV2,
        OrderPaidV1,
        OrderCancelledV1,
        PaymentCreatedV1,
        PaymentConfirmedV1,
        PaymentExpiredV1,
        PaymentCancelledV1,
        StockReservedV1,
        StockRejectedV1,
        StockCommittedV1,
        StockReleasedV1,
        LedgerTransactionPostedV1,
        LedgerTransactionReversedV1,
        PaymentRefundRequestedV1,
        PaymentRefundedV1,
    ):
        registry.register(model)

    @registry.upcaster("OrderCreated", 1)
    def order_created_v1_to_v2(payload: Payload) -> Payload:
        return {**payload, "customer_type": None}

    @registry.downcaster("OrderCreated", 2)
    def order_created_v2_to_v1(payload: Payload) -> Payload:
        return {k: v for k, v in payload.items() if k != "customer_type"}

    return registry


REGISTRY = build_default_registry()
