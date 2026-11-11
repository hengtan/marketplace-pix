[English](../RESILIENCE.md) | **Português (Brasil)**

# Resiliência

Este documento explica os padrões de resiliência do marketplace: o que cada um resolve, onde está aplicado,
como configurar, os trade-offs e como defender cada decisão em entrevista. Todos vivem na biblioteca
compartilhada `backend/libs/marketplace_common/src/marketplace_common/resilience/` e são usados pelo gateway,
pelo `payments` (cliente do PSP), pelo `assistant` (LLM e embedder) e pelo `ordering` (chamada ao catálogo).

## 1. Visão geral

Falhas em sistemas distribuídos são normais. O objetivo não é evitá-las, e sim garantir que uma dependência
lenta ou morta não derrube quem depende dela. A ordem em que os padrões se compõem importa:

```
Retry  >  Circuit breaker  >  Bulkhead  >  Timeout (limitado pelo deadline)  >  chamada
```

- O **retry** fica por fora: cada tentativa passa pelo breaker, então tentativas contra um circuito aberto
  são rejeitadas na hora e **nunca** retentadas.
- O **breaker** fica por fora do bulkhead: uma rejeição do bulkhead (sistema saturado) não conta como falha
  da dependência.
- O **timeout** fica por dentro e é o menor entre o timeout configurado e o que sobrou do deadline.

Onde cada padrão está aplicado:

| Chamada | Breaker | Retry | Bulkhead | Deadline | Rate limit |
|---|---|---|---|---|---|
| Gateway para cada serviço (7 breakers) | sim, por serviço | só GET e HEAD | sim, por serviço | define, repassa e limita o timeout | sim, por cliente e por rota |
| `payments` para o PSP (cobrança, status, cancelamento) | sim | sim (as 3 operações são idempotentes) | sim | limita o timeout | não |
| `payments`, webhook: consulta de status no PSP | o mesmo `ResilientPsp` | sim | sim | limita o timeout | não |
| `assistant` para o LLM e o embedder | sim, um por modelo | sim (leitura) e não no stream | sim | limita o timeout | via gateway |
| `ordering` para o catálogo | já tinha retry próprio | já tinha | não | repassa o header e limita o timeout | via gateway |
| Gateway para o Redis (limiter) | sim | não | não | não | n/a |

## 2. Circuit breaker

**Problema.** Um serviço lento ou fora do ar segura conexões, threads e memória de quem o chama, e a falha
sobe em cascata. Insistir só piora a recuperação do serviço doente.

**Como funciona aqui** (`circuit_breaker.py`):

- Três estados: `closed` (passa tudo), `open` (rejeita sem chamar a dependência) e `half_open` (deixa passar
  poucas sondas).
- Janela deslizante por contagem (`window_size`) **e** por idade (`window_seconds`). Só avalia depois de
  `minimum_calls` chamadas, para não abrir com 1 falha em 1 chamada.
- Abre por **taxa de falha** (`failure_rate_threshold`, padrão 50%) ou por **taxa de chamadas lentas**
  (`slow_call_threshold` e `slow_call_rate_threshold`). Uma dependência que responde 200 em 8 segundos também
  derruba o sistema, por isso lento conta.
- Em `half_open` admite no máximo `half_open_max_calls` sondas (concorrentes e no total). Uma falha reabre e
  reinicia a espera. Todas as sondas com sucesso fecham.
- `is_failure` decide o que conta como falha: 404 e erros de validação não contam (a dependência está
  saudável), 5xx e erros de transporte contam. `failure_on_result` marca respostas ruins sem exceção.
- Cancelamento e geradores abandonados são neutros: não contam como sucesso nem como falha e liberam a vaga da sonda.
- Uso como decorador (`@breaker.protect`), context manager (`async with breaker.guard()`) ou
  `await breaker.call(operacao)`.

**Métricas Prometheus:** `resilience_circuit_breaker_state{name,state}`,
`resilience_circuit_breaker_transitions_total{name,from_state,to_state}`,
`resilience_circuit_breaker_calls_total{name,outcome}`, `resilience_circuit_breaker_rejected_total{name}`.

