# Contratos do projeto

Fonte única de verdade para eventos, APIs, portas e dados de seed. Quem implementa um serviço segue este
documento. Se precisar mudar algo, registre a mudança no relatório final em vez de alterar este arquivo.

## 1. Regras do repositório

- Commitar ao terminar cada item (commits pequenos, mensagem em inglês, no imperativo). A identidade do git já está configurada.
- Nenhum trailer de coautoria e nenhuma menção a ferramentas de IA em código, comentários, docs ou mensagens de commit.
- **Nunca** dar `git push`.
- Mexer apenas na própria pasta. Arquivos compartilhados (`infra/docker-compose.yml`, `README.md`, `docs/`, `.env*`, outros serviços) só o integrador altera: descreva no relatório o que precisa mudar.
- Não derrubar nem reiniciar containers em execução. Não matar processos do Chrome.
- Textos para o usuário em pt-BR correto (acentos, concordância). Sem travessão (a pontuação longa de travessão) em nenhum texto ou copy.
- Código em inglês, sem comentários desnecessários.

## 2. Portas

| Serviço | Porta host | Container |
|---|---|---|
| gateway | 8000 | `gateway` |
| ordering | 8001 | `ordering-api` |
| payments | 8002 | `payments-api` |
| catalog | 8003 | `catalog-api` |
| inventory | 8004 | `inventory-api` |
| ledger | 8005 | `ledger-api` |
| notifications | 8006 | `notifications-api` |
| frontend (dev) | 5173 | n/a |
| Mailpit (SMTP / UI) | 1025 / 8025 | `mailpit` |

Infra já em execução (use nos testes de integração): Postgres `localhost:5433` (usuário e senha no `.env` da raiz),
Kafka `localhost:9094`, Redis `localhost:6380`. Bancos existentes: `ordering`, `payments`, `ledger`, `inventory`,
`catalog`, `notifications`. Cada serviço só acessa o seu banco e usa `<serviço>_test` nos testes.
Em uma worktree o `.env` não existe (é ignorado pelo git): copie com
`cp /Users/hengtan/Documents/git/estudos/marketplace-pix/.env .env`.

## 3. Padrão de serviço Python

Copie a estrutura e as convenções de `backend/services/payments` (e `ordering`): Python 3.13, `uv`, FastAPI,
SQLAlchemy 2 async, Alembic, Pydantic v2, aiokafka, pytest + pytest-asyncio, `ruff` (linha 100), `mypy --strict`.

- Camadas: `domain` (puro) → `application` (casos de uso + ports) → `infrastructure` → `interface`.
- Cada caso de uso roda em um Unit of Work (uma transação).
- Produtor de eventos: **outbox** (tabela `outbox_events`, índice parcial) + relay (`relay_main.py`).
- Consumidor de eventos: **inbox** (`inbox_messages`, PK `(message_id, consumer)`), commit manual de offset,
  `KafkaEventConsumer` de `payments/infrastructure/messaging/kafka_consumer.py`.
- Pontos de entrada: `main.py` (API), `worker_main.py` (consumidores e jobs), `relay_main.py` (outbox).
- Config via `pydantic-settings` (variáveis de ambiente, `.env` da raiz quando existir) com `load_settings()`.
- `GET /health` e `GET /ready` em toda API. Dockerfile multi-stage igual ao do `payments`.
- Testes: unitários com fakes (que só efetivam no `commit` e limpam o buffer de eventos ao persistir) e de
  integração contra Postgres, Kafka e Redis reais, sempre em banco `<serviço>_test` e tópicos com nome aleatório.
- Todo caso de falha relevante (duplicidade, concorrência, queda no meio) tem teste.

## 4. Eventos (Kafka)

Mensagem: chave = `order_id` (texto), valor = JSON, headers `event_id` (uuid) e `event_type`.
Consumidores deduplicam por `event_id` (inbox) e ignoram tipos que não tratam. Datas em ISO 8601 UTC.
Grupo de consumo = nome do serviço (se houver mais de um consumidor no serviço, sufixo: `ledger-orders`).

### orders.events (produtor: ordering)

