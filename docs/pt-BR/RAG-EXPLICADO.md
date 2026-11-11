[English](../RAG-EXPLAINED.md) | **Português (Brasil)**

# RAG e agentes explicados (para quem vem de .NET)

Este guia explica, de ponta a ponta, o pipeline do serviço `assistant` do marketplace: o que cada etapa faz, por que ela existe, o que custa e o que mediu de verdade. Foi escrito para quem tem boa base de back-end (C#, ASP.NET, EF Core, filas) e nunca montou um sistema de RAG.

Os números vêm de `docs/pt-BR/RAG-AVALIACAO.md` (tabela completa e como reproduzir). Tudo roda com **embeddings e LLM simulados** (sem chave de API), e isso limita o que os números provam: veja a seção "O que é simulado" no fim.

## 1. Tradução rápida de conceitos

| Conceito de RAG/LLM | O que se parece no mundo .NET |
|---|---|
| Embedding | Uma função de hash, mas que preserva **significado**: textos parecidos viram vetores próximos. |
| Banco vetorial (pgvector) | Um índice do SQL Server, só que a busca é por **proximidade** e não por igualdade. |
| HNSW | Um índice aproximado: troca um pouco de exatidão por muita velocidade, como um `TABLESAMPLE` inteligente. |
| Chunking | Paginar um documento grande em pedaços que cabem no contexto. |
| Busca híbrida + RRF | Dois `OrderBy` diferentes (vetorial e texto) fundidos em uma lista única, como um `Union` ordenado por posição. |
| Reranker | Um segundo `OrderBy`, mais caro e mais preciso, aplicado só ao top 10. |
| Tool use | Strategy/Command: o modelo escolhe qual "método" chamar, o código executa e devolve o resultado. |
| Guardrails | Validação de entrada e de saída (FluentValidation), mais um filtro de autorização no meio do pipeline. |
| Cache semântico | `IMemoryCache`, mas a chave é "perguntas com o mesmo significado" e não a string exata. |
| Prompt injection | SQL injection para linguagem natural: texto de terceiros virando instrução. |
| Spans do OpenTelemetry | `Activity`/`ActivitySource` do .NET: a mesma ideia, mesma semântica. |
| Orçamento de tokens | Rate limiting, mas cobrado em tokens e dólares em vez de requisições. |
| Eval harness | Um projeto de testes de regressão, só que a métrica é qualidade da resposta e não "passou/falhou". |

## 2. O pipeline completo

```
 Pergunta do cliente (POST /chat ou /chat/stream)
        |
        v
 [0] VALIDA  tamanho, vazio -> 422
        |
        v
 [1] GUARDA DE ENTRADA  detector de prompt injection (9 categorias + ofuscação)
        |  score >= 0,7 ? ----sim----> "Não posso seguir esse tipo de instrução" (sem agente, sem modelo)
        v
 [2] CACHE SEMÂNTICO  mesma chave de filtros + similaridade >= 0,92 ?
        |  acerto ----------------------------------------------> devolve a resposta guardada
        v  erro                                                    (sem agente e sem modelo)
 [3] ENTENDIMENTO DA CONSULTA
        |   intenção: catálogo | estoque | pedido | política | fora de escopo
        |   fora de escopo -> resposta curta, sem ferramenta
        |   filtros (preço, nota, categoria, ordenação), negação, correção de digitação,
        |   expansão de sinônimos, HyDE (opcional), decomposição de perguntas compostas
        v
 [4] AGENTE (no máximo 3 passos)  Planner -> ferramenta -> observação -> Planner ...
        |      search_products  get_stock  get_order_status  get_policy   (cada uma com timeout)
        |
        |   search_products:
        |     [4a] pré-filtro por metadados (SQL)
        |     [4b] vetorial (pgvector HNSW)  +  texto (tsvector)       em paralelo lógico
        |     [4c] fusão RRF com pesos
        |     [4d] um chunk por produto, rerank lexical (termos expandidos valem metade)
        |     [4e] corte por pontuação, MMR (opcional), parent-document (chunk achou, produto inteiro entra)
        v
 [5] PROMPT  contexto delimitado + sanitização do texto de terceiros (indireta)
        |      checagem de orçamento por sessão e por usuário
        v
 [6] GERAÇÃO  LLM (mock ou Ollama), em streaming, com timeout de primeiro token, ocioso e total
        |      falhou ou estourou o tempo? -> FALLBACK: resultados da busca sem modelo + aviso
        |      cliente fechou a aba?       -> fecha a conexão com o modelo, contabiliza o parcial
        v
 [7] GUARDA DE SAÍDA  citações válidas, produto não recuperado, números batem com o trecho
        |      citado, vazamento do system prompt, link/HTML/dado pessoal que não estava no contexto
        v
 [8] GRAVA  sessão (memória), orçamento, cache (se elegível), métricas e spans
        |
        v
 answer + citations + tool_calls + retrieved + latency_ms (+ cached, degraded, warning)
```

Cada etapa de 3 a 7 vira um **span** do OpenTelemetry e um ponto no histograma `assistant_step_duration_seconds`; tokens e custo viram contadores; o painel do Grafana (`infra/observability/grafana/dashboards/assistant.json`) mostra tudo.

## 3. Etapa por etapa: por que existe, trade-offs, números

### 3.1 Ingestão e chunking

**O que faz.** Lê o catálogo, monta um documento por produto (descrição, preço, nota, lojista, palavras-chave), quebra em chunks de até 300 caracteres com 60 de sobreposição e prefixa cada chunk com um **cabeçalho contextual** (`Produto: ... | Categoria: ...`). Gera embeddings, grava no pgvector e só reprocessa o que mudou (hash do conteúdo).

**Por que existe.** O modelo e o índice trabalham com trechos pequenos: um documento inteiro dilui o sinal. O cabeçalho evita o chunk "órfão" que não diz de que produto fala.

**Trade-offs.** Chunk pequeno acha melhor, mas entrega pouco contexto; chunk grande é o contrário. A resposta moderna é **parent-document retrieval**: indexar pedaços pequenos e, depois de achar, entregar o documento inteiro do produto. Medido: com chunks de 150 caracteres só **24%** dos trechos entregues ao modelo traziam o preço; com parent-document, **100%**. O ranking não muda (o parent-document não altera quem foi achado), muda o que o modelo consegue responder.

**Segurança na ingestão.** O texto do catálogo vem de lojistas, ou seja, de terceiros. Antes de indexar, frases que parecem instruções para o modelo ("ignore as instruções anteriores...") são removidas e o produto conta como `flagged` no relatório do reindex. É a defesa contra **injeção indireta**.

### 3.2 Embeddings, pgvector e HNSW

**Embedding** transforma texto em um vetor de 256 números (aqui, feature hashing de palavras, radicais e bigramas: determinístico e sem modelo). **Similaridade de cosseno** mede o ângulo entre vetores. O **HNSW** é um índice de grafo que acha vizinhos próximos sem comparar com todos: ganha velocidade e perde exatidão (por isso "aproximado"). Em catálogo de 24 produtos não faria diferença; a escolha é para a escala de milhares.

**Trade-off que importa.** Embedding lexical só enxerga palavras em comum. Com um modelo real (`nomic-embed-text`, por exemplo) "algo para ouvir música sem incomodar" se aproxima de "fone com cancelamento de ruído" sozinho. Aqui isso é coberto pelo léxico de sinônimos (3.5), que é um remendo, não um substituto.

### 3.3 Busca híbrida e RRF

**O que faz.** Roda duas buscas: vetorial (significado) e de texto (`tsvector` em português, sem acento) e funde as posições com **Reciprocal Rank Fusion**: cada lista contribui `peso / (60 + posição)` por item.

**Por que existe.** Vetor acha paráfrase e erra termo exato ("65W", código de produto); texto acha termo exato e erra paráfrase. RRF funde só por **posição**, então não precisa normalizar as pontuações (que têm escalas incomparáveis).

**Medido.** Pesos 1,0/1,0 foram os melhores. Pesar o vetor (1,5/0,5) derrubou hit@3 de 0,923 para 0,910; pesar o texto (0,5/1,5) também. Com embedder lexical os dois ramos concordam muito, então o ajuste fino rende pouco. Os pesos continuam configuráveis (`vector_weight`, `text_weight`).

### 3.4 Reranker e filtros

**Reranker.** Reordena os 10 candidatos pela cobertura lexical da pergunta (mais o nome do produto e a posição original). Quem tem cobertura zero recebe pontuação 0 e é cortado: é isso que transforma "nada relevante" em "não encontrei" em vez de uma recomendação inventada. Um cross-encoder entraria na mesma porta.

**Filtros de metadados (pré-filtro).** Preço máximo/mínimo, nota mínima e categoria são extraídos do texto ("até R$ 100", "nota acima de 4,8", "o mais barato de esporte") e aplicados **no SQL, antes da busca vetorial**. Isso é crucial: filtrar depois da busca perde resultados quando o catálogo cresce. Teste reproduzível: com 200 clones do fone e a pergunta "fone até 100 reais", o pré-filtro devolve 4 produtos dentro do preço e o pós-filtro devolve **0**.

### 3.5 Entendimento da consulta

É onde o sistema deixa de passar a pergunta crua para a busca.

- **Intenção.** Regras determinísticas classificam em catálogo, estoque, pedido, política ou fora de escopo, usando o vocabulário do próprio catálogo. Fora de escopo ("qual a capital da França?") termina sem ferramenta e sem contexto: a abstenção em perguntas sem resposta foi de 0,765 para 0,882.
- **Expansão de sinônimos (rewrite).** Termos relacionados entram na busca com **metade do peso** dos originais. É a maior alavanca de recuperação medida: MRR **0,870 para 0,913** e hit@1 de 0,756 para 0,808, porque resolve paráfrases sem palavra em comum.
- **Correção de digitação.** Distância de edição contra o vocabulário do catálogo ("tecaldo" vira "teclado"). Ganho pequeno aqui (+0,013 em hit@1): quase todo erro cai em uma frase com outras palavras certas.
- **Negação.** "quero algo de casa, não quero luminária" exclui a luminária. O baseline devolvia o produto proibido em todos os casos; com negação, nunca devolve (negação 0,000 para 1,000).
- **Decomposição.** "fone até R$ 400 e uma mochila até R$ 350" vira duas buscas com filtros próprios.
- **HyDE.** O modelo escreve uma resposta hipotética e a busca usa esse texto. Fica implementado e **desligado**: medido, ele piorou o MRR em combinação com a expansão (0,942 contra 0,952) e custa uma chamada extra ao LLM.
- **MMR.** Reduz redundância entre resultados. **Neutro** neste catálogo (um chunk por produto já evita repetição). Útil em catálogos com muitos produtos quase iguais.

A configuração de produção é a que sobrou da medição, não a que parecia mais sofisticada: expansão sempre, digitação, negação, decomposição, parent-document, roteamento de intenção.

### 3.6 O agente e as ferramentas

Um laço **planejar, agir, observar** com no máximo 3 passos e 4 ferramentas: `search_products` (RAG), `get_stock` (inventory), `get_order_status` (ordering) e `get_policy` (trocas, entrega, pagamento). O `Planner` é uma porta: a versão padrão é um conjunto de regras; existe um `LlmPlanner` que pede ao modelo **JSON validado com pydantic**, confere a ferramenta contra uma lista permitida e cai nas regras se a saída for inválida. Cada ferramenta tem timeout: uma ferramenta lenta vira uma observação "demorou demais" em vez de travar a conversa.

**Memória.** As últimas 6 mensagens guardam os produtos citados: "e esse tem estoque?" e "qual o mais barato deles?" resolvem a referência. Perguntas que dependem do histórico nunca entram no cache.

### 3.7 Cache semântico

**O que faz.** Guarda a resposta no pgvector. Uma pergunta nova só reaproveita uma entrada se tiver a **mesma chave** (filtros, ordenação, negações) e similaridade de cosseno >= 0,92. Expira por TTL (1 hora) e é **invalidado por eventos do catálogo** (`ProductPriceChanged`, `ProductUpdated`, `ProductDeleted`, `ProductCreated` em `catalog.events`): remove as respostas que citam o produto e, para mudanças que podem alterar quem entra no resultado, as que dependem de filtro ou foram "não encontrei".

**O que nunca entra.** Estoque e pedido (dado vivo), perguntas que dependem do histórico, respostas fora do embasamento, respostas degradadas.

**Medido** (107 perguntas do conjunto dourado, 4 passadas): 85 elegíveis, hit rate de 1,000 nas passadas repetidas, 0,750 no total, **137.556 tokens** (US$ 0,0688 de referência) economizados. A passada com "por favor... obrigado" só acertou depois de tratar essas palavras como vazias: o cache herda a qualidade da normalização do texto.

**Armadilha que o teste pegou.** "fone com cancelamento" e "fone sem cancelamento" têm embeddings quase iguais (o "sem" é palavra vazia). Por isso a chave inclui as palavras de negação: sem isso o cache devolveria a resposta errada.

### 3.8 Guardrails

- **Injeção direta (a mensagem do usuário).** Detector com 9 categorias (sobrescrever instruções, trocar de papel, exfiltrar o prompt, falsificar delimitadores, abusar de ferramenta, canal de exfiltração, forçar saída, alegar autoridade, manipular preço) em português e inglês, depois de normalizar acento, caixa, caracteres invisíveis, homóglifos, letras separadas, leetspeak e payloads em base64. Pontuação >= 0,7 bloqueia antes do agente e do modelo.
- **Injeção indireta (texto de produto).** Sanitizado na ingestão **e** de novo na montagem do prompt (defesa em profundidade): frases suspeitas, tags falsas (`</contexto><system>`), imagens markdown e links são removidos. Teste do pior caso: um LLM "papagaio" que repete todo o contexto não consegue vazar a carga maliciosa.
- **PII.** CPF, CNPJ, e-mail, telefone, cartão (com Luhn) e tokens são trocados por rótulos em **logs** (na criação do registro) e em **atributos de span**.
- **Saída estruturada.** `generate_structured` pede JSON, valida com pydantic e, se falhar, devolve o erro de validação ao modelo para reparar (até 2 tentativas) antes de desistir.
- **Citações verificadas.** Toda afirmação numérica precisa existir no trecho que ela cita (ou na observação da ferramenta, quando não cita nada). Um preço trocado entre produtos ou inventado remove a frase; sem sobrar nada, devolve uma recusa segura. Também bloqueia vazamento do system prompt, link ou HTML que não estava no contexto e dado pessoal que não veio do contexto.
- **Orçamento.** Tokens e custo por **sessão** e por **usuário por dia** (cabeçalho `X-User-Id`, senão o IP). Estourou: 429 com `Retry-After` (ou evento `error` no SSE).

Há 41 ataques catalogados nos testes (`tests/attacks.py` mais os casos de saída): 24 diretos, 7 indiretos (via catálogo) e 10 de modelo obediente.

### 3.9 Streaming, timeouts e fallback

Três perguntas diferentes, três respostas:

1. **O cliente fechou a aba.** O Starlette cancela a tarefa; o gerador fecha a conexão com o LLM (o Ollama para de gerar), contabiliza os tokens já gastos, não grava a resposta incompleta e marca o stream como cancelado.
2. **O LLM demora.** Timeout de primeiro token (15 s), ocioso entre tokens (10 s) e total (60 s).
3. **O LLM caiu.** Devolve os resultados da busca, sem modelo, com preços do catálogo e `degraded: true` mais um aviso. Se a **busca** é que caiu, diz "não consegui consultar o catálogo" em vez de "não encontrei": mentir que não existe é pior que admitir que falhou.

### 3.10 Observabilidade

Spans `assistant.chat > understand, cache, rewrite, retrieve, rerank, tool, generate, guard`, com atributos no padrão `gen_ai.*` (modelo, tokens de entrada e saída) e custo estimado. Métricas Prometheus: latência por etapa, tokens, custo, cache (hit, miss, skip, economia), guardrails, orçamento, fallbacks, streams ativos e cancelados. O dashboard tem um teste que garante que toda consulta usa uma métrica que existe de verdade.

### 3.11 Avaliação

**Conjunto dourado:** 111 casos (eram 36) em 15 categorias, com um **holdout** de 35 casos escritos depois de congelar as regras. **Métricas:** hit@1/3/5, MRR, nDCG@5, precisão e revocação de contexto, negação, abstenção; e, via juiz atrás da interface `JudgeLlm` (heurístico determinístico por padrão, `LlmJudge` para um modelo), faithfulness e answer relevancy. **Portão de regressão:** `python -m assistant.evals --offline --gate` falha se uma métrica cair abaixo do piso (`evals/thresholds.json`) ou mais de 0,02 abaixo da linha de base (`evals/baseline.json`), e roda no CI.

## 4. Números medidos (antes e depois)

| métrica (95 casos de recuperação) | baseline | produção |
|---|---|---|
| hit@1 | 0,756 | 0,859 |
| hit@3 | 0,923 | 0,962 |
| MRR | 0,870 | 0,952 |
| nDCG@5 | 0,861 | 0,942 |
| precisão de contexto | 0,870 | 0,951 |
| revocação de contexto | 0,892 | 0,957 |
| negação (proibido fora do resultado) | 0,000 | 1,000 |
| abstenção (sem resposta, sem contexto) | 0,765 | 0,882 |
| trechos com preço no contexto | 0,771 | 1,000 |
| hit@3 no holdout | 0,909 | 0,939 |

Ponta a ponta (111 casos): hit@3 0,965, MRR 0,956, nDCG@5 0,946, faithfulness 1,000, groundedness 1,000, tool accuracy 1,000, answer pass 0,991. No conjunto original de 36 casos: hit@3 de 0,893 para 0,964.

## 5. O que é simulado e o que mudaria com um modelo real

| Simulado | Com modelo real |
|---|---|
| `HashingEmbedder` (lexical) | Embeddings semânticos: paráfrases param de depender do léxico; HyDE e MMR provavelmente passam a valer. |
| `MockLlm` (gera só do contexto) | Fluência, mas também alucinação e obediência a injeção: os guardrails de saída deixam de ser teóricos. |
| `HeuristicJudge` | Um juiz LLM (`LlmJudge`); o heurístico fica como termômetro barato de regressão. |
| Preço de referência de tokens | Uso real reportado pelo provedor. |

Os adaptadores do Ollama existem e são testados contra um servidor HTTP falso (`tests/fake_ollama.py`): streaming NDJSON, erro 503, conexão fechada pelo cliente. O Ollama real não foi instalado nesta máquina: falta rodar e reavaliar.

## 6. Quinze perguntas de entrevista

**1. O que é RAG e quando usar em vez de fine-tuning?**
Recuperar trechos relevantes e colocá-los no prompt para o modelo responder com base neles. Use quando o conhecimento muda (catálogo, políticas), precisa de citação e de controle de acesso. Fine-tuning ensina estilo e formato, não fatos que mudam todo dia.

**2. Por que busca híbrida (vetor mais texto) e não só vetor?**
Vetor acha paráfrase e erra termo exato (código, modelo, "65W"); texto faz o inverso. Fundir os dois cobre os dois erros. Aqui, a fusão por RRF evitou normalizar escalas diferentes.

**3. Como funciona o RRF e por que ele não precisa normalizar pontuações?**
Cada lista dá `peso / (k + posição)` ao item e soma-se. Só a posição entra, então pontuações de escalas incomparáveis (cosseno contra `ts_rank`) não importam. `k = 60` suaviza a diferença entre as primeiras posições.

**4. HNSW é exato? Qual o trade-off?**
Não, é aproximado: um grafo navegável que troca revocação por velocidade (parâmetros `m`, `ef_construction`, `ef_search`). Em catálogo pequeno uma varredura exata basta; o índice é para escala.

**5. Como escolher o tamanho do chunk?**
Medindo. Chunk pequeno acha melhor e entrega pouco; grande entrega contexto e dilui o sinal. O padrão forte é indexar pequeno e entregar grande (parent-document). Aqui, chunks de 150 deixaram só 24% dos trechos com preço; com parent-document, 100%.

**6. Pré-filtro ou pós-filtro por metadados?**
Pré-filtro, no SQL, antes da busca vetorial. O pós-filtro corta o top-k já escolhido e pode devolver vazio: no teste com 200 clones do fone, "até 100 reais" deu 4 resultados com pré-filtro e 0 com pós-filtro.

**7. O que são HyDE e query expansion, e quando atrapalham?**
Expansão adiciona termos relacionados; HyDE gera um documento hipotético e busca por ele. Ajudam em paráfrases e atrapalham quando puxam termos de outro assunto (falsos positivos) ou custam uma chamada de LLM extra. Aqui a expansão deu +0,044 de MRR; o HyDE piorou em combinação e ficou desligado.

**8. Como avaliar um sistema de RAG sem "achar" que está bom?**
Conjunto dourado com casos de várias categorias (paráfrase, negação, erro de digitação, adversarial), métricas de recuperação (hit@k, MRR, nDCG, precisão e revocação de contexto) e de geração (faithfulness, relevância), um holdout para não ajustar às cegas e um portão de regressão no CI.

**9. O que mede faithfulness e como evitar um juiz LLM enviesado?**
Se as afirmações da resposta estão sustentadas pelo contexto. Reduza o viés com rubrica fechada, saída estruturada validada, um juiz determinístico para regressão barata e calibração periódica do juiz LLM contra rótulos humanos.

**10. Como funciona o agente e como limitar o risco do tool use?**
Laço planejar, agir, observar com limite de passos. Risco: o modelo escolher uma ferramenta ou argumento perigoso. Mitigação: lista permitida, argumentos validados (UUID, esquema pydantic), timeout por ferramenta, ferramentas somente de leitura e fallback para regras quando a saída do planejador é inválida.

**11. Qual a diferença entre injeção direta e indireta, e como defender?**
Direta vem da mensagem do usuário; indireta vem de texto de terceiros recuperado (descrição de produto, página, e-mail). Defesa em camadas: detector na entrada, sanitização do texto recuperado na ingestão e no prompt, delimitadores e instrução de "dado não confiável", validação da saída e privilégio mínimo nas ferramentas. Nenhuma camada sozinha basta.

**12. Como garantir que a resposta não inventa preço ou número?**
Verificar cada afirmação numérica contra o trecho que ela cita (ou a observação da ferramenta), remover a frase que não bate e recusar com segurança se nada sobrar. É uma checagem determinística, barata e independente do modelo.

**13. Como funciona um cache semântico e qual o risco?**
Embedding da pergunta mais busca do vizinho mais próximo acima de um limiar, com a mesma chave de filtros. Riscos: devolver resposta de uma pergunta parecida mas diferente (negação, número), dado velho e vazamento entre usuários. Mitigação: chave com filtros e negações, TTL, invalidação por evento do catálogo e nunca cachear dado vivo nem resposta que dependa do histórico.

**14. O usuário fechou a aba no meio do stream. O que deve acontecer?**
Cancelar a geração e fechar a conexão com o provedor (para não pagar por tokens que ninguém lê), registrar os tokens já gastos, não gravar a resposta incompleta e liberar o slot do stream. Em async, isso é tratar o cancelamento no gerador e fechar o iterador do LLM no `finally`.

**15. O LLM caiu ou ficou lento. O que o usuário vê?**
Timeouts por fase (primeiro token, ocioso, total) e degradação graciosa: os resultados da busca, sem modelo, com um aviso e `degraded: true`. Se a própria busca caiu, a resposta diz isso em vez de "não encontrei". Observabilidade (taxa de fallback por motivo) mostra se virou rotina.

## 7. Como rodar e reproduzir

```bash
cd backend/services/assistant
uv run python -m assistant.evals --offline --gate        # métricas ponta a ponta e portão
uv run python -m assistant.rageval --write-docs ../../../docs/RAG-EVALUATION.md   # comparação de variantes (gera a versão em inglês)
uv run python -m assistant.cachebench                    # hit rate e economia do cache
uv run python -m assistant.worker_main                   # consumidor de catalog.events (invalida cache e reindexa)
uv run pytest                                            # unitários, integração (pgvector real), red team
```
