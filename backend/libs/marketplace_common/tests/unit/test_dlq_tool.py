from datetime import UTC, datetime

from marketplace_common.dlq.tool import (
    DlqEntry,
    replay_headers,
    select_for_replay,
    summarize,
)


def entry(
    offset: int,
    event_type: str = "OrderCreated",
    reason: str = "RuntimeError('boom')",
    source: str | None = "orders.events/0/7",
    group: str = "payments",
    event_id: str | None = None,
    extra: list[tuple[str, bytes]] | None = None,
) -> DlqEntry:
    headers = [
        ("event_id", (event_id or f"id-{offset}").encode()),
        ("event_type", event_type.encode()),
        ("dlq_reason", reason.encode()),
        ("dlq_group", group.encode()),
    ]
    if source:
        headers.append(("dlq_source", source.encode()))
    headers.extend(extra or [])
    return DlqEntry("orders.events.dlq", 0, offset, 1000 + offset, b"order-1", b'{"a": 1}', headers)


def marker(event_id: str, offset: int = 99) -> DlqEntry:
    return DlqEntry(
        "orders.events.dlq",
        0,
        offset,
        5000,
        b"order-1",
        b"",
        [("dlq_marker", b"replayed"), ("event_id", event_id.encode())],
    )


def test_source_topic_is_parsed_from_the_dlq_source_header():
    assert entry(1).source_topic == "orders.events"
    assert entry(1, source="a.b.c/12/345").source_topic == "a.b.c"
    assert entry(1, source=None).source_topic is None
    assert entry(1, source="garbage").source_topic is None


def test_summary_groups_by_source_type_reason_and_group():
    rows = summarize(
        [
            entry(1),
            entry(2),
            entry(3, event_type="OrderCancelled"),
            entry(4, group="ledger"),
            marker("id-1"),
        ]
    )

    assert [r["count"] for r in rows] == [2, 1, 1]
    top = rows[0]
    assert (top["source_topic"], top["event_type"], top["group"]) == (
        "orders.events",
        "OrderCreated",
        "payments",
    )
    assert top["already_replayed"] == 1


def test_replay_selects_by_event_type_and_limit_in_order():
    entries = [entry(1), entry(2, event_type="OrderCancelled"), entry(3), entry(4)]

    result = select_for_replay(entries, event_type="OrderCreated", limit=2)

    assert [e.offset for e in result.selected] == [1, 3]


def test_replay_skips_what_was_already_replayed_unless_forced():
    entries = [
        entry(1),
        entry(2),
        entry(3, extra=[("dlq_replayed", b"2026-01-01")]),
        marker("id-1"),
    ]

    safe = select_for_replay(entries)
    forced = select_for_replay(entries, force=True)

    assert [e.offset for e in safe.selected] == [2]
    assert [e.offset for e in safe.skipped_replayed] == [1, 3]
    assert [e.offset for e in forced.selected] == [1, 2, 3]


def test_entries_without_a_valid_source_are_never_replayed():
    result = select_for_replay([entry(1, source=None), entry(2)], force=True)

    assert [e.offset for e in result.selected] == [2]
    assert [e.offset for e in result.skipped_invalid] == [1]


def test_replay_headers_drop_failure_metadata_and_mark_the_replay():
    now = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)

    headers = dict(replay_headers(entry(1, extra=[("traceparent", b"00-aa-bb-01")]), now))

    assert "dlq_reason" not in headers
    assert "dlq_source" not in headers
    assert "dlq_group" not in headers
    assert headers["event_id"] == b"id-1"
    assert headers["event_type"] == b"OrderCreated"
    assert headers["traceparent"] == b"00-aa-bb-01"
    assert headers["dlq_replayed"] == now.isoformat().encode()
    assert headers["dlq_replayed_from"] == b"orders.events.dlq/0/1"
