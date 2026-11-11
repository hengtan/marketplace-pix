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
- [x] Limpeza (TTL) das `idempotency_keys` e das linhas publicadas do outbox (job em lotes em `marketplace_common.maintenance`)

## Fase 2: `payments` (FEITA)
- [x] Domínio `Payment` (PENDING, CONFIRMED, EXPIRED), id determinístico por pedido, regras de confirmar/expirar
- [x] PSP simulado atrás de uma porta (`PspGateway`), idempotente por `reference`
- [x] Consumidor Kafka de `orders.events` com **inbox** (dedupe por `event_id`, na mesma transação da cobrança)
- [x] Webhook com HMAC (401 sem assinatura válida) que ainda **consulta o PSP** antes de confirmar (fail-closed, 409 se não pago)
- [x] Job de expiração (`ExpirePayments`) e eventos `PaymentCreated`, `PaymentConfirmed`, `PaymentExpired` via outbox/relay
- [x] 53 testes (unit + integração com Postgres e Kafka reais), Dockerfile e 4 serviços no compose
- [ ] Mensagem que falha sempre (poison): retry limitado e `orders.events.dlq`
- [x] Limpeza (TTL) do inbox e do outbox publicado
- [x] Reembolso de pagamento tardio (`PaymentRefundRequested`, `PaymentRefunded`, estorno no ledger e estoque devolvido)
- [ ] Cancelar a cobrança no PSP quando expira
- [ ] Extrair outbox, relay e inbox para `backend/libs` (hoje copiados do ordering)

## Fase 3: Saga completa (ordering + payments) (FEITA)
- [x] `ordering` consome `payments.events` com inbox: `PaymentConfirmed` marca o pedido como pago, `PaymentExpired` cancela
- [x] Pedido bloqueado com `FOR UPDATE`: confirmação e expiração concorrentes têm um vencedor só (o outro vira CONFLICT)
- [x] Teste ponta a ponta nos containers: pedido pago e pedido com PIX expirado
- [x] Conflito (pagamento confirmado para pedido já cancelado) vira auditoria em `order_audit` e pedido de reembolso
- [x] Timeout global da saga (`SagaTimeoutManager` no ordering cancela pedido parado em PENDING com `saga timeout`)
- [ ] Orquestrador explícito (a saga continua coreografada por eventos, com o process manager só para o prazo)
- [x] Teste automatizado ponta a ponta entre os serviços (`scripts/e2e.sh` e `scripts/e2e-saga.sh`)

## Fase 4: `ledger` (FEITA)
- [x] Dupla entrada (débitos iguais a créditos, transação desbalanceada é rejeitada)
- [x] Split lojista e plataforma (10% por lojista, arredondamento que sempre fecha)
- [x] Concorrência: 50 pagamentos simultâneos mantêm o saldo exato; teste de propriedade (hypothesis)
- [x] Conciliação (`/reconciliation`) e resumo do lojista com série diária

## Fase 5: `inventory` e `notifications`
- [x] `inventory`: reserva tudo ou nada, sem overselling (100 reservas para 10 unidades aceitam 10), TTL, liberação
- [x] Falta de estoque cancela o pedido e a cobrança (saga completa)
- [x] `notifications`: e-mails via Celery + Mailpit, retry, varredor, resumo diário

## Fase 6: `catalog`, gateway e frontend
- [x] `catalog`: busca sem acento, filtros, ordenação, ETag/304, seed de 24 produtos
- [x] Preço e lojista do pedido vêm do catálogo (o cliente só envia produto e quantidade)
- [x] Gateway: rotas do contrato, CORS, `Idempotency-Key`, `X-Request-Id`, limite de requisições, saúde agregada
- [x] Frontend "Praça" (React 19, Tailwind v4, Radix, Motion, ⌘K, PIX ao vivo, painel do lojista), servido em http://localhost:5173 e verificado no navegador contra o backend real

## Resiliência (FEITA)
- [x] Retentativas limitadas e DLQ (`<tópico>.dlq`) em todos os consumidores
- [x] Ferramenta para reprocessar mensagens da DLQ (`marketplace_common.dlq`, dry-run por padrão, anti-laço)
- [x] Consumidor, outbox e relay extraídos para `backend/libs/marketplace_common`