**Quando usar.** Em toda chamada de rede a uma dependência que pode degradar.
**Quando não usar.** Em chamadas locais ou dentro de uma transação de banco, onde "abrir" não ajuda ninguém.

**Trade-offs.** Janela curta reage rápido mas oscila (flapping). Janela longa é estável mas demora a
proteger. `minimum_calls` baixo abre com ruído. O estado é por processo: cada réplica do gateway aprende
sozinha (barato e sem ponto central, mas as réplicas divergem por alguns segundos).

**Estado por processo e o modo compartilhado (opcional).** Por padrão cada instância do gateway tem o seu
breaker: uma réplica que ainda não viu falhas continua mandando tráfego a um serviço que outra já
considerou doente, e cada réplica gasta as próprias chamadas para descobrir. Com `BREAKER_SHARED_STATE=true`
(precisa de `REDIS_URL`, padrão desligado) o gateway usa `SharedCircuitBreaker`
(`resilience/shared_breaker.py`): quem abre grava no Redis uma chave `gw:cb:<serviço>` que vive `open_seconds`;
as demais leem a chave (no máximo a cada `BREAKER_SYNC_INTERVAL`, 0,25 s) e abrem também, com o tempo
restante; quem fecha apaga a chave. O que continua local: a janela de falhas e a contagem de sondas do
half-open (cada réplica sonda por conta própria). Se o Redis falha, o breaker volta a ser o local e a chamada
não é afetada. Testes: `tests/unit/test_shared_breaker.py` (duas réplicas convergem, a janela restante bate,
recuperação, falha do Redis), `tests/integration/test_redis_shared_breaker.py` (Redis real) e
`gateway/tests/test_shared_breaker.py` (duas instâncias do gateway: a que não viu falha responde `503
circuit_open` sem chamar o serviço).

**Equivalente em .NET.** Polly `AdvancedCircuitBreaker` (v7) ou `AddCircuitBreaker` no
`Microsoft.Extensions.Resilience` (Polly v8): `FailureRatio` = `failure_rate_threshold`,
`SamplingDuration` = `window_seconds`, `MinimumThroughput` = `minimum_calls`, `BreakDuration` =
`open_seconds`. A chamada lenta equivale ao `SlowCallDurationThreshold` do Resilience4j.

**Em entrevista.** "Uso breaker com janela deslizante, taxa de falha e de lentidão, e sondas limitadas no
half-open. Cada dependência tem o seu, para a queda do catálogo não afetar o estoque. Quando abre, o
gateway responde 503 estruturado com Retry-After em 10 ms, em vez de segurar a conexão 10 segundos."

## 3. Retry com backoff exponencial, full jitter e orçamento

**Problema.** Falhas transitórias (conexão resetada, 503 de um deploy) somem se a chamada for repetida.
Mas retry mal feito é a principal causa de tempestades: se 3 camadas fazem 3 tentativas, 1 requisição vira
27 contra o serviço que já está caindo.

**Como funciona aqui** (`retry.py`):

- Atraso = `uniform(0, min(max_delay, base * 2^(tentativa-1)))`: backoff exponencial com **full jitter**.
  O jitter espalha os clientes no tempo; sem ele todos retentam no mesmo instante e geram picos sincronizados.
- Só retenta se `idempotent=True` **e** o erro for transitório (`retry_on`) **ou** o resultado for ruim
  (`retry_on_result`, ex.: 502, 503, 504). No gateway só `GET` e `HEAD` são retentados. `POST /orders` nunca
  é repetido pelo gateway: quem repete é o cliente, com a mesma `Idempotency-Key`.
- Nunca retenta `CircuitOpenError`, `BulkheadFullError` e `DeadlineExceeded`.
- Não dorme além do deadline: se o atraso não cabe no tempo que sobrou, desiste na hora.
- **Retry budget** (`RetryBudget`): em uma janela de 10 s as retentativas permitidas são
  `min_retries + ratio * requisições` (padrão 3 + 20%). Com o serviço fora, o orçamento esgota e o sistema
  para de amplificar a carga. A métrica `resilience_retry_events_total{event="budget_denied"}` mostra isso.