| Evento | Campos |
|---|---|
| `OrderCreated` | `order_id`, `customer_id`, `customer_name`, `customer_email`, `total_cents`, `currency`, `items[]` com `product_id`, `merchant_id`, `quantity`, `unit_price_cents`; mais `event_id`, `occurred_at` |
| `OrderPaid` | `order_id`, `event_id`, `occurred_at` |
| `OrderCancelled` | `order_id`, `reason`, `event_id`, `occurred_at` |

### payments.events (produtor: payments)

| Evento | Campos |
|---|---|
| `PaymentCreated` | `order_id`, `payment_id`, `amount_cents`, `currency`, `pix_code`, `expires_at` |
| `PaymentConfirmed` | `order_id`, `payment_id`, `amount_cents`, `currency` |
| `PaymentExpired` | `order_id`, `payment_id` |
| `PaymentCancelled` | `order_id`, `payment_id` |

### inventory.events (produtor: inventory)

| Evento | Campos |
|---|---|
| `StockReserved` | `order_id` |
| `StockRejected` | `order_id`, `reason`, `missing[]` com `product_id`, `requested`, `available` |
| `StockCommitted` | `order_id` |
| `StockReleased` | `order_id`, `reason` |

### ledger.events (produtor: ledger)

| Evento | Campos |
|---|---|
| `LedgerTransactionPosted` | `order_id`, `transaction_id`, `total_cents`, `platform_fee_cents` |

### Quem consome o quê

| Serviço | Consome | Reage |
|---|---|---|
| payments | `OrderCreated`, `OrderCancelled` | cria cobrança; cancela cobrança pendente |
| ordering | `PaymentConfirmed`, `PaymentExpired`, `StockRejected` | marca pago; cancela (`payment expired`); cancela (`out of stock`) |
| inventory | `OrderCreated`, `PaymentConfirmed`, `PaymentExpired`, `PaymentCancelled`, `OrderCancelled` | reserva; confirma a venda; libera |
| ledger | `OrderCreated`, `PaymentConfirmed` | guarda a projeção do pedido; lança a transação |
| notifications | `OrderCreated`, `PaymentCreated`, `OrderPaid`, `OrderCancelled` | envia e-mails (Celery) |

## 5. APIs REST (todas atrás do gateway)

O frontend fala **só** com o gateway, em `http://localhost:8000`. As tabelas abaixo mostram o caminho
no gateway e o caminho real no serviço. O gateway implementa exatamente estas regras de reescrita:

- `/api/catalog/<resto>` → catalog `/<resto>`
- `/api/inventory/<resto>` → inventory `/<resto>`
- `/api/ledger/<resto>` → ledger `/<resto>`
- `/api/orders` e `/api/orders/<resto>` → ordering `/orders` e `/orders/<resto>`
- `/api/payments/by-order/<resto>` → payments `/payments/by-order/<resto>`
- `/api/payments/dev/<resto>` → payments `/dev/<resto>`
- `/api/notifications` e `/api/notifications/<resto>` → notifications `/notifications` e `/notifications/<resto>`
- `GET /api/health` → agrega o `/health` de todos os serviços

Listas paginadas: `{ "items": [...], "total": 0, "page": 1, "page_size": 20 }`. Dinheiro sempre em centavos
inteiros (`*_cents`) com `currency` ("BRL"). IDs em uuid. Erros: `{ "detail": "texto" }`.

### catalog (porta 8003)

| Gateway | Serviço |
|---|---|
| `GET /api/catalog/products` | `GET /products` |
| `GET /api/catalog/products/{id}` | `GET /products/{id}` |
| `GET /api/catalog/products/slug/{slug}` | `GET /products/slug/{slug}` |
| `GET /api/catalog/products/by-ids?ids=a,b` | `GET /products/by-ids?ids=a,b` |
| `GET /api/catalog/categories` | `GET /categories` |

`GET /products` aceita `q`, `category`, `min_price_cents`, `max_price_cents`, `sort`
(`relevance|price_asc|price_desc|newest|rating`), `page`, `page_size` (padrão 12, máximo 48).

