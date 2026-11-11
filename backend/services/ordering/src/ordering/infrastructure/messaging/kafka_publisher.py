from __future__ import annotations

import json

from aiokafka import AIOKafkaProducer

from ordering.application.ports import OutboxMessage


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
        await self._producer.send_and_wait(
            message.topic,
            key=message.key.encode(),
            value=json.dumps(message.payload).encode(),
            headers=[
                ("event_id", str(message.id).encode()),
                ("event_type", message.type.encode()),
            ],
        )