**Quando usar.** Leituras e operações idempotentes.
**Quando não usar.** Em escrita sem chave de idempotência (cobrar duas vezes é pior que falhar uma) e em
erros determinísticos (400, 404, 422), que falham igual toda vez.

**Trade-offs.** Mais tentativas aumentam a chance de sucesso e a latência de cauda. O budget troca um pouco
de disponibilidade por proteção contra o efeito manada. Retry em várias camadas multiplica: por isso o
gateway é o único lugar que retenta chamadas HTTP de leitura.

**Equivalente em .NET.** Polly v8 `RetryStrategyOptions` com `BackoffType = Exponential`, `UseJitter = true`,
`MaxRetryAttempts`, `ShouldHandle` (= `retry_on` e `retry_on_result`). O budget não existe no Polly: é um
conceito do Finagle e do Envoy (`retry_budget`), e aqui está implementado à mão.

**Em entrevista.** "Backoff exponencial com full jitter, só em operação idempotente, respeitando o deadline
e com um orçamento de retentativas como fração do tráfego. Sem budget, retry vira ataque ao próprio
serviço."

## 4. Deadline propagation (timeouts em cascata)

**Problema.** Se o gateway espera 10 s e o serviço de baixo espera mais 10 s pelo próximo, o cliente já
desistiu e o trabalho continua inútil. Timeouts independentes em cada salto somam em vez de se limitar.

**Como funciona aqui** (`deadline.py`):

- O gateway cria um orçamento de tempo por requisição: `X-Request-Deadline` do cliente (limitado a
  `max_request_deadline_seconds`, 30 s) ou o padrão `request_deadline_seconds` (8 s; 25 s para o
  `assistant`, que pode demorar mais).
- O header carrega o **tempo restante em milissegundos**, não um horário absoluto (estilo `grpc-timeout`).
  Assim não depende de relógios sincronizados: cada salto converte para o seu relógio monotônico.
- Cada chamada de saída recalcula o restante, grava no header e **limita o timeout do httpx** ao que sobrou
  (`deadline_event_hooks`). Uma cadeia gateway, ordering e catálogo nunca passa do orçamento original.
- Toda API que usa `install_api_observability` instala o `DeadlineMiddleware`: lê o header, responde `504`
  se já chegou expirado (não gasta trabalho) e deixa o orçamento disponível via `current_deadline()`.
- O retry consulta o deadline antes de dormir; o `ResilientPsp` e o `ModelGuard` limitam o `asyncio.timeout`.

**Trade-offs.** O deadline é cooperativo: o middleware não cancela handlers no meio de uma transação (cancelar
no meio de um commit é pior que terminar). Por isso as chamadas de saída é que respeitam o orçamento.

**Equivalente em .NET.** `CancellationToken` propagado de ponta a ponta, mais `HttpClient.Timeout` e a
`TimeoutStrategy` do Polly. Em gRPC é o *deadline* nativo.

**Em entrevista.** "Timeout por salto não basta. Propago o tempo restante como header relativo e cada
camada limita suas chamadas a ele. Quando o orçamento acaba, falha rápido com 504 em vez de trabalhar para
um cliente que já foi embora."

## 5. Bulkhead

**Problema.** Uma dependência lenta consome todas as conexões e threads compartilhadas, e as outras rotas
(saudáveis) também ficam sem recurso. É o princípio dos compartimentos de um navio.

**Como funciona aqui** (`bulkhead.py`): um semáforo por dependência com `max_concurrent` execuções
simultâneas e uma fila curta de `max_queue` esperas por até `queue_timeout`. Passou disso, rejeita na hora
(`BulkheadFullError`, 503 com `Retry-After` no gateway). Métricas: `resilience_bulkhead_in_flight`,
`resilience_bulkhead_queued`, `resilience_bulkhead_rejected_total{reason}` e o histograma de espera.

