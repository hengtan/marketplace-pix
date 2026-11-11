from marketplace_common.events import assert_producer_contract
from marketplace_common.events.contract import (
    SAMPLE_EVENT_ID,
    SAMPLE_OCCURRED_AT,
    SAMPLE_ORDER_ID,
    SAMPLE_TRANSACTION_ID,
)

from ledger.domain.events import LedgerTransactionPosted, LedgerTransactionReversed
from ledger.infrastructure.db.outbox import serialize_event


def test_ledger_transaction_posted_matches_its_golden_file() -> None:
    event = LedgerTransactionPosted(
        order_id=SAMPLE_ORDER_ID,
        transaction_id=SAMPLE_TRANSACTION_ID,
        event_id=SAMPLE_EVENT_ID,
        occurred_at=SAMPLE_OCCURRED_AT,
        total_cents=3980,
        platform_fee_cents=398,
    )
    assert_producer_contract("LedgerTransactionPosted", serialize_event(event))


def test_ledger_transaction_reversed_matches_its_golden_file() -> None:
    event = LedgerTransactionReversed(
        order_id=SAMPLE_ORDER_ID,
        transaction_id=SAMPLE_TRANSACTION_ID,
        event_id=SAMPLE_EVENT_ID,
        occurred_at=SAMPLE_OCCURRED_AT,
        total_cents=3980,
        platform_fee_cents=398,
    )
    assert_producer_contract("LedgerTransactionReversed", serialize_event(event))
