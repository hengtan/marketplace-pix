from __future__ import annotations

import json

from aiokafka import AIOKafkaProducer

from marketplace_common.messaging.events import SCHEMA_VERSION_HEADER
from marketplace_common.messaging.outbox import OutboxMessage
from marketplace_common.observability.tracing import inject_headers


class KafkaPublisher:
    def __init__(self, bootstrap_servers: str) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            acks="all",
            enable_idempotence=True,
        )

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, message: OutboxMessage) -> None:
        headers = [
            ("event_id", str(message.id).encode()),
            ("event_type", message.type.encode()),
            (
                SCHEMA_VERSION_HEADER,
                str(message.payload.get(SCHEMA_VERSION_HEADER, 1)).encode(),
            ),
        ]
        trace_headers = inject_headers()
        if "traceparent" not in trace_headers and message.traceparent:
            trace_headers["traceparent"] = message.traceparent
        headers.extend((name, value.encode()) for name, value in trace_headers.items())
        await self._producer.send_and_wait(
            message.topic,
            key=message.key.encode(),
            value=json.dumps(message.payload).encode(),
            headers=headers,
        )
