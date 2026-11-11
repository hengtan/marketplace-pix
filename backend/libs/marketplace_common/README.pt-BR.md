# marketplace_common

Biblioteca compartilhada dos microsserviços do marketplace. Reúne o que antes estava copiado em cada serviço
(consumidor Kafka com DLQ, publicador, outbox relay) e o que é transversal a todos (observabilidade e a
ferramenta de reprocesso da DLQ).

```
marketplace_common/
  messaging/       IncomingEvent, KafkaEventConsumer, KafkaPublisher, OutboxRelay e as portas do outbox
  observability/   logs JSON, tracing (OpenTelemetry), métricas (Prometheus), middlewares HTTP
  dlq/             python -m marketplace_common.dlq list | replay
  security/        Principal, papéis e escopos, identidade assinada entre gateway e serviços
  events/          modelos versionados por evento, upcasters, arquivos golden e testes de contrato
  maintenance/     CleanupJob: retenção em lotes do outbox publicado, do inbox e das chaves de idempotência
```

Instalação nos serviços, por caminho e editável (`pyproject.toml` de cada serviço):

```toml
dependencies = ["marketplace-common[kafka,sqlalchemy]"]

[tool.uv.sources]
marketplace-common = { path = "../../libs/marketplace_common", editable = true }
```

Os extras evitam arrastar dependências que o serviço não usa: o gateway instala só o núcleo
(sem `aiokafka` nem SQLAlchemy), os demais pedem `kafka` e `sqlalchemy`.

## 1. Observabilidade

Observabilidade é a capacidade de entender o que acontece dentro de um sistema olhando apenas para o que ele
emite. Monitorar responde "está quebrado?". Observar responde "por que está quebrado e onde?", inclusive para
perguntas que ninguém previu. Ela se apoia em três sinais, e cada um responde a uma pergunta diferente.

| Sinal | O que é | Pergunta que responde | Custo | Neste projeto |
|---|---|---|---|---|
| Logs | Eventos discretos, uma linha por fato | O que aconteceu naquele momento? | Alto em volume | JSON no stdout, com `trace_id`, `span_id` e `request_id` |
| Métricas | Números agregados ao longo do tempo | Quanto, com que frequência, está piorando? | Baixo e constante | Prometheus e Grafana |
| Traces | O caminho de uma requisição por vários serviços | Onde o tempo foi gasto e onde falhou? | Médio (amostrável) | OpenTelemetry e Jaeger |

O valor aparece quando os três se conectam. Um alerta de métrica (erros subiram) leva ao trace de uma
requisição lenta (o span do banco do payments demorou), e o `trace_id` impresso no log abre as linhas exatas
daquela execução.

### Trace e span

- **Span** é uma unidade de trabalho com início, fim, nome e atributos: uma requisição HTTP, uma query SQL, o
  tratamento de um evento. Tem um `span_id` e aponta para o pai (`parent_span_id`).
- **Trace** é a árvore de spans de uma mesma operação de negócio, ligada por um único `trace_id`. Um pedido
  criado vira um trace que atravessa ordering, payments, inventory, ledger e notifications.
- **Contexto** é o par (`trace_id`, `span_id`) que viaja junto da chamada. Em HTTP vai no header `traceparent`
  (padrão W3C), `00-<trace_id>-<span_id>-01`. No Kafka vai nos headers da mensagem, com o mesmo nome.

### Método RED

Para qualquer serviço que atende requisições, três números bastam para saber se ele está saudável:

- **R**ate: quantas requisições por segundo.
- **E**rrors: quantas falham (aqui, respostas 5xx sobre o total).
- **D**uration: quanto demoram, sempre em percentis (p50, p95, p99) e nunca só pela média.

Cada API expõe `http_requests_total{method,route,status}` e `http_request_duration_seconds{method,route}`.
O rótulo `route` usa o template (`/orders/{order_id}`), não o caminho real, para não explodir a cardinalidade
das séries. Caminhos que não casam com nenhuma rota entram como `unmatched`. Para workers, que não atendem
HTTP, o equivalente é o método **USE** (utilização, saturação, erros), representado aqui pela duração dos
handlers, pelo outbox pendente e pela DLQ.

