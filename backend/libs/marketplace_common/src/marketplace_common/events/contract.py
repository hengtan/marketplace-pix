from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import resources
from typing import Any
from uuid import UUID

from marketplace_common.events.registry import REGISTRY, EventRegistry

SAMPLE_EVENT_ID = UUID("00000000-0000-4000-8000-0000000000e1")
SAMPLE_ORDER_ID = UUID("11111111-1111-4111-8111-111111111111")
SAMPLE_PAYMENT_ID = UUID("22222222-2222-4222-8222-222222222222")
SAMPLE_TRANSACTION_ID = UUID("33333333-3333-4333-8333-333333333333")
SAMPLE_CUSTOMER_ID = UUID("44444444-4444-4444-8444-444444444444")
SAMPLE_PRODUCT_ID = UUID("55555555-5555-4555-8555-555555555555")
SAMPLE_MERCHANT_ID = UUID("66666666-6666-4666-8666-666666666666")
SAMPLE_OCCURRED_AT = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
SAMPLE_EXPIRES_AT = datetime(2026, 1, 15, 12, 30, tzinfo=UTC)


def golden_payload(event_type: str, version: int) -> dict[str, Any]:
    path = resources.files("marketplace_common.events").joinpath(
        "golden", f"{event_type}.v{version}.json"
    )
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def assert_producer_contract(
    event_type: str,
    produced: dict[str, Any],
    registry: EventRegistry = REGISTRY,
) -> None:
    """Falha se o payload produzido diverge do arquivo golden da sua versão ou do modelo.

    Qualquer campo novo, removido, renomeado ou de outro tipo quebra o teste. Mudar o contrato é uma
    decisão: nova versão do modelo, upcaster e novo arquivo golden, nunca um ajuste silencioso.
    """
    version = int(produced["schema_version"])
    model = registry.model(event_type, version)
    expected = golden_payload(event_type, version)
    assert produced == expected, (
        f"{event_type} v{version} diverges from its golden file: "
        f"missing={sorted(set(expected) - set(produced))} "
        f"extra={sorted(set(produced) - set(expected))} "
        f"changed={sorted(k for k in set(expected) & set(produced) if expected[k] != produced[k])}"
    )
    undeclared = set(produced) - set(model.model_fields)
    assert not undeclared, f"{event_type} v{version} emits undeclared fields: {sorted(undeclared)}"
    model.model_validate(produced)