**Trade-offs.** Limite baixo protege mas recusa tráfego legítimo em pico. Fila longa esconde a saturação e
aumenta a latência (e depois o cliente já desistiu). Preferir fila curta e falhar rápido.

**Equivalente em .NET.** `BulkheadPolicy` do Polly v7. No v8 virou o `ConcurrencyLimiter`
(`AddConcurrencyLimiter`), com `PermitLimit` e `QueueLimit`.

**Em entrevista.** "Cada dependência tem o seu limite de concorrência e uma fila pequena. A queda do
assistente não consome as conexões do catálogo."

## 6. Rate limiter distribuído no Redis

**Problema.** Proteger o sistema de um cliente abusivo ou de um laço descontrolado. Um limiter em memória
só conhece o tráfego da própria réplica: com 5 réplicas o limite real é 5 vezes maior.

**Como funciona aqui** (`rate_limit.py`):

- **Token bucket** em um script Lua, executado de forma atômica no Redis (um `EVALSHA`, sem condição de
  corrida entre réplicas). A chave é `gw:rl:<rota>:<cliente>`; o estado é um hash com `tokens` e `ts`, com
  `PEXPIRE` para o balde ocioso sumir sozinho. O relógio é o do Redis (`TIME`), então réplicas com relógios
  diferentes concordam. Nos testes o tempo é injetado.
- Limite por cliente (IP) **e** por rota (nome do serviço). Padrão: 600 por minuto, com `ordering` em 120 e
  `assistant` em 60, configurável por `RATE_LIMIT_PER_MINUTE` e `RATE_LIMIT_ROUTES` (JSON). Um token bucket
  permite rajada até a capacidade e reabastece de forma contínua, o que é mais amigável que uma janela fixa
  (que deixa passar o dobro na virada da janela).
- Respostas trazem `RateLimit-Limit`, `RateLimit-Remaining` e `RateLimit-Reset` (segundos até encher), e o
  `429` traz `Retry-After`.
- **Se o Redis cair** (`RATE_LIMIT_FAILURE_MODE`): `fallback` (padrão) usa o token bucket em memória por
  instância, `fail_open` deixa passar tudo e `fail_closed` bloqueia. Todas contam em
  `resilience_rate_limit_backend_total{backend}`. Um circuit breaker próprio evita pagar o timeout do Redis
  em toda requisição enquanto ele estiver fora.

**Trade-offs.**

- Fail-open privilegia disponibilidade (e fica sem proteção contra abuso). Fail-closed privilegia proteção
  (e uma queda do Redis derruba o produto). O fallback em memória é o meio-termo: o limite deixa de ser
  global, mas continua existindo.
- O Redis entra no caminho crítico de toda requisição: custa 1 ida e volta (cerca de 1 ms na mesma rede) e
  por isso tem timeout curto e breaker.
- Identidade do cliente: o IP da conexão ou, só quando a conexão vem de um proxy listado em
  `TRUSTED_PROXIES` (CIDR, separados por vírgula), o primeiro endereço não confiável de `X-Forwarded-For`, lido
  da direita para a esquerda (`X-Real-IP` na falta dele). Sem a lista, o cabeçalho é ignorado: um cliente não
  consegue forjar o IP para fugir do limite (teste: `test_a_client_cannot_dodge_the_limit_by_forging_forwarded_for`).
  O gateway repassa aos serviços o endereço resolvido em `X-Forwarded-For`. No compose o padrão é a faixa privada
  inteira (a rede do Docker); em produção liste só os endereços do balanceador.

**Equivalente em .NET.** `Microsoft.AspNetCore.RateLimiting` com `TokenBucketRateLimiter` (por política e
por partição). A versão distribuída exige um pacote como `RedisRateLimiting` ou um script Lua como o daqui.
No Polly v8 existe `AddRateLimiter`, mas é do lado do cliente.

**Em entrevista.** "Token bucket em Lua, atômico, com o relógio do Redis. Por cliente e por rota. Se o Redis
cai, o comportamento é uma decisão de produto, configurável: caio para memória local, deixo passar ou
bloqueio. Em qualquer caso há métrica e alerta."