### O que a biblioteca entrega

| Peça | Para que serve |
|---|---|
| `setup_logging(service)` | Troca os handlers do logging por um formatador JSON. Inclui `trace_id` e `span_id` quando há span ativo e `request_id` quando há requisição |
| `setup_tracing(service)` | Liga o OpenTelemetry pelas variáveis `OTEL_*`. Sem `OTEL_EXPORTER_OTLP_ENDPOINT` não faz nada (no-op seguro) |
| `install_api_observability(app, service)` | Numa API FastAPI: logs, tracing, `X-Request-Id`, métricas RED e a rota `GET /metrics` |
| `setup_worker_observability(service)` | Em workers e relays: logs, tracing e um servidor `/metrics` na porta `METRICS_PORT` (padrão 9100) |
| `instrument_sqlalchemy(engine)` | Cada query vira um span filho |
| `current_traceparent()` | Contexto atual como texto, usado para gravar no outbox |

Instrumentação automática: FastAPI (um span por requisição), httpx (chamadas entre serviços, injeta o
`traceparent`) e SQLAlchemy. As rotas `/health`, `/ready` e `/metrics` ficam de fora dos traces.

Variáveis de ambiente (padrão OpenTelemetry):

| Variável | Efeito |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Liga o tracing. Ex.: `http://jaeger:4318` (OTLP sobre HTTP) |
| `OTEL_SERVICE_NAME` | Sobrescreve o nome do serviço que o código informa |
| `OTEL_SDK_DISABLED=true` | Desliga mesmo com endpoint configurado |
| `METRICS_PORT` | Porta do `/metrics` de workers e relays (padrão 9100, `0` desliga) |
| `LOG_LEVEL` | Nível dos logs (padrão `INFO`) |

### Métricas de negócio e de mensageria

| Série | Tipo | Quem emite |
|---|---|---|
| `http_requests_total`, `http_request_duration_seconds` | counter, histogram | toda API |
| `marketplace_handler_duration_seconds{consumer_group,event_type,result}` | histogram | `KafkaEventConsumer` |
| `marketplace_dlq_messages_total{source_topic,consumer_group}` | counter | `KafkaEventConsumer` |
| `marketplace_outbox_published_total{topic,event_type}` | counter | `OutboxRelay` |
| `marketplace_outbox_pending` | gauge | `OutboxRelay` |
| `marketplace_outbox_relay_errors_total` | counter | `OutboxRelay` |
| `marketplace_orders_created_total` | counter | ordering (API) |
| `marketplace_payments_confirmed_total` | counter | payments (API) |

### Por que propagar o contexto pelo Kafka

Numa chamada HTTP o contexto segue sozinho, no header, e a instrumentação do httpx e do FastAPI cuida disso.
No Kafka a conversa é assíncrona: quem publica não espera, quem consome roda em outro processo, às vezes
minutos depois. Sem propagação, cada consumidor abriria um trace novo e o pedido apareceria como cinco
histórias desconexas, sem como saber qual evento de payments nasceu de qual pedido.

A solução tem duas metades:

1. O publicador injeta `traceparent` nos headers da mensagem.
2. O consumidor extrai o `traceparent` e cria o span do handler como filho dele (`SpanKind.CONSUMER`).

Há uma armadilha específica de quem usa **outbox**: quem publica no Kafka não é a requisição, é o relay,
em outro processo e outro momento. Se o relay injetasse o contexto dele, o trace nasceria no relay e a
requisição original ficaria de fora. Por isso o contexto é **gravado na linha do outbox** (coluna
`outbox_events.traceparent`) no mesmo momento em que o evento é escrito, dentro do span da requisição ou do
handler. O relay lê o valor, abre um span `<tópico> publish` como filho dele e é esse span que o publicador
injeta nos headers.

