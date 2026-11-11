import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")


@pytest.fixture
async def topics() -> AsyncIterator[tuple[str, str]]:
    base = f"test.common.{uuid4().hex[:8]}"
    names = [base, f"{base}.dlq"]
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    await admin.create_topics([NewTopic(n, num_partitions=1, replication_factor=1) for n in names])
    yield base, names[1]
    await admin.delete_topics(names)
    await admin.close()
