import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from inventory.application.commit_stock import CommitStock
from inventory.application.common import Delivery, Outcome, ReservationNotFound
from inventory.application.expire_reservations import ExpireReservations
from inventory.application.release_stock import ReleaseStock
from inventory.application.reserve_stock import ReserveStock
from inventory.domain.reservation import ReservationStatus
from inventory.infrastructure.db.models import InboxMessageModel, ReservationModel
from tests.integration.helpers import (
    count,
    items,
    outbox_types,
    reservation_status,
    set_stock,
    stock_levels,
)


@pytest.fixture
def reserve(uow_factory):
    return ReserveStock(uow_factory, timedelta(minutes=35))


async def test_reservation_moves_stock_and_writes_the_outbox_in_one_transaction(
    reserve, session_factory
):
    product, order_id = uuid4(), uuid4()
    await set_stock(session_factory, product, 10)

    outcome = await reserve.execute(order_id, items((product, 4)))

    assert outcome is Outcome.PROCESSED
    assert await stock_levels(session_factory, product) == (6, 4)
    assert await reservation_status(session_factory, order_id) is ReservationStatus.RESERVED
    assert await outbox_types(session_factory) == ["StockReserved"]


async def test_insufficient_stock_rejects_everything_without_touching_stock(
    reserve, session_factory
):
    plenty, scarce, order_id = uuid4(), uuid4(), uuid4()
    await set_stock(session_factory, plenty, 10)
    await set_stock(session_factory, scarce, 1)

    await reserve.execute(order_id, items((plenty, 5), (scarce, 2)))

    assert await stock_levels(session_factory, plenty) == (10, 0)
    assert await stock_levels(session_factory, scarce) == (1, 0)
    assert await reservation_status(session_factory, order_id) is ReservationStatus.REJECTED
    assert await outbox_types(session_factory) == ["StockRejected"]


async def test_reservation_for_the_same_order_is_idempotent(reserve, session_factory):
    product, order_id = uuid4(), uuid4()
    await set_stock(session_factory, product, 10)

    first = await reserve.execute(order_id, items((product, 4)))
    second = await reserve.execute(order_id, items((product, 4)))

    assert (first, second) == (Outcome.PROCESSED, Outcome.DUPLICATE)
    assert await stock_levels(session_factory, product) == (6, 4)
    assert await outbox_types(session_factory) == ["StockReserved"]


async def test_the_same_order_reserved_concurrently_takes_stock_once(reserve, session_factory):
    product, order_id = uuid4(), uuid4()
    await set_stock(session_factory, product, 10)

    outcomes = await asyncio.gather(
        *(reserve.execute(order_id, items((product, 3))) for _ in range(8))
    )

    assert outcomes.count(Outcome.PROCESSED) == 1
    assert outcomes.count(Outcome.DUPLICATE) == 7
    assert await stock_levels(session_factory, product) == (7, 3)
    assert await count(session_factory, ReservationModel) == 1


async def test_one_hundred_concurrent_reservations_for_stock_of_ten_accept_exactly_ten(
    reserve, session_factory
):
    product = uuid4()
    await set_stock(session_factory, product, 10)
    orders = [uuid4() for _ in range(100)]

    await asyncio.gather(*(reserve.execute(o, items((product, 1))) for o in orders))

    assert await stock_levels(session_factory, product) == (0, 10)
    statuses = [await reservation_status(session_factory, o) for o in orders]
    assert statuses.count(ReservationStatus.RESERVED) == 10
    assert statuses.count(ReservationStatus.REJECTED) == 90
    types = await outbox_types(session_factory)
    assert types.count("StockReserved") == 10
    assert types.count("StockRejected") == 90


async def test_orders_with_items_in_opposite_order_do_not_deadlock(reserve, session_factory):
    first, second = uuid4(), uuid4()
    await set_stock(session_factory, first, 100)
    await set_stock(session_factory, second, 100)
    forward = [items((first, 1), (second, 1)) for _ in range(25)]
    backward = [items((second, 1), (first, 1)) for _ in range(25)]

    results = await asyncio.gather(
        *(
            reserve.execute(uuid4(), batch)
            for pair in zip(forward, backward, strict=True)
            for batch in pair
        ),
        return_exceptions=True,
    )

    assert all(result is Outcome.PROCESSED for result in results), results
    assert await stock_levels(session_factory, first) == (50, 50)
    assert await stock_levels(session_factory, second) == (50, 50)