```
POST /orders ──► outbox.add (grava traceparent) ──► [outbox_events]
                                                         │ relay lê o traceparent
                                                         ▼
                              span "orders.events publish" (filho do POST /orders)
                                                         │ headers Kafka: traceparent
                                                         ▼
          span "orders.events process" (payments) ──► outbox.add ──► ... e assim por diante
```

O resultado é um trace único com o pedido inteiro. Os testes da biblioteca provam isso de ponta a ponta com
Kafka real: publica dentro de um span, consome, e confere que o `trace_id` é o mesmo e que a árvore de pais
está correta.

## 2. DLQ (dead letter queue)

Quando o handler de uma mensagem falha, o consumidor tenta de novo (até `max_attempts`, com
`error_backoff` entre as tentativas). Passado o limite, a mensagem vai para o tópico `<origem>.dlq` com três
headers de diagnóstico e o consumo segue. Sem isso, uma "mensagem envenenada" travaria a partição inteira e
nada depois dela seria processado.

| Header | Conteúdo |
|---|---|
| `dlq_reason` | `repr` da exceção (até 500 caracteres) |
| `dlq_source` | `tópico/partição/offset` de origem |
| `dlq_group` | grupo consumidor que desistiu |

A DLQ é uma fila de **trabalho pendente**, não um lixão. Cada mensagem ali é um evento que o negócio
precisava processar e não conseguiu. A pergunta é sempre "por que falhou?":

- **Falha transitória ou bug já corrigido** (banco fora do ar, deploy ruim, dependência instável): reprocessar
  resolve. É o caso comum.
- **Mensagem inválida de verdade** (payload corrompido, regra de negócio que nunca vai aceitar): reprocessar
  só devolve o problema. Corrija o dado na origem ou descarte com decisão consciente.
- **Reprocessar só depois de corrigir a causa.** Reenviar com o bug ainda ativo recria a DLQ.

Reprocessar é seguro porque os consumidores deduplicam por `event_id` (inbox): reentregar um evento que já
foi tratado não tem efeito colateral.

### Ferramenta

```bash
# resumo: origem, tipo de evento, motivo e contagem
uv run python -m marketplace_common.dlq list --topic orders.events.dlq

# simulação (padrão): mostra o que seria reenviado e não envia nada
uv run python -m marketplace_common.dlq replay --topic orders.events.dlq --event-type OrderCreated --limit 10

# executa de verdade
uv run python -m marketplace_common.dlq replay --topic orders.events.dlq --event-type OrderCreated --limit 10 --yes
```

O endereço do Kafka vem de `--bootstrap` ou de `KAFKA_BOOTSTRAP_SERVERS` (padrão `localhost:9094`).

Regras de segurança do `replay`:

- `--dry-run` é o comportamento padrão. Só `--yes` publica.
- O tópico de destino é lido do header `dlq_source` de cada mensagem, e a chave original é mantida (a
  mensagem volta à mesma partição, preservando a ordem por pedido).
- Os headers `dlq_reason`, `dlq_source` e `dlq_group` são removidos e entram `dlq_replayed` (quando) e
  `dlq_replayed_from` (de qual posição da DLQ).
- **Anti-laço:** depois de reenviar, a ferramenta grava um marcador na própria DLQ. Uma mensagem já
  reprocessada, ou que voltou à DLQ com o header `dlq_replayed`, é recusada, a menos que se passe `--force`.
  Assim um bug persistente não vira um ciclo infinito de reenvio.

### Retenção (TTL) de outbox, inbox e idempotência

Sem limpeza, `outbox_events`, `inbox_messages` e `idempotency_keys` crescem para sempre. O `CleanupJob`
apaga o que passou da retenção, em lotes:

