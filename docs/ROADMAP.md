# Roadmap

Regra de ouro: em cada fase, escrever os testes antes da parte difícil e tentar quebrar de propósito
(mesma requisição duas vezes, derrubar o worker no meio, mensagem duplicada).

## Fase 0: Fundação (infra local)
- [x] Estrutura de pastas e README
- [x] `docker compose up` sobe Postgres, Redis e Kafka (com tópicos criados)
- [ ] Padrão de serviço definido (template reaproveitado pelos demais)

## Fase 1: `ordering` (ATACAR PRIMEIRO)
Motivo: é o coração. Aqui moram o domínio (DDD), o ACID com Unit of Work, o outbox e depois a saga.
- [x] Agregado `Order`, value object `Money`, eventos de domínio
- [x] Caso de uso: criar pedido (UoW + porta)
- [x] Caso de uso: consultar pedido
- [ ] Caso de uso: cancelar pedido
- [x] `Idempotency-Key` no POST (claim na mesma transação do pedido; teste com 5 requisições concorrentes)
- [x] API FastAPI (`POST /orders`, `GET /orders/{id}`, `/health`, `/ready`) + Dockerfile + compose (profile `services`)
- [x] Tabela `outbox_events` gravada na mesma transação do pedido (migração Alembic)
- [x] Relay do outbox publicando no Kafka (chave = order_id)
- [x] Testes: unit do domínio, integração com Postgres e Kafka reais
- [ ] Teste que roda as migrações Alembic do zero
- [ ] Preço vindo do catálogo (hoje o cliente envia `unit_price_cents`)
- [ ] Limpeza (TTL) das `idempotency_keys` e das linhas publicadas do outbox

## Fase 2: `payments`
- [ ] PSP simulado (adapter) e cobrança PIX com expiração
- [ ] Consumidor com **inbox** (dedupe por message_id)
- [ ] Webhook com HMAC e confirmação consultando o PSP (fail-closed)
- [ ] Eventos `PagamentoConfirmado` e `PagamentoExpirado`

## Fase 3: Saga completa (ordering + payments)
- [ ] Orquestrador no ordering, com compensação e timeout
- [ ] Testes de falha: serviço fora do ar, evento duplicado, PIX expirado

## Fase 4: `ledger`
- [ ] Dupla entrada (soma de débitos = soma de créditos)
- [ ] Split lojista e plataforma
- [ ] Teste de concorrência

## Fase 5: `inventory` e `notifications`
- [ ] Reserva de estoque com TTL e compensação
- [ ] Celery para e-mail e conciliação diária

## Fase 6: `catalog`, gateway e frontend
- [ ] Catálogo e busca
- [ ] Gateway
- [ ] Front: listagem, carrinho, checkout PIX, status do pedido em tempo real (SSE), painel do lojista
- [ ] Cliente TypeScript gerado do OpenAPI

## Fase 7: IA
- [ ] RAG sobre o catálogo (pgvector)
- [ ] Agente com tool use (estoque, status do pedido)
- [ ] Avaliação (Promptfoo) e tracing (Langfuse)

## Fase 8: Plataforma
- [ ] OpenTelemetry, Prometheus, Grafana
- [ ] GitHub Actions (build, teste, deploy)
- [ ] k3d + Helm (local) e Terraform + Azure Container Apps (nuvem, com alerta de orçamento)
