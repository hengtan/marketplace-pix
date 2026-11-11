from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient

DLQ_REASON = "dlq_reason"
DLQ_SOURCE = "dlq_source"
DLQ_GROUP = "dlq_group"
DLQ_REPLAYED = "dlq_replayed"
DLQ_REPLAYED_FROM = "dlq_replayed_from"
DLQ_MARKER = "dlq_marker"
DLQ_REPLAY_OF = "dlq_replay_of"
STRIPPED_ON_REPLAY = {DLQ_REASON, DLQ_SOURCE, DLQ_GROUP, DLQ_REPLAYED, DLQ_REPLAYED_FROM}


@dataclass(frozen=True, slots=True)
class DlqEntry:
    dlq_topic: str
    partition: int
    offset: int
    timestamp_ms: int
    key: bytes | None
    value: bytes | None
    headers: list[tuple[str, bytes]]

    @property
    def header_map(self) -> dict[str, str]:
        return {name: value.decode(errors="replace") for name, value in self.headers if value}

    @property
    def event_id(self) -> str:
        return self.header_map.get("event_id", "")

    @property
    def event_type(self) -> str:
        return self.header_map.get("event_type", "unknown")

    @property
    def reason(self) -> str:
        return self.header_map.get(DLQ_REASON, "unknown")

    @property
    def group(self) -> str:
        return self.header_map.get(DLQ_GROUP, "unknown")

    @property
    def source_topic(self) -> str | None:
        source = self.header_map.get(DLQ_SOURCE)
        if not source or source.count("/") < 2:
            return None
        return source.rsplit("/", 2)[0]

    @property
    def was_replayed(self) -> bool:
        return DLQ_REPLAYED in self.header_map

    @property
    def is_marker(self) -> bool:
        return DLQ_MARKER in self.header_map

    @property
    def position(self) -> str:
        return f"{self.dlq_topic}/{self.partition}/{self.offset}"


@dataclass(slots=True)
class ReplayResult:
    selected: list[DlqEntry] = field(default_factory=list)
    skipped_replayed: list[DlqEntry] = field(default_factory=list)
    skipped_invalid: list[DlqEntry] = field(default_factory=list)
    sent: int = 0
    dry_run: bool = True


async def _partitions(bootstrap: str, topic: str) -> list[int]:
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        (description,) = await admin.describe_topics([topic])
    finally:
        await admin.close()
    if description.get("error_code"):
        raise SystemExit(f"topic {topic!r} not found")
    return sorted(int(p["partition"]) for p in description["partitions"])


async def read_entries(bootstrap: str, topic: str) -> list[DlqEntry]:
    partitions = await _partitions(bootstrap, topic)
    consumer = AIOKafkaConsumer(
        bootstrap_servers=bootstrap,
        group_id=f"dlq-tool-{uuid4().hex[:8]}",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    entries: list[DlqEntry] = []
    try:
        assigned = [TopicPartition(topic, p) for p in partitions]
        consumer.assign(assigned)
        await consumer.seek_to_beginning(*assigned)
        ends = await consumer.end_offsets(assigned)
        pending = {tp for tp in assigned if ends[tp] > 0}
        while pending:
            batches = await consumer.getmany(timeout_ms=1000, max_records=500)
            for tp, records in batches.items():
                for record in records:
                    entries.append(_to_entry(record))
                if await consumer.position(tp) >= ends[tp]:
                    pending.discard(tp)
    finally:
        await consumer.stop()
    return sorted(entries, key=lambda e: (e.timestamp_ms, e.partition, e.offset))


def _to_entry(record: Any) -> DlqEntry:
    return DlqEntry(
        dlq_topic=record.topic,
        partition=record.partition,
        offset=record.offset,
        timestamp_ms=record.timestamp,
        key=record.key,
        value=record.value,
        headers=[(name, value or b"") for name, value in (record.headers or [])],
    )


def split_markers(entries: Sequence[DlqEntry]) -> tuple[list[DlqEntry], set[str]]:
    messages = [e for e in entries if not e.is_marker]
    replayed_ids = {e.event_id for e in entries if e.is_marker and e.event_id}
    return messages, replayed_ids


def summarize(entries: Sequence[DlqEntry]) -> list[dict[str, Any]]:
    messages, replayed_ids = split_markers(entries)
    counts: Counter[tuple[str, str, str, str]] = Counter()
    replayed: Counter[tuple[str, str, str, str]] = Counter()
    for entry in messages:
        group_key = (
            entry.source_topic or "unknown",
            entry.event_type,
            entry.reason[:120],
            entry.group,
        )
        counts[group_key] += 1
        if entry.was_replayed or entry.event_id in replayed_ids:
            replayed[group_key] += 1
    return [
        {
            "source_topic": source,
            "event_type": event_type,
            "reason": reason,
            "group": group,
            "count": count,
            "already_replayed": replayed[(source, event_type, reason, group)],
        }
        for (source, event_type, reason, group), count in counts.most_common()
    ]


def select_for_replay(
    entries: Sequence[DlqEntry],
    event_type: str | None = None,
    limit: int | None = None,
    force: bool = False,
) -> ReplayResult:
    messages, replayed_ids = split_markers(entries)
    result = ReplayResult()
    for entry in messages:
        if event_type and entry.event_type != event_type:
            continue
        if entry.source_topic is None or entry.key is None or entry.value is None:
            result.skipped_invalid.append(entry)
            continue
        if not force and (entry.was_replayed or entry.event_id in replayed_ids):
            result.skipped_replayed.append(entry)
            continue
        if limit is not None and len(result.selected) >= limit:
            break
        result.selected.append(entry)
    return result


def replay_headers(entry: DlqEntry, now: datetime) -> list[tuple[str, bytes]]:
    kept = [(name, value) for name, value in entry.headers if name not in STRIPPED_ON_REPLAY]
    kept.append((DLQ_REPLAYED, now.isoformat().encode()))
    kept.append((DLQ_REPLAYED_FROM, entry.position.encode()))
    return kept


async def replay(
    bootstrap: str,
    topic: str,
    event_type: str | None = None,
    limit: int | None = None,
    execute: bool = False,
    force: bool = False,
) -> ReplayResult:
    entries = await read_entries(bootstrap, topic)
    result = select_for_replay(entries, event_type=event_type, limit=limit, force=force)
    result.dry_run = not execute
    if not execute or not result.selected:
        return result
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap, acks="all")
    await producer.start()
    try:
        for entry in result.selected:
            now = datetime.now(UTC)
            await producer.send_and_wait(
                str(entry.source_topic),
                key=entry.key,
                value=entry.value,
                headers=replay_headers(entry, now),
            )
            await producer.send_and_wait(
                topic,
                key=entry.key,
                value=b"",
                headers=[
                    (DLQ_MARKER, b"replayed"),
                    (DLQ_REPLAY_OF, entry.position.encode()),
                    (DLQ_REPLAYED, now.isoformat().encode()),
                    ("event_id", entry.event_id.encode()),
                ],
            )
            result.sent += 1
    finally:
        await producer.stop()
    return result
