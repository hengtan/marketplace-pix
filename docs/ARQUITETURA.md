# Arquitetura

## Visão geral

Microsserviços com banco próprio, comunicação assíncrona por eventos (Kafka) e saga orquestrada pelo `ordering`.
Chamadas síncronas só na borda (gateway para serviço) e em consultas simples.

## Fluxo de uma compra

1. `POST /orders` (com `Idempotency-Key`): o ordering grava o pedido `PENDENTE` e o evento `OrderCreated` no outbox, na mesma transação. Responde 202.
2. O relay publica `OrderCreated`. O inventory reserva o estoque (TTL) e publica `StockReserved`.
3. O ordering pede a cobrança. O payments gera o PIX (QR e copia e cola, com expiração) e publica `PaymentRequested`.
4. O PSP chama o webhook. O payments valida a assinatura E consulta a cobrança no PSP antes de confirmar. Publica `PaymentConfirmed`.
5. O ledger lança as entradas (cliente, plataforma, lojista). O ordering marca `PAGO`. O notifications avisa o cliente.
6. Falha ou expiração: a saga compensa (libera estoque, cancela cobrança, marca `CANCELADO`).

## Saga: timeout global e pagamento tardio

O ordering roda um **process manager** (`SagaTimeoutManager`, no `worker_main`) que varre os pedidos parados em
`PENDING` além de `SAGA_TIMEOUT_SECONDS` (padrão 2700, acima do TTL do PIX). Cada pedido preso é cancelado com
`saga timeout`, vira uma linha em `order_audit` e emite `OrderCancelled`. As compensações são reações a esse
evento, todas idempotentes: o payments cancela a cobrança no PSP e o inventory libera a reserva.

Se um pagamento chega **depois** do cancelamento (o PSP confirmou quase junto com o prazo), o ordering não
reabre o pedido: grava a anomalia em `order_audit` (chave única por pedido e pagamento) e emite
`PaymentRefundRequested`. O payments reembolsa no PSP e emite `PaymentRefunded`, o ledger lança o estorno
(uma transação `REVERSAL` que zera as contas) e o inventory devolve à prateleira a venda que já tinha sido
confirmada. Cada passo tem inbox, e o resultado é o mesmo com mensagem repetida ou fora de hora.

```
pedido PENDING ──(prazo)──► CANCELLED + order_audit(SAGA_TIMEOUT) + OrderCancelled
                                   ├─► payments: cancela a cobrança
                                   └─► inventory: libera a reserva
PaymentConfirmed (tardio) ─► ordering: order_audit(LATE_PAYMENT) + PaymentRefundRequested
                                   └─► payments: reembolsa no PSP ─► PaymentRefunded
                                          ├─► ledger: estorno (REVERSAL)
                                          └─► inventory: devolve o estoque vendido
```

Verificação ponta a ponta com prazo curto: `scripts/e2e-saga.sh`.

## Kafka e Celery: papéis separados

- Kafka: eventos de domínio (fatos). Tópicos `orders.events`, `payments.events`, `inventory.events`, `ledger.events`, 3 partições, chave `order_id` (ordem por pedido). Cada serviço é um consumer group.
- Celery com Redis como broker: tarefas (e-mail, conciliação diária).
- Kafka entrega ao menos uma vez e o rebalanceamento reprocessa: o inbox é obrigatório. Retry e DLQ por tópicos `*.retry` e `*.dlq`, implementados por nós.

## Padrões

| Padrão | Onde | Regra |
|---|---|---|
| Unit of Work | todo caso de uso | uma transação por caso de uso |
| Outbox | produtor de eventos | evento gravado junto com o dado, relay publica depois |
| Inbox | consumidor de eventos | grava `message_id` antes de processar; duplicado é ignorado |
| Idempotência HTTP | POSTs críticos | `Idempotency-Key` guarda a resposta da 1ª chamada |
| Saga (orquestração) | ordering | cada passo tem compensação; timeout dispara compensação |
| Fail-closed | webhook de PIX | na dúvida, o pedido continua pendente |
| Circuit breaker, retry com budget, bulkhead | chamadas entre serviços | cada dependência com o seu; retry só em leitura (ver `docs/RESILIENCIA.md`) |
| Deadline propagation | gateway e serviços | `X-Request-Deadline` com o tempo restante; cada salto limita o timeout a ele |
| Rate limit distribuído | gateway | token bucket em Lua no Redis, por cliente e rota, com fallback em memória |

## Tabelas-chave

```sql
outbox_events(id, aggregate_id, type, payload jsonb, created_at, published_at NULL)
inbox_messages(message_id PK, consumer, processed_at)
idempotency_keys(key, request_hash, response jsonb, status, created_at)
ledger_entries(id, transaction_id, account_id, amount, direction)
```

## Clean Architecture por serviço

```
interface -> application -> domain
infrastructure -> application, domain
```

O `domain` é Python puro. Dá pra travar a regra no CI com `import-linter`.
DDD completo em ordering, payments e ledger. Catalog e notifications podem ser simples.

## Decisões

Registrar em `docs/adr/` (um arquivo por decisão: contexto, decisão, consequências).