## Resiliência avançada (FEITA)
- [x] Circuit breaker (janela deslizante, falha e lentidão, sondas no half-open), retry com full jitter e budget, deadline propagation, bulkhead
- [x] Rate limit distribuído no Redis (token bucket em Lua) com fallback e fail-open configuráveis
- [x] Aplicado no gateway, no cliente do PSP, no webhook e no LLM e embedder do assistant
- [x] `scripts/chaos.sh` (catalog, payments e Redis), `scripts/loadtest.py`, painel e alertas de SLO (burn rate)
- [ ] Estado do breaker compartilhado entre réplicas (hoje é por processo)
- [ ] Identificar o cliente pelo `X-Forwarded-For` confiável no rate limit

## Fase 7: IA
- [ ] RAG sobre o catálogo (pgvector)
- [ ] Agente com tool use (estoque, status do pedido)
- [ ] Avaliação (Promptfoo) e tracing (Langfuse)

## Fase 8: Plataforma
- [ ] OpenTelemetry, Prometheus, Grafana
- [ ] GitHub Actions (build, teste, deploy)
- [ ] k3d + Helm (local) e Terraform + Azure Container Apps (nuvem, com alerta de orçamento)

## Fase 7: IA (FEITA, com modelos simulados)
- [x] Serviço `assistant`: ingestão com chunking e pgvector (HNSW), busca híbrida com RRF, reranker, filtros, agente com ferramentas, memória e guardrails
- [x] Avaliação com métricas (hit@k, MRR, aderência ao contexto) que falha o build abaixo dos limiares
- [x] Interface de chat no frontend (streaming, citações com foto e preço, rastro "Como cheguei nessa resposta", memória)
- [x] Entendimento de consulta: intenção (catálogo, pedido, estoque, política, fora de escopo), reescrita com sinônimos, correção de digitação, negação e decomposição
- [x] Cache semântico (pgvector) com TTL e invalidação por eventos do catálogo (`catalog.events`), métricas de hit rate e economia
- [x] Recuperação avançada: filtros pré-busca, pesos na fusão, MMR, parent-document; variantes comparadas em `docs/RAG-AVALIACAO.md`
- [x] Avaliação: 111 casos (dev e holdout), hit@k, MRR, nDCG, precisão e revocação de contexto, juiz `JudgeLlm`, portão de regressão no CI
- [x] Guardrails: injeção direta e indireta, PII em logs e traces, orçamento por sessão e usuário, saída estruturada com reparo, números verificados contra o trecho citado, 41 ataques no red team
- [x] Observabilidade de LLM: spans por etapa, tokens e custo, painel `assistant` no Grafana
- [x] Streaming com cancelamento, timeouts e fallback para a busca pura
- [ ] `catalog` publicar `catalog.events` (o assistant já consome; hoje o índice só atualiza no reindex)
- [ ] Trocar embeddings e LLM por Ollama (adaptadores prontos e testados contra um servidor HTTP falso, falta rodar com o Ollama real e reavaliar)
- [ ] Serviço `assistant-worker` no `docker-compose` e job no Prometheus

## Fase 8: Plataforma
- [x] OpenTelemetry com traces atravessando o Kafka, métricas Prometheus (RED) e dashboard no Grafana
- [x] CI no GitHub Actions
- [x] `assistant` na observabilidade e no CI (CI cobre todos os serviços, a biblioteca, o assistente e o frontend)
- [ ] Azure (Terraform) e Kubernetes (Helm/k3d): adiados

## Plataforma: segurança, contratos e saga (FEITA)
- [x] Serviço `identity` (argon2id, JWT EdDSA, JWKS, refresh rotativo com detecção de reuso), papéis e escopos
- [x] Gateway valida o token, remove cabeçalhos de identidade do cliente e assina a identidade para os serviços
- [x] Autorização por objeto (pedido do dono) e multi-tenant (ledger, estoque e pedidos do lojista), com testes de BOLA e de isolamento
- [x] Versionamento de eventos: `schema_version`, modelos por versão, upcasters, golden files e testes de contrato; `OrderCreated` v2
- [x] Retenção em lotes de outbox, inbox, idempotência e refresh tokens
- [x] Timeout global da saga e pagamento tardio reembolsado de forma idempotente e auditável
- [x] `docs/SEGURANCA.md` e `docs/EVOLUCAO-DE-EVENTOS.md`
- [ ] MFA, cookie `HttpOnly` por BFF, revogação imediata do access token, cadastro em massa (ver limitações em `docs/SEGURANCA.md`)