`GET /products/by-ids` devolve o envelope paginado (`items`, `total`, `page`, `page_size`), na ordem pedida,
ignora ids desconhecidos e aceita no máximo 100 ids (422 se `ids` faltar ou for inválido). Parâmetros fora do
intervalo devolvem 422 com `detail` em texto.

Produto: `id`, `slug`, `name`, `description`, `price_cents`, `currency`, `category`, `image_url` (pode ser nulo),
`rating` (0 a 5), `reviews_count`, `tags[]`, `merchant` (`id`, `slug`, `name`), `created_at`.
Categoria: `slug`, `label`, `count`.

### inventory (porta 8004)

| Gateway | Serviço |
|---|---|
| `GET /api/inventory/stock?product_ids=a,b` | `GET /stock?product_ids=a,b` → `[{product_id, available, reserved}]` |
| `GET /api/inventory/stock/{product_id}` | `GET /stock/{product_id}` |
| `PUT /api/inventory/stock/{product_id}` | `PUT /stock/{product_id}` com `{ "available": 10 }` |

### ordering (porta 8001)

| Gateway | Serviço |
|---|---|
| `POST /api/orders` | `POST /orders` (header `Idempotency-Key` obrigatório) |
| `GET /api/orders/{id}` | `GET /orders/{id}` |
| `GET /api/orders?customer_id=&page=&page_size=` | `GET /orders?...` |

`POST` corpo: `customer_id`, `customer_name`, `customer_email`, `items[]` com `product_id` e `quantity`.
**O preço e o `merchant_id` vêm do catálogo**, nunca do cliente. Resposta `201`: `{ "id": "..." }`.
Pedido: `id`, `customer_id`, `customer_name`, `customer_email`, `status` (`PENDING|PAID|CANCELLED`), `currency`,
`total_cents`, `created_at`, `cancel_reason` (nulo), `items[]` (`product_id`, `merchant_id`, `quantity`, `unit_price_cents`).

### payments (porta 8002)

| Gateway | Serviço |
|---|---|
| `GET /api/payments/by-order/{order_id}` | `GET /payments/by-order/{order_id}` |
| `POST /api/payments/dev/psp/charges/{charge_id}/pay` | `POST /dev/psp/charges/{charge_id}/pay` (só desenvolvimento) |

Pagamento: `id`, `order_id`, `status` (`PENDING|CONFIRMED|EXPIRED|CANCELLED`), `amount_cents`, `currency`,
`pix_code`, `psp_charge_id`, `expires_at`, `confirmed_at`.

### ledger (porta 8005)

| Gateway | Serviço |
|---|---|
| `GET /api/ledger/merchants/{merchant_id}/summary?days=30` | `GET /merchants/{merchant_id}/summary?days=30` |
| `GET /api/ledger/accounts/{account_id}/entries?page=&page_size=` | `GET /accounts/{account_id}/entries?...` |
| `GET /api/ledger/reconciliation` | `GET /reconciliation` |

Resumo do lojista: `merchant_id`, `currency`, `balance_cents` (a receber), `gross_sales_cents`,
`platform_fees_cents`, `net_sales_cents`, `orders_count`, `daily[]` (`date`, `gross_cents`, `net_cents`, `orders`).
Contas: `merchant:<merchant_id>`, `platform:revenue`, `psp:receivable`. Lançamento: `id`, `transaction_id`,
`direction` (`DEBIT|CREDIT`), `amount_cents`, `description`, `order_id`, `created_at`.
Conciliação: `balanced` (soma de débitos igual à de créditos), `total_debits_cents`, `total_credits_cents`,
`transactions_count`, `checked_at`.
Regra de split: taxa da plataforma de 10% (1000 bps) sobre o subtotal de cada lojista, arredondada para o
centavo mais próximo; o lojista recebe o restante. Em cada transação, débitos = créditos.

### notifications (porta 8006)

| Gateway | Serviço |
|---|---|
| `GET /api/notifications?customer_id=&page=&page_size=` | `GET /notifications?...` |
| `GET /api/notifications/{id}/preview` | `GET /notifications/{id}/preview` (HTML) |

