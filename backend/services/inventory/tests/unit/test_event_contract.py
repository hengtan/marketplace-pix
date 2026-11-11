from marketplace_common.events import assert_producer_contract
from marketplace_common.events.contract import (
    SAMPLE_EVENT_ID,
    SAMPLE_OCCURRED_AT,
    SAMPLE_ORDER_ID,
    SAMPLE_PRODUCT_ID,
)

from inventory.domain.events import (
    Shortage,
    StockCommitted,
    StockRejected,
    StockReleased,
    StockReserved,
)
from inventory.infrastructure.db.outbox import serialize_event

COMMON = {
    "order_id": SAMPLE_ORDER_ID,
    "event_id": SAMPLE_EVENT_ID,
    "occurred_at": SAMPLE_OCCURRED_AT,
}


def test_stock_reserved_matches_its_golden_file() -> None:
    assert_producer_contract("StockReserved", serialize_event(StockReserved(**COMMON)))


def test_stock_rejected_matches_its_golden_file() -> None:
    event = StockRejected(
        **COMMON,
        reason="insufficient stock",
        missing=[Shortage(product_id=SAMPLE_PRODUCT_ID, requested=5, available=3)],
    )
    assert_producer_contract("StockRejected", serialize_event(event))


def test_stock_committed_matches_its_golden_file() -> None:
    assert_producer_contract("StockCommitted", serialize_event(StockCommitted(**COMMON)))


def test_stock_released_matches_its_golden_file() -> None:
    event = StockReleased(**COMMON, reason="payment expired")
    assert_producer_contract("StockReleased", serialize_event(event))
