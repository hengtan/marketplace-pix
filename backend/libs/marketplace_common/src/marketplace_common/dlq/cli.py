from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence

from marketplace_common.dlq.tool import ReplayResult, read_entries, replay, summarize


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m marketplace_common.dlq",
        description="Inspect and replay dead letter queue topics.",
    )
    parser.add_argument(
        "--bootstrap",
        default=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094"),
        help="Kafka bootstrap servers (default: $KAFKA_BOOTSTRAP_SERVERS or localhost:9094)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="summarize the messages of a .dlq topic")
    listing.add_argument("--topic", required=True, help="DLQ topic, e.g. orders.events.dlq")
    listing.add_argument("--json", action="store_true", help="machine readable output")

    replaying = commands.add_parser("replay", help="republish DLQ messages to their source topic")
    replaying.add_argument("--topic", required=True, help="DLQ topic, e.g. orders.events.dlq")
    replaying.add_argument("--event-type", help="only messages of this event type")
    replaying.add_argument("--limit", type=int, help="replay at most this many messages")
    replaying.add_argument(
        "--yes", action="store_true", help="actually republish (default is a dry run)"
    )
    replaying.add_argument(
        "--force", action="store_true", help="replay messages that were already replayed"
    )
    return parser


async def _list(args: argparse.Namespace) -> int:
    entries = await read_entries(args.bootstrap, args.topic)
    rows = summarize(entries)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print(f"{args.topic}: empty")
        return 0
    total = sum(row["count"] for row in rows)
    print(f"{args.topic}: {total} message(s)")
    print(f"{'COUNT':>5}  {'REPLAYED':>8}  {'SOURCE':<20} {'EVENT TYPE':<24} {'GROUP':<18} REASON")
    for row in rows:
        print(
            f"{row['count']:>5}  {row['already_replayed']:>8}  {row['source_topic']:<20} "
            f"{row['event_type']:<24} {row['group']:<18} {row['reason']}"
        )
    return 0


def _print_replay(result: ReplayResult, topic: str) -> None:
    mode = "DRY RUN (nothing sent, use --yes to replay)" if result.dry_run else "REPLAY"
    print(f"{mode} from {topic}")
    for entry in result.selected:
        print(
            f"  {entry.position} -> {entry.source_topic} "
            f"key={entry.key.decode() if entry.key else ''} "
            f"type={entry.event_type} event_id={entry.event_id}"
        )
    print(
        f"selected={len(result.selected)} sent={result.sent} "
        f"skipped_already_replayed={len(result.skipped_replayed)} "
        f"skipped_invalid={len(result.skipped_invalid)}"
    )
    if result.skipped_replayed:
        print("already replayed messages were skipped, use --force to send them again")


async def _replay(args: argparse.Namespace) -> int:
    result = await replay(
        args.bootstrap,
        args.topic,
        event_type=args.event_type,
        limit=args.limit,
        execute=args.yes,
        force=args.force,
    )
    _print_replay(result, args.topic)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = _list if args.command == "list" else _replay
    return asyncio.run(handler(args))


if __name__ == "__main__":
    sys.exit(main())