Notificação: `id`, `kind` (`ORDER_CREATED|PIX_READY|ORDER_PAID|ORDER_CANCELLED`), `subject`, `status`
(`QUEUED|SENT|FAILED`), `order_id`, `created_at`, `sent_at`.

### gateway (porta 8000)

Proxy reverso FastAPI. Roteia `/api/<serviço>/...` para o serviço, repassa método, corpo, query e headers
relevantes (incluindo `Idempotency-Key`), cria `X-Request-Id`, aplica CORS para `http://localhost:5173`,
agrega `GET /api/health`.

## 6. Dados de seed (determinísticos)

`merchant_id = uuid5(NAMESPACE_URL, "marketplace-pix:merchant:<slug>")`
`product_id  = uuid5(NAMESPACE_URL, "marketplace-pix:product:<slug>")`

Lojistas: `aurora-tech` (Aurora Tech), `casa-lume` (Casa Lume), `trilha-sports` (Trilha Sports).

| Slug | Nome | Categoria | Lojista | Preço (centavos) |
|---|---|---|---|---|
| fone-bluetooth-nova | Fone Bluetooth Nova ANC | tecnologia | aurora-tech | 34990 |
| caixa-som-pulse | Caixa de Som Pulse 360 | tecnologia | aurora-tech | 21990 |
| smartwatch-orbit | Smartwatch Orbit S2 | tecnologia | aurora-tech | 49990 |
| teclado-mecanico-forge | Teclado Mecânico Forge 75% | tecnologia | aurora-tech | 38990 |
| mouse-glide-pro | Mouse sem fio Glide Pro | tecnologia | aurora-tech | 17990 |
| webcam-clear-4k | Webcam Clear 4K | tecnologia | aurora-tech | 25990 |
| carregador-turbo-65w | Carregador Turbo 65W GaN | tecnologia | aurora-tech | 12990 |
| hub-usbc-dock | Hub USB-C Dock 8 em 1 | tecnologia | aurora-tech | 15990 |
| luminaria-arco-dourado | Luminária Arco Dourado | casa | casa-lume | 28990 |
| cafeteira-prensa-francesa | Cafeteira Prensa Francesa | casa | casa-lume | 14990 |
| vaso-ceramica-terra | Vaso de Cerâmica Terra | casa | casa-lume | 8990 |
| manta-algodao-nuvem | Manta de Algodão Nuvem | casa | casa-lume | 19990 |
| jogo-facas-chef | Jogo de Facas Chef | casa | casa-lume | 32990 |
| difusor-aromas-calma | Difusor de Aromas Calma | casa | casa-lume | 11990 |
| relogio-parede-minimal | Relógio de Parede Minimal | casa | casa-lume | 9990 |
| organizador-bambu-set | Organizador de Bambu Set | casa | casa-lume | 7990 |
| tenis-corrida-vento | Tênis de Corrida Vento | esporte | trilha-sports | 45990 |
| mochila-trilha-30l | Mochila de Trilha 30L | esporte | trilha-sports | 31990 |
| garrafa-termica-aco-750 | Garrafa Térmica Aço 750 ml | esporte | trilha-sports | 9990 |
| tapete-yoga-grip | Tapete de Yoga Grip | esporte | trilha-sports | 12990 |
| relogio-gps-trail | Relógio GPS Trail | esporte | trilha-sports | 64990 |
| capacete-bike-aero | Capacete de Bike Aero | esporte | trilha-sports | 27990 |
| corda-pular-speed | Corda de Pular Speed | esporte | trilha-sports | 4990 |
| kit-elasticos-forca | Kit de Elásticos de Força | esporte | trilha-sports | 6990 |

Categorias (`slug` → `label`): `tecnologia` → Tecnologia, `casa` → Casa e decoração, `esporte` → Esporte e aventura.
Estoque inicial (inventory): 25 unidades por produto, exceto `relogio-gps-trail` com 3 e `smartwatch-orbit` com 5
(para exercitar o aviso de "últimas unidades" e o caso de estoque insuficiente).
Imagens: o catálogo guarda `image_url` verificado (HTTP 200) ou nulo; o frontend precisa degradar com elegância.
