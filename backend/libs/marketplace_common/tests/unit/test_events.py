from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from marketplace_common.events import (
    REGISTRY,
    EventRegistry,
    UnknownEvent,
    assert_producer_contract,
    golden_payload,
    serialize_event,
)
from marketplace_common.events.contract import SAMPLE_EVENT_ID, SAMPLE_OCCURRED_AT, SAMPLE_ORDER_ID
from marketplace_common.events.models import EventModel, OrderCreatedV1, OrderCreatedV2
from marketplace_common.messaging import to_incoming_event


def all_models() -> list[tuple[str, int]]:
    return [(t, v) for t in REGISTRY.types() for v in REGISTRY.versions(t)]


@pytest.mark.parametrize(("event_type", "version"), all_models())
def test_every_registered_version_has_a_golden_file_that_validates(
    event_type: str, version: int
) -> None:
    payload = golden_payload(event_type, version)
    model = REGISTRY.model(event_type, version)
    assert payload["schema_version"] == version
    assert model.model_validate(payload).schema_version == version
    assert set(payload) == set(model.model_fields), "golden must carry exactly the declared fields"


def test_order_created_v1_is_upcast_to_v2() -> None:
    v1 = golden_payload("OrderCreated", 1)
    upcast = REGISTRY.upcast("OrderCreated", v1)
    assert upcast["schema_version"] == 2
    assert upcast["customer_type"] is None
    parsed = REGISTRY.parse("OrderCreated", v1)
    assert isinstance(parsed, OrderCreatedV2)
    assert parsed.customer_type is None
    assert parsed.items[0].quantity == 2


def test_new_reader_accepts_old_data_and_old_reader_accepts_new_data() -> None:
    v1, v2 = golden_payload("OrderCreated", 1), golden_payload("OrderCreated", 2)
    assert isinstance(REGISTRY.parse("OrderCreated", v1), OrderCreatedV2)
    old_reading_new = REGISTRY.parse_as("OrderCreated", v2, 1)
    assert isinstance(old_reading_new, OrderCreatedV1)
    assert old_reading_new.total_cents == v2["total_cents"]
    assert not hasattr(old_reading_new, "customer_type")


def test_downcast_v2_to_v1_matches_the_v1_golden_shape() -> None:
    downcast = REGISTRY.downcast("OrderCreated", golden_payload("OrderCreated", 2), 1)
    assert downcast == golden_payload("OrderCreated", 1)


def test_upcast_then_downcast_round_trips() -> None:
    v1 = golden_payload("OrderCreated", 1)
    again = REGISTRY.downcast("OrderCreated", REGISTRY.upcast("OrderCreated", v1), 1)
    assert again == v1


def test_a_payload_newer_than_known_is_read_as_the_latest_known(
    caplog: pytest.LogCaptureFixture,
) -> None:
    future = {**golden_payload("OrderCreated", 2), "schema_version": 9, "shipping": {"zip": "1"}}
    with caplog.at_level(logging.WARNING):
        parsed = REGISTRY.parse("OrderCreated", future)
    assert isinstance(parsed, OrderCreatedV2)
    assert "newer than the newest known" in caplog.text


def test_missing_schema_version_means_v1() -> None:
    legacy = {k: v for k, v in golden_payload("OrderCreated", 1).items() if k != "schema_version"}
    assert isinstance(REGISTRY.parse("OrderCreated", legacy), OrderCreatedV2)


def test_unknown_types_and_versions_raise() -> None:
    with pytest.raises(UnknownEvent):
        REGISTRY.latest("Nope")
    with pytest.raises(UnknownEvent):
        REGISTRY.model("OrderCreated", 7)


def test_invalid_payload_is_rejected_by_the_model() -> None:
    broken = {**golden_payload("OrderCreated", 2), "customer_type": "alien"}
    with pytest.raises(ValidationError):
        REGISTRY.parse("OrderCreated", broken)
    missing = {k: v for k, v in golden_payload("OrderPaid", 1).items() if k != "order_id"}
    with pytest.raises(ValidationError):
        REGISTRY.parse("OrderPaid", missing)


class ThingV1(EventModel):
    event_type = "Thing"
    version = 1
    name: str


class ThingV2(EventModel):
    event_type = "Thing"
    version = 2
    full_name: str


class ThingV3(EventModel):
    event_type = "Thing"
    version = 3
    full_name: str
    tags: tuple[str, ...] = ()