## 7. Degradação graciosa

O contrato de erros do gateway (`{ "detail": "texto" }`) continua valendo, com campos extras opcionais:

| Situação | Status | Corpo e cabeçalhos |
|---|---|---|
| Circuito de um serviço aberto | 503 | `{"detail": "catalog is temporarily unavailable", "code": "circuit_open", "service": "catalog", "retry_after_seconds": N}` e `Retry-After: N` |
| Bulkhead cheio | 503 | mesmo formato, `code: "overloaded"` |
| Limite de requisições | 429 | `Retry-After` e `RateLimit-*` |
| Deadline estourado | 504 | `{"detail": "request deadline exceeded"}` |
| Timeout do upstream | 504 | `{"detail": "upstream timeout"}` |
| Upstream fora (sem breaker aberto ainda) | 502 | `{"detail": "upstream unavailable"}` |
| PSP indisponível no webhook | 503 | `{"code": "psp_unavailable"}` e `Retry-After` (o PSP reenvia o webhook) |
| LLM ou embedder protegido e aberto | 503 | `{"code": "model_unavailable"}` e `Retry-After` |

`GET /api/health` agrega o `/health` de cada serviço e agora inclui `breakers` (estado, taxa de falha e
tempo até a próxima sonda de cada serviço). Fica `degraded` se qualquer serviço estiver fora **ou** qualquer
breaker não estiver fechado.

O mais importante: **o isolamento é por serviço**. Com o catálogo fora, o estoque, o ledger e a leitura de
pedidos seguem respondendo. E o fluxo de dinheiro não depende de chamada síncrona: o pedido é gravado com o
evento no outbox na mesma transação, então se o `payments` estiver fora a saga simplesmente espera no Kafka
e continua quando ele volta.

## 8. Observabilidade e SLO

- Painel Grafana **Resiliência** (`infra/observability/grafana/dashboards/resilience.json`): estado dos
  breakers, transições, rejeições, retries, bulkhead, decisões do rate limit, quem respondeu o limite
  (Redis ou fallback), 429, 503 e 504 no gateway, deadlines estourados e a seção de SLO.
- Regras do Prometheus em `infra/observability/rules/resilience-slo.yml` (validadas com `promtool check rules`
  e testadas com `promtool test rules` em `infra/observability/tests/`).
- **SLOs do gateway:** disponibilidade de 99,5% (respostas que não são 5xx) e latência com 95% das
  respostas abaixo de 500 ms.
- **Alertas por burn rate**, em duas janelas, como no livro de SRE do Google. O *burn rate* é a velocidade
  de consumo do orçamento de erro: 1 gasta o orçamento exatamente no fim do mês.

| Alerta | Janelas | Burn rate | Severidade |
|---|---|---|---|
| `...BurnRateFast` | 1h e 5m | 14,4 (acaba em cerca de 2 dias) | página |
| `...BurnRateSlow` | 6h e 30m | 6 | página |
| `...BurnRateTicket` | 1d e 2h | 3 | ticket |

A janela curta junto da longa evita alertar por um pico que já passou e faz o alerta limpar rápido.
Também há alertas para breaker aberto, breaker oscilando, rate limiter sem Redis (e em fail-closed), excesso
de 429, bulkhead rejeitando, orçamento de retry esgotado e picos de deadline.

## 9. Como foi testado

- **Unitários** (relógio injetável, sem `sleep` real): breaker, retry, deadline, bulkhead e rate limiter na lib,
  mais gateway, `payments`, `assistant` e `ordering`.
- **Integração com Redis real:** o script Lua (rajada, reabastecimento, TTL, atomicidade com 200 chamadas
  concorrentes, dois limiters compartilhando o mesmo balde, relógio do servidor) e duas instâncias do
  gateway dividindo o mesmo limite.