async def test_commit_sells_the_reserved_units(reserve, uow_factory, session_factory):
    product, order_id = uuid4(), uuid4()
    await set_stock(session_factory, product, 10)
    await reserve.execute(order_id, items((product, 4)))

    outcome = await CommitStock(uow_factory).execute(order_id)

    assert outcome is Outcome.PROCESSED
    assert await stock_levels(session_factory, product) == (6, 0)
    assert await reservation_status(session_factory, order_id) is ReservationStatus.COMMITTED
    assert await outbox_types(session_factory) == ["StockReserved", "StockCommitted"]


async def test_commit_without_reservation_fails_and_rolls_back_the_inbox_claim(
    reserve, uow_factory, session_factory
):
    product, order_id = uuid4(), uuid4()
    await set_stock(session_factory, product, 10)
    delivery = Delivery(uuid4(), "inventory-payments")

    with pytest.raises(ReservationNotFound):
        await CommitStock(uow_factory).execute(order_id, delivery)
    assert await count(session_factory, InboxMessageModel) == 0

    await reserve.execute(order_id, items((product, 2)))
    assert await CommitStock(uow_factory).execute(order_id, delivery) is Outcome.PROCESSED
    assert await stock_levels(session_factory, product) == (8, 0)


async def test_releasing_twice_does_not_duplicate_units(reserve, uow_factory, session_factory):
    product, order_id = uuid4(), uuid4()
    await set_stock(session_factory, product, 10)
    await reserve.execute(order_id, items((product, 4)))
    release = ReleaseStock(uow_factory)

    first = await release.execute(order_id, "payment_expired")
    second = await release.execute(order_id, "order_cancelled")

    assert (first, second) == (Outcome.PROCESSED, Outcome.IGNORED)
    assert await stock_levels(session_factory, product) == (10, 0)
    assert (await outbox_types(session_factory)).count("StockReleased") == 1


async def test_concurrent_release_and_commit_of_the_same_order_resolve_to_one_outcome(
    reserve, uow_factory, session_factory
):
    product, order_id = uuid4(), uuid4()
    await set_stock(session_factory, product, 10)
    await reserve.execute(order_id, items((product, 4)))

    results = await asyncio.gather(
        ReleaseStock(uow_factory).execute(order_id, "payment_expired"),
        CommitStock(uow_factory).execute(order_id),
    )

    assert results.count(Outcome.PROCESSED) == 1
    available, reserved = await stock_levels(session_factory, product)
    assert reserved == 0
    assert available in (6, 10)


async def test_expiry_job_releases_overdue_reservations_only(uow_factory, session_factory):
    product, late, fresh = uuid4(), uuid4(), uuid4()
    await set_stock(session_factory, product, 10)
    past = datetime.now(UTC) - timedelta(minutes=40)
    await ReserveStock(uow_factory, timedelta(minutes=35), lambda: past).execute(
        late, items((product, 3))
    )
    await ReserveStock(uow_factory, timedelta(minutes=35)).execute(fresh, items((product, 2)))

    job = ExpireReservations(uow_factory)

    assert await job.run_once() == 1
    assert await job.run_once() == 0
    assert await reservation_status(session_factory, late) is ReservationStatus.RELEASED
    assert await reservation_status(session_factory, fresh) is ReservationStatus.RESERVED
    assert await stock_levels(session_factory, product) == (8, 2)
    assert (await outbox_types(session_factory)).count("StockReleased") == 1


async def test_expiry_job_running_in_parallel_releases_each_reservation_once(
    uow_factory, session_factory
):
    first, second = uuid4(), uuid4()
    await set_stock(session_factory, first, 50)
    await set_stock(session_factory, second, 50)
    past = datetime.now(UTC) - timedelta(minutes=40)
    reserve = ReserveStock(uow_factory, timedelta(minutes=35), lambda: past)
    for index in range(10):
        pair = items((first, 1), (second, 1)) if index % 2 else items((second, 1), (first, 1))
        await reserve.execute(uuid4(), pair)

    counts = await asyncio.gather(
        *(ExpireReservations(uow_factory, batch_size=3).run_once() for _ in range(4))
    )
    await ExpireReservations(uow_factory).run_once()

    assert await stock_levels(session_factory, first) == (50, 0)
    assert await stock_levels(session_factory, second) == (50, 0)
    assert (await outbox_types(session_factory)).count("StockReleased") == 10
    assert sum(counts) <= 10
