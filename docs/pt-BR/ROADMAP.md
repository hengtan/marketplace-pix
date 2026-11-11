[English](../ROADMAP.md) | **Português (Brasil)**

# Roadmap

Regra de trabalho: em toda fase, escreva os testes antes da parte difícil e tente quebrar de propósito (a mesma requisição duas vezes, matar um worker no meio, uma mensagem duplicada, uma dependência que cai).

## Entregue

### Domínio central e saga
- [x] `ordering`: agregado `Order`, value object `Money`, Unit of Work, `Idempotency-Key` reivindicada na mesma transação do pedido (testada com 5 requisições concorrentes), outbox com contexto de trace, relay para o Kafka com chave = id do pedido
- [x] `payments`: cobrança PIX atrás de uma porta de PSP (idempotente por referência), webhook HMAC que ainda consulta o PSP antes de confirmar (fail-closed), inbox, job de expiração, cobrança cancelada no PSP ao expirar
- [x] Saga coreografiada entre `ordering`, `payments`, `inventory`, `ledger` e `notifications`; linha do pedido travada com `FOR UPDATE` para que confirmar e expirar concorrentes tenham um só vencedor
- [x] Timeout global da saga (`SagaTimeoutManager`), e um pagamento tardio é reembolsado de forma idempotente e auditada (`PaymentRefundRequested`, `PaymentRefunded`, estorno no ledger, estoque devolvido)
- [x] `ledger`: dupla entrada que rejeita transação desbalanceada, split de 10% da plataforma com arredondamento que sempre fecha, 50 pagamentos concorrentes mantêm o saldo exato, endpoint de conciliação
- [x] `inventory`: reserva tudo-ou-nada com TTL (100 reservas para 10 unidades aceitam exatamente 10), liberação e devolução no reembolso, linha de estoque criada automaticamente quando um produto nasce, produtos desativados saem da lista do lojista
- [x] `notifications`: e-mails por Celery e Mailpit, retry, sweeper, resumo diário
- [x] `catalog`: busca sem acento, filtros, ordenação, ETag e revalidação, API de escrita do lojista (criar, editar, desativar, reativar, lista do dono), `catalog.events` por outbox, seed que nunca sobrescreve edições do lojista

### Resiliência
- [x] Retentativas limitadas e fila de mensagens mortas (`<tópico>.dlq`) em todo consumidor, mais uma ferramenta de reprocesso (`marketplace_common.dlq`, simulação por padrão)
- [x] Circuit breaker (janela deslizante, taxas de falha e de chamadas lentas, sondas no half-open), retry com full jitter e orçamento de retries, propagação de deadline, bulkhead
- [x] Rate limit distribuído em Redis (token bucket em Lua) com modo de falha configurável, `X-Forwarded-For` confiável
- [x] Aplicado ao gateway, ao cliente do PSP, ao webhook, e ao LLM e embedder do assistente
- [x] Estado do breaker compartilhado entre réplicas, opcional (`BREAKER_SHARED_STATE`)
- [x] `scripts/chaos.sh`, `scripts/loadtest.py`, dashboard de SLO e alertas de burn rate

### Segurança e plataforma
- [x] Serviço `identity`: argon2id, JWT EdDSA com JWKS, refresh rotativo com detecção de reuso, papéis e escopos
- [x] O gateway valida o token, remove os headers de identidade do cliente e assina a identidade para os serviços
- [x] Autorização por objeto e multi-tenant (ledger, estoque e pedidos do lojista), com testes de BOLA e de isolamento
- [x] Revogação do access token, limite de cadastro e login com backoff progressivo, headers de segurança, limite de tamanho do corpo
- [x] Versionamento de eventos (`schema_version`, upcasters, arquivos golden, testes de contrato), retenção em lotes de outbox, inbox, chaves de idempotência e refresh tokens

### IA
- [x] Serviço `assistant`: chunking, pgvector HNSW, busca híbrida com RRF, reranker, filtros, laço de agente com ferramentas, memória, guardrails
- [x] Entendimento de consulta, cache semântico com invalidação por eventos, MMR, recuperação parent-document
- [x] Avaliação com 111 casos e portão de regressão no CI; 41 ataques red team contidos; spans OpenTelemetry por etapa, métricas de tokens e custo, streaming com cancelamento e fallback gracioso
- [x] Os modelos são simulados atrás de interfaces (embeddings por feature hashing, LLM determinístico); os adaptadores Ollama estão prontos e testados contra um servidor HTTP falso

### Frontend
- [x] Loja "Praça" (React 19, Tailwind v4, Radix, Motion, ⌘K): fluxo PIX ao vivo, chat do assistente com citações e rastro, login e cadastro
- [x] Painel do lojista com cinco abas endereçáveis por URL (visão geral, pedidos, estoque, produtos, extrato), edição inline de estoque com rollback, reativação de produtos desativados, atalhos de teclado, exportação CSV
- [x] Lighthouse desktop 99, axe limpo em todas as rotas nos temas claro e escuro, transições de rota que respeitam `prefers-reduced-motion`

### Qualidade e entrega
- [x] Traces OpenTelemetry que atravessam o Kafka, métricas RED no Prometheus, dashboards no Grafana (marketplace, resiliência, assistente)
- [x] GitHub Actions com jobs por serviço de lint, formato, tipos estritos, unitários e integração, o portão de regressão do RAG e o job do frontend
- [x] Scripts de ponta a ponta: `scripts/e2e.sh` (114 verificações), `scripts/e2e-saga.sh` (27), `scripts/chaos.sh` (40)

## Ainda não construído

- [ ] Azure com Terraform (Container Apps ou AKS, Key Vault, alerta de orçamento) e Kubernetes com Helm (k3d local): adiados de propósito
- [ ] Modelos reais via Ollama (ou um provedor gerenciado) e nova avaliação contra os mesmos 111 casos
- [ ] MFA, verificação de e-mail e cookie `HttpOnly` para o refresh por um BFF (veja as limitações em `docs/pt-BR/SEGURANCA.md`)
- [ ] Um orquestrador explícito da saga (a saga é coreografada, com um process manager só para o prazo)
- [ ] Um job de coleta do Prometheus para o `assistant-worker`
- [ ] SSR ou prerender da home da loja para levar o Lighthouse mobile de 88 a 91 para um 90 ou mais estável
- [ ] Um teste que rode as migrações Alembic de cada serviço do zero