def chain_registry(with_second_step: bool = True) -> EventRegistry:
    registry = EventRegistry()
    for model in (ThingV1, ThingV2, ThingV3):
        registry.register(model)

    @registry.upcaster("Thing", 1)
    def rename(payload: dict[str, Any]) -> dict[str, Any]:
        migrated = {k: v for k, v in payload.items() if k != "name"}
        return {**migrated, "full_name": payload["name"]}

    if with_second_step:

        @registry.upcaster("Thing", 2)
        def add_tags(payload: dict[str, Any]) -> dict[str, Any]:
            return {**payload, "tags": []}

    return registry


def thing_v1() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event_id": str(SAMPLE_EVENT_ID),
        "occurred_at": SAMPLE_OCCURRED_AT.isoformat(),
        "order_id": str(SAMPLE_ORDER_ID),
        "name": "x",
    }


def test_upcasters_chain_across_several_versions_including_a_rename() -> None:
    parsed = chain_registry().parse("Thing", thing_v1())
    assert isinstance(parsed, ThingV3)
    assert parsed.full_name == "x" and parsed.tags == ()


def test_a_gap_in_the_upcaster_chain_is_an_error() -> None:
    with pytest.raises(UnknownEvent):
        chain_registry(with_second_step=False).parse("Thing", thing_v1())


def test_registering_the_same_version_twice_is_rejected() -> None:
    registry = EventRegistry()
    registry.register(ThingV1)
    with pytest.raises(ValueError):
        registry.register(ThingV1)


@dataclass(frozen=True, slots=True, kw_only=True)
class FakeEvent:
    schema_version = 2
    order_id: Any
    event_id: Any = SAMPLE_EVENT_ID
    occurred_at: Any = SAMPLE_OCCURRED_AT
    tags: tuple[str, ...] = field(default=("a",))


@dataclass(frozen=True, slots=True, kw_only=True)
class Unversioned:
    order_id: Any


def test_serialize_event_stamps_the_class_version_and_defaults_to_one() -> None:
    payload = serialize_event(FakeEvent(order_id=SAMPLE_ORDER_ID))
    assert payload["schema_version"] == 2
    assert payload["occurred_at"] == "2026-01-15T12:00:00+00:00"
    assert payload["tags"] == ["a"]
    assert serialize_event(Unversioned(order_id=SAMPLE_ORDER_ID))["schema_version"] == 1
    with pytest.raises(TypeError):
        serialize_event({"a": 1})


def test_contract_check_passes_for_the_golden_and_names_every_kind_of_drift() -> None:
    golden = golden_payload("OrderPaid", 1)
    assert_producer_contract("OrderPaid", dict(golden))

    renamed = {("order" if k == "order_id" else k): v for k, v in golden.items()}
    with pytest.raises(AssertionError, match="missing=\\['order_id'\\]"):
        assert_producer_contract("OrderPaid", renamed)

    with pytest.raises(AssertionError, match="extra=\\['coupon'\\]"):
        assert_producer_contract("OrderPaid", {**golden, "coupon": "X"})

    with pytest.raises(AssertionError, match="changed=\\['occurred_at'\\]"):
        assert_producer_contract("OrderPaid", {**golden, "occurred_at": 1768478400})

    with pytest.raises(AssertionError):
        assert_producer_contract("OrderPaid", {k: v for k, v in golden.items() if k != "event_id"})


def record(headers: dict[str, str], payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        headers=[(k, v.encode()) for k, v in headers.items()],
        key=b"k",
        value=json.dumps(payload).encode(),
        offset=1,
    )


def test_incoming_event_reads_the_version_from_header_then_payload_then_defaults() -> None:
    base = {"event_id": str(SAMPLE_EVENT_ID), "event_type": "OrderPaid"}
    golden = golden_payload("OrderPaid", 1)
    from_header = to_incoming_event(record({**base, "schema_version": "3"}, golden))
    from_payload = to_incoming_event(record(base, {**golden, "schema_version": 2}))
    legacy = to_incoming_event(
        record(base, {k: v for k, v in golden.items() if k != "schema_version"})
    )
    assert from_header is not None and from_header.schema_version == 3
    assert from_payload is not None and from_payload.schema_version == 2
    assert legacy is not None and legacy.schema_version == 1


def test_incoming_event_parse_uses_the_registry() -> None:
    event = to_incoming_event(
        record(
            {"event_id": str(SAMPLE_EVENT_ID), "event_type": "OrderCreated", "schema_version": "1"},
            golden_payload("OrderCreated", 1),
        )
    )
    assert event is not None
    assert isinstance(event.parse(), OrderCreatedV2)


def test_garbage_version_header_is_treated_as_a_malformed_message() -> None:
    bad = to_incoming_event(
        record(
            {"event_id": str(SAMPLE_EVENT_ID), "event_type": "OrderPaid", "schema_version": "x"},
            golden_payload("OrderPaid", 1),
        )
    )
    assert bad is None