- **Caos** (`scripts/chaos.sh`): derruba catalog, payments e Redis um de cada vez, com a stack real. Valida
  que o breaker abre, que a resposta é rápida (503 em poucos milissegundos), que o sistema volta sozinho e
  que pedidos criados antes e durante a queda do payments chegam a `PAID`. Resultado na seção 10.
- **Carga** (`scripts/loadtest.py`): ver `docs/pt-BR/loadtest-result.md`.
- **Alertas:** `promtool test rules` simula séries de erro e confirma que os alertas disparam (e não disparam
  com tráfego saudável).

## 10. Resultados medidos

Ver `docs/pt-BR/loadtest-result.md` (carga) e a saída de `scripts/chaos.sh`, resumida abaixo.

Última execução de `scripts/chaos.sh` contra uma stack Docker paralela (40 verificações, 40 aprovadas):

| Cenário | Resultado medido |
|---|---|
| Catálogo derrubado | breaker abriu após 25 chamadas; com o circuito aberto o gateway respondeu `503` com `Retry-After` em poucos milissegundos; inventory seguiu respondendo; `POST /orders` degradou com 503 |
| Catálogo volta | respondeu 200 de novo sozinho, sem reiniciar o gateway, e o breaker fechou após as sondas do half-open |
| Payments derrubado | pedido criado antes e outro durante a queda; consulta de pagamento com circuito aberto respondeu 503 rápido; ordering seguiu lendo pedidos |
| Payments volta | as cobranças dos dois pedidos foram criadas cerca de 8 s depois (a saga retomou pelo Kafka) e ambos chegaram a `PAID` |
| Redis derrubado | 30 de 30 requisições responderam 200, com p50 de 12 ms, p90 de 18 ms e máximo de 28 ms; a métrica `memory_fallback` subiu e os headers `RateLimit-*` continuaram saindo |
| Redis volta | o gateway voltou a usar o Redis sozinho |

Na primeira versão do script o máximo sem Redis chegou a 2 a 3 segundos: a limpeza da conexão cancelada no
redis-py segurava a resposta. O limiter agora espera a operação em uma tarefa separada e responde no
timeout sem esperar essa limpeza (teste `test_slow_cancellation_cleanup_does_not_delay_the_answer`). O
máximo medido caiu para menos de 600 ms nas repetições manuais e o p90 ficou abaixo de 250 ms.

## 11. Aprendizados e armadilhas encontradas

- **Gerador abandonado não é falha.** No stream do LLM, o cliente que fecha a conexão encerra o gerador com
  `GeneratorExit`. Se o breaker tratasse isso como erro, abrir uma aba e fechar derrubaria o circuito.
  Agora cancelamento e `GeneratorExit` são neutros.
- **Timeout do Redis mede também a latência do event loop.** Com o gateway a 100% de CPU, um timeout de
  100 ms para o Redis estourava por atraso do próprio loop, e o breaker do Redis oscilou 5 vezes em uma
  carga. O padrão subiu para 250 ms e o breaker passou a exigir mais amostras (10 chamadas, janela de 30).
  O fallback em memória segurou o tráfego o tempo todo, e foi o que o painel mostrou.
- **Dependência nova em lib compartilhada quebra quem não a usa.** O `httpx` usado pelo deadline não estava
  nas dependências da lib e derrubou, só dentro do Docker, os serviços que não o declaravam. Corrigido
  declarando a dependência. Lição: testar a imagem, não só o ambiente de desenvolvimento.
- **Half-open precisa de tráfego para fechar.** Depois que a dependência volta, o breaker só fecha após as
  sondas com sucesso. O script de caos envia requisições até o breaker fechar em vez de assumir que fecha
  sozinho no mesmo instante.
- **Teste de carga consome estoque.** Cada pedido reserva unidades; o `loadtest.py` repõe o estoque antes
  de começar, senão os pedidos passam a ser cancelados por falta de estoque e mascaram o resultado.

## 12. Perguntas de entrevista e respostas curtas

**Qual a diferença entre timeout, retry e circuit breaker?**
Timeout limita quanto esperar uma chamada. Retry tenta de novo quando a falha parece passageira. Breaker
para de chamar quem está doente. Combinados, o retry fica por fora do breaker e o timeout por dentro.