```sql
WITH doomed AS (
  SELECT ctid FROM outbox_events
  WHERE published_at < now() - make_interval(secs => :retention)
  ORDER BY published_at LIMIT :batch
  FOR UPDATE SKIP LOCKED)
DELETE FROM outbox_events WHERE ctid = ANY (ARRAY(SELECT ctid FROM doomed))
```

Cada lote é uma transação curta (padrão 1000 linhas) e o `SKIP LOCKED` pula o que outra transação segura,
então nada espera e várias réplicas do job rodam juntas. Um ciclo tem no máximo `CLEANUP_MAX_BATCHES` lotes,
com pausa entre eles, e o próximo ciclo continua de onde parou. O outbox **não publicado** nunca é apagado
(a coluna `published_at` nula não entra na comparação). Índices parciais por `published_at`, `processed_at`
e `created_at` mantêm a busca barata.

| Variável | Padrão | Efeito |
|---|---|---|
| `RETENTION_OUTBOX_PUBLISHED_HOURS` | 168 (7 dias) | quanto manter o outbox já publicado |
| `RETENTION_INBOX_HOURS` | 336 (14 dias) | quanto manter o registro de dedup do inbox |
| `RETENTION_IDEMPOTENCY_HOURS` | 48 | validade da `Idempotency-Key` |
| `CLEANUP_INTERVAL_SECONDS` | 300 | intervalo entre ciclos |
| `CLEANUP_BATCH_SIZE` | 1000 | linhas por lote |
| `CLEANUP_MAX_BATCHES` | 50 | lotes por ciclo e por tabela |
| `CLEANUP_PAUSE_SECONDS` | 0.05 | pausa entre lotes |

Duas regras de segurança da política: o inbox precisa durar **mais** que a retenção do tópico no Kafka (apagar o
registro de dedup enquanto a mensagem ainda pode voltar reabre a porta para processar duas vezes), e a chave de
idempotência precisa durar mais que o maior tempo de retentativa de um cliente (depois de expirar, a mesma chave
cria um pedido novo, e isso tem teste).

Métricas: `marketplace_cleanup_deleted_total{table}`, `marketplace_cleanup_batches_total{table}`,
`marketplace_cleanup_runs_total{result}`, `marketplace_cleanup_run_duration_seconds` e
`marketplace_cleanup_last_success_timestamp_seconds` (alerte se ficar velho). O job roda dentro do
`worker_main` de ordering, payments, inventory, ledger e notifications, e na API do identity (refresh tokens
expirados).

## 3. Biblioteca compartilhada em microsserviços: acoplamento versus duplicação

Compartilhar código entre serviços independentes é uma troca, e ela precisa ser consciente.

| | Copiar em cada serviço | Biblioteca compartilhada |
|---|---|---|
| Autonomia de deploy | Total | Uma mudança na lib exige atualizar cada serviço que a usa |
| Correção de bug | Corrigir N vezes (e esquecer uma) | Corrigir uma vez |
| Consistência | As cópias divergem com o tempo | Comportamento único |
| Acoplamento | Nenhum entre serviços | Versão da lib vira contrato implícito |
| Risco | Falhas diferentes em cada cópia | Uma falha na lib derruba todos de uma vez |

A regra prática usada aqui: compartilhar **infraestrutura transversal e estável** (como falar com o Kafka,
como emitir logs e métricas, como reprocessar a DLQ) e **nunca regra de negócio nem modelo de domínio**.
Cada serviço mantém seus casos de uso, suas entidades e seus próprios testes. A lib não conhece `Order`
nem `Payment`.

Cuidados para a lib não virar um monólito distribuído:

- API pequena e estável, com extras opcionais para não impor dependências.
- Mudanças compatíveis por padrão (o campo `traceparent` do `OutboxMessage` é opcional, com valor padrão).
- Testes na própria lib, rodando uma única vez, em vez de repetidos em cinco serviços.
- Em produção real, publicar a lib com versionamento semântico em um registro de pacotes e fixar a versão em
  cada serviço, para atualizar um por vez. Aqui ela é referenciada por caminho porque o repositório é um
  monorepo de estudo.

