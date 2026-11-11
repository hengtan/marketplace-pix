**English** | [Português (Brasil)](pt-BR/EVOLUCAO-DE-EVENTOS.md)

# Event evolution

How to change the shape of a Kafka event without breaking producers, consumers, and the messages already on
the topic. The code is in `backend/libs/marketplace_common/src/marketplace_common/events/`.

## 1. The problem

In a Kafka-based system, producer and consumer do not deploy together. When `ordering` starts publishing a new
field, all of the following exist at the same time:

- old consumers, which have never heard of the field;
- new consumers, which may receive old messages (the topic keeps history, the DLQ keeps failures, and a
  reprocess redelivers what already went by);
- the producer itself, which needs to guarantee that nothing changed by accident.

Without discipline, the first field `rename` takes the ledger down in production. The answer here has three
parts: a **versioned envelope**, **models and upcasters** in the library, and **contract tests** with golden
files.

## 2. The envelope

Every message carries its version in two places, so you can filter without opening the JSON and so the payload
stays readable outside Kafka (DLQ, replay, logs):

| Where | Field |
|---|---|
| Kafka header | `schema_version` (the integer as text) |
| JSON body | `"schema_version": 2` |

The producer writes the version to the outbox (`marketplace_common.events.serialize_event` reads the
`schema_version` class attribute of the domain event, default 1). `KafkaPublisher` copies it to the header. The
consumer's `IncomingEvent` reads the header, then the body, and if both are missing it assumes `1`, which is
the case for every message published before this change.

## 3. Versioned models and upcasters

Each event type has one pydantic model per version (`OrderCreatedV1`, `OrderCreatedV2`, ...), registered in
`REGISTRY`. The models ignore unknown fields (`extra="ignore"`), which is what makes reading forward compatible.

An **upcaster** migrates the payload from one version to the adjacent one. The registry chains as many as
needed (v1 → v2 → v3), so a new consumer reads any message from history as if it were the newest version.
There is also a **downcaster**, used when a producer needs to serve an old version.

```python
event.parse()                                   # IncomingEvent -> newest-version model (automatic upcast)
REGISTRY.parse_as("OrderCreated", payload, 1)   # an old reader reading new data
REGISTRY.downcast("OrderCreated", payload, 1)   # v2 -> v1
```

Reading rules:

| Situation | Behavior |
|---|---|
| Message older than the consumer | upcast up to the newest version the consumer knows |
| Message newer than the consumer | read with the newest model it knows, ignore the rest, and log a warning |
| A version with no upcaster in the middle of the chain | explicit error (`UnknownEvent`), never a guess |
| Payload invalid for the model | `ValidationError`, and the consumer follows the normal retry and DLQ path |

## 4. Compatible or incompatible

| Change | Class | What to do |
|---|---|---|
| New **optional** field | compatible | new model version, an upcaster that fills in the default, a new golden file |
| New required field | incompatible | a new event type, or an optional field instead of a required one |
| Remove a field | incompatible | publish both versions for a period (dual publish) and only then retire it |
| Rename a field | incompatible | add the new name as optional, migrate consumers, remove the old one later |
| Change type or semantics (e.g. cents to dollars) | incompatible | a new event type |

Rollout order for a compatible change: **consumers first** (they already tolerate the field because they ignore
what they do not know), producer last. For an incompatible change, the producer publishes both forms until the
last consumer has migrated.

## 5. Contract tests (golden files)

In `events/golden/` there is one JSON per type and version (`OrderCreated.v2.json`, ...), written by hand and
reviewed like code. The `assert_producer_contract(type, payload)` helper compares what the producer actually
serializes against the golden file **and** against the model. It fails, saying which fields are missing, extra,
or changed, when someone:

- removes or renames a field;
- adds a field without declaring it (the test requires the model to know everything that goes out);
- changes a type (a date turning into a number, for example);
- forgets to bump the version.

Each producer (`ordering`, `payments`, `inventory`, `ledger`) has `tests/unit/test_event_contract.py` with one
case per event. On the other side, each consumer (`ledger`, `payments`, `inventory`, `notifications`) has
`test_consumer_compatibility.py`, which feeds the handler the golden files of **all** published versions. A new
version lands on both sides: the producer proves it emits what was agreed, and the consumer proves it
understands it.

## 6. The real evolution: `OrderCreated` v2

Motivation: ordering started accepting both guest and authenticated-user checkout, and the consumers
(analytics, emails) want to know the difference. v2 adds `customer_type`, with values `guest` or `registered`,
**optional**.

| | v1 | v2 |
|---|---|---|
| `customer_type` | absent | `guest`, `registered`, or null |
| Upcaster v1 → v2 | | fills `customer_type = null` (the past cannot be known) |
| Downcaster v2 → v1 | | removes `customer_type` |

Proofs, all automated:

1. The producer (`Order.create`) emits `schema_version = 2` with the right type, and the payload is identical to
   golden v2.
2. A new consumer reads golden v1 and gets an `OrderCreatedV2` with `customer_type = None`.
3. A v1 reader reads golden v2 without error (it ignores the new field): forward compatibility.
4. `downcast(upcast(v1)) == v1`: a lossless round trip.
5. With real Kafka, the `schema_version` header leaves the publisher and the consumer parses v1 and v2 messages
   from the same topic into the same model.
6. The four existing consumers process golden v1 and v2 with no code changes.

## 7. What was left out (and why)

- **Schema registry with Avro or Protobuf**: solves the same family of problems with one more service and binary
  serialization. For a study repository using JSON, pydantic models and golden files cover the reasoning, and
  migrating to a registry would mean swapping the source of the models, not the discipline.
- **Consumer validation at the entry of every handler**: only `IncomingEvent.parse()` uses the models. The
  current handlers still read the dictionary and ignore what they do not know.
- **Evolving the envelope itself** (for example, moving `event_id` into an object): that would be an
  incompatible change and would require a new topic.

## 8. Interview talking script

**Likely question:** "How do you evolve an event without breaking consumers?"

> First I separate compatible from incompatible changes. A new optional field is compatible; removing,
> renaming, or changing semantics is not. In the project, every message carries a `schema_version`, in the
> header and in the body, and the shared library has one pydantic model per type and version, with upcasters
> between adjacent versions. The new consumer reads everything, including history, as the newest version. The
> old consumer ignores what it does not know, and that is under test.
>
> What gives me confidence are the contract tests: I keep one golden file per version, and the producer's test
> fails if the payload comes out different, whether a field is missing, extra, or of another type. On the
> consumer side, each service runs its handler against the golden files of all versions. In practice I evolved
> `OrderCreated` to v2 with an optional `customer_type` field, and proved it in both directions: old data in
> the new reader and new data in the old reader.
>
> The rollout order is consumers first, producer after. For an incompatible change I publish both forms until
> the last consumer has migrated, or I create a new event type. If the volume justified it, the next step would
> be a schema registry with compatibility checks in CI, but the discipline is the same.

**Follow-up questions and short answers**

- *What about the messages that were already on Kafka?* Without `schema_version` they count as `1`, and the
  upcaster takes them to the current version.
- *What if a consumer receives a version it does not know?* It reads with the newest model it has, ignores the
  excess, and logs a warning. If an upcaster is missing in the middle of the chain, it fails loudly instead of
  guessing.
- *Why not just trust the consumer's tests?* Because the one who breaks the contract is the producer. The
  golden file turns the contract into a versioned artifact that CI compares on every change.
- *What does it cost?* Migration code to maintain and golden files to review. It pays off as long as there is
  more than one independent consumer, which is exactly when the problem shows up.