**Por que jitter?** Sem ele, todos os clientes retentam no mesmo instante e criam picos sincronizados.
Com full jitter o atraso é sorteado entre 0 e o teto exponencial, o que espalha a carga.

**Como evita tempestade de retries?** Idempotência obrigatória, budget como fração do tráfego, retry só
em uma camada e nunca contra circuito aberto.

**Retry de POST é seguro?** Só com chave de idempotência. Aqui o gateway não retenta POST: o cliente
reenvia com a mesma `Idempotency-Key` e o `ordering` devolve o mesmo resultado.

**O que acontece se o Redis do rate limit cair?** Depende da política: fallback para memória (padrão), deixar
passar ou bloquear. O breaker do Redis impede esperar timeout em toda chamada, e há métrica e alerta.

**Por que token bucket e não janela fixa?** Aceita rajada controlada, reabastece de forma contínua e não
tem o problema do dobro de tráfego na virada da janela.

**Como garante que um pedido não se perde se o payments cair?** O pedido e o evento do outbox são gravados
na mesma transação. O evento espera no Kafka, e quando o payments volta o consumidor (com inbox, que
deduplica) cria a cobrança. O teste de caos prova isso.

**Breaker por processo ou compartilhado?** Por processo: simples, sem ponto central, sem custo de rede.
O preço é que as réplicas aprendem de forma independente. Compartilhar o estado no Redis só vale se a
decisão precisar ser idêntica em todas as réplicas.

**Como escolhe os limiares?** Começo conservador (50% de falha, mínimo de 10 chamadas), olho o painel em
carga real e ajusto. Medir antes de configurar: o caso do timeout do Redis mostra por quê.

**Equivalências com o Polly:** ver a tabela abaixo.

| Aqui | Polly v8 / ASP.NET Core |
|---|---|
| `CircuitBreaker` | `AddCircuitBreaker` (`FailureRatio`, `SamplingDuration`, `MinimumThroughput`, `BreakDuration`) |
| `retry_async` + `RetryPolicy` | `AddRetry` (`BackoffType.Exponential`, `UseJitter`, `MaxRetryAttempts`, `ShouldHandle`) |
| `RetryBudget` | sem equivalente nativo (Finagle e Envoy `retry_budget`) |
| `Deadline` | `CancellationToken` propagado, `AddTimeout`, deadline do gRPC |
| `Bulkhead` | `AddConcurrencyLimiter` (era `BulkheadPolicy` no v7) |
| `RouteRateLimiter` | `Microsoft.AspNetCore.RateLimiting` (`TokenBucketRateLimiter`), versão distribuída com Redis |
| 503 estruturado, fallback em memória | `AddFallback` |
| composição `retry > breaker > bulkhead > timeout` | ordem dos `AddX` no `ResiliencePipelineBuilder` |

## 13. Limitações conhecidas

- O estado dos breakers é por processo, a menos que `BREAKER_SHARED_STATE=true` (seção 2): no modo
  compartilhado só a decisão de abrir é global, a janela de falhas e as sondas seguem locais.
- Com `TRUSTED_PROXIES` na faixa privada (padrão do compose), quem acessa o gateway direto pela porta publicada
  no host (que chega pelo gateway da ponte do Docker, também privado) pode forjar `X-Forwarded-For` em
  desenvolvimento. Em produção use os endereços exatos do proxy.
- O deadline é cooperativo: handlers que já estão dentro de uma transação não são cancelados.
- O breaker conta respostas 5xx como falha, inclusive 500 por bug do serviço, o que é o desejado para
  proteger o chamador, mas pode abrir o circuito por um erro de código.
- O stream SSE do assistant segura uma vaga do bulkhead só até os cabeçalhos chegarem. O corpo do stream
  não ocupa vaga.
- Retenção do Prometheus no compose é de 3 dias: o alerta de ticket de 1 dia funciona, mas não há histórico
  para uma janela de 30 dias de SLO.