## 4. Subindo a stack de observabilidade

```bash
cd infra
docker compose -f docker-compose.yml -f docker-compose.observability.yml --profile services up -d --build
```

| Ferramenta | Endereço |
|---|---|
| Grafana (dashboard "Marketplace") | http://localhost:3000 (admin / admin, leitura anônima liberada) |
| Jaeger (traces) | http://localhost:16686 |
| Prometheus | http://localhost:9090 |

O arquivo `docker-compose.observability.yml` também injeta `OTEL_EXPORTER_OTLP_ENDPOINT` nos serviços. Sem
ele os serviços funcionam normalmente, só sem traces.

## 5. Perguntas de entrevista

**1. Qual a diferença entre monitoramento e observabilidade?**
Monitoramento verifica condições conhecidas ("a CPU passou de 90%?") e responde se algo está quebrado.
Observabilidade é poder investigar condições que ninguém previu, a partir de dados ricos (logs, métricas e
traces correlacionados) emitidos pelo próprio sistema. Em microsserviços ela importa mais porque uma falha
raramente está no serviço que a mostra.

**2. Para que serve cada pilar e por que os três juntos?**
Métricas dizem que há um problema e quanto ele pesa, de forma barata e agregada. Traces mostram onde, no
caminho entre serviços, o tempo foi gasto ou o erro nasceu. Logs dão o detalhe de cada execução. O elo entre
eles é o `trace_id` nos logs e a mesma dimensão nos rótulos: do alerta ao trace e do trace às linhas de log.

**3. O que é o método RED e quando não serve?**
Rate, Errors e Duration por serviço: o mínimo para saber se quem atende requisições está bem, do ponto de
vista de quem chama. Não serve para recursos (use USE: utilização, saturação e erros) nem para processos em
lote ou consumidores, onde pesam vazão do handler, atraso de fila e mensagens na DLQ.

**4. Por que usar percentis de latência em vez da média?**
A média esconde a cauda. Se 1% das requisições leva 5 s, a média quase não muda, mas esses usuários sentem.
O p95 e o p99 mostram a experiência dos casos ruins. Por isso a duração é um histograma, que permite calcular
percentis no Prometheus com `histogram_quantile`.

**5. Como um trace atravessa o Kafka se não há request HTTP?**
O contexto vai em headers da mensagem (`traceparent`, padrão W3C). O publicador injeta e o consumidor extrai
e cria o span do handler como filho. Com outbox há um passo a mais: o contexto é gravado na linha do outbox
no momento da escrita, porque quem publica é o relay, em outro processo. Sem isso o trace quebraria no relay.

**6. O que é uma DLQ e quando reprocessar?**
É o destino das mensagens que esgotaram as tentativas, para não travar a partição. Reprocessa-se depois de
corrigir a causa (bug, dependência fora do ar), de forma controlada: filtrando por tipo, com limite, primeiro
em simulação, e com proteção contra reenvio em laço. Mensagem realmente inválida não se reprocessa, se
corrige ou se descarta. A idempotência do consumidor (inbox por `event_id`) é o que torna isso seguro.

**7. Por que o consumidor só confirma o offset depois de tratar a mensagem?**
Entrega "ao menos uma vez": se o processo cair entre tratar e confirmar, a mensagem é reentregue. O handler
é idempotente (inbox) e por isso reprocessar é inofensivo. Confirmar antes inverteria o risco para "no
máximo uma vez", com perda silenciosa de eventos.

**8. Biblioteca compartilhada ou código duplicado entre microsserviços?**
Depende do que se compartilha. Infraestrutura transversal e estável (mensageria, observabilidade) compensa
a lib: um bug corrigido uma vez e comportamento uniforme. Regra de negócio e modelos de domínio não, porque
acoplam as equipes e os deploys. Para a lib não virar monólito distribuído: API pequena, mudanças
compatíveis, versionamento semântico, testes próprios e atualização gradual, serviço a serviço.
