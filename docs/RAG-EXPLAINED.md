**English** | [Português (Brasil)](pt-BR/RAG-EXPLICADO.md)

# RAG and Agents Explained (for .NET Developers)

This guide explains, end to end, the pipeline of the marketplace's `assistant` service: what each stage does, why it exists, what it costs, and what was actually measured. It is written for someone with a solid back-end background (C#, ASP.NET, EF Core, queues) who has never built a RAG system.

The numbers come from `docs/RAG-EVALUATION.md` (full table and how to reproduce). Everything runs with **simulated embeddings and a simulated LLM** (no API key), and that limits what the numbers prove: see the "What is simulated" section at the end.

## 1. Quick concept translation

| RAG/LLM concept | What it looks like in the .NET world |
|---|---|
| Embedding | A hash function, but one that preserves **meaning**: similar texts become nearby vectors. |
| Vector database (pgvector) | A SQL Server index, except the lookup is by **proximity** instead of equality. |
| HNSW | An approximate index: trades a little accuracy for a lot of speed, like a smart `TABLESAMPLE`. |
| Chunking | Paging a large document into pieces that fit in the context. |
| Hybrid search + RRF | Two different `OrderBy` clauses (vector and text) merged into a single list, like a `Union` ordered by position. |
| Reranker | A second `OrderBy`, more expensive and more precise, applied only to the top 10. |
| Tool use | Strategy/Command: the model picks which "method" to call, the code runs it and returns the result. |
| Guardrails | Input and output validation (FluentValidation), plus an authorization filter in the middle of the pipeline. |
| Semantic cache | `IMemoryCache`, but the key is "questions with the same meaning" rather than the exact string. |
| Prompt injection | SQL injection for natural language: third-party text turning into instructions. |
| OpenTelemetry spans | .NET's `Activity`/`ActivitySource`: same idea, same semantics. |
| Token budget | Rate limiting, but charged in tokens and dollars instead of requests. |
| Eval harness | A regression test project, except the metric is answer quality instead of pass/fail. |

## 2. The full pipeline

```
 Customer question (POST /chat or /chat/stream)
        |
        v
 [0] VALIDATE  length, empty -> 422
        |
        v
 [1] INPUT GUARD  prompt injection detector (9 categories + obfuscation)
        |  score >= 0.7 ? ----yes----> "I can't follow that kind of instruction" (no agent, no model)
        v
 [2] SEMANTIC CACHE  same filter key + similarity >= 0.92 ?
        |  hit ------------------------------------------------> returns the stored answer
        v  miss                                                   (no agent, no model)
 [3] QUERY UNDERSTANDING
        |   intent: catalog | stock | order | policy | out of scope
        |   out of scope -> short answer, no tool
        |   filters (price, rating, category, sorting), negation, typo correction,
        |   synonym expansion, HyDE (optional), decomposition of compound questions
        v
 [4] AGENT (at most 3 steps)  Planner -> tool -> observation -> Planner ...
        |      search_products  get_stock  get_order_status  get_policy   (each with a timeout)
        |
        |   search_products:
        |     [4a] metadata pre-filter (SQL)
        |     [4b] vector (pgvector HNSW)  +  text (tsvector)       logically in parallel
        |     [4c] weighted RRF fusion
        |     [4d] one chunk per product, lexical rerank (expanded terms count half)
        |     [4e] score cutoff, MMR (optional), parent-document (chunk found, whole product enters)
        v
 [5] PROMPT  delimited context + sanitization of third-party text (indirect injection)
        |      budget check per session and per user
        v
 [6] GENERATION  LLM (mock or Ollama), streaming, with first-token, idle, and total timeouts
        |      failed or timed out? -> FALLBACK: search results without the model + warning
        |      client closed the tab? -> closes the model connection, accounts for the partial output
        v
 [7] OUTPUT GUARD  valid citations, non-retrieved product, numbers match the cited
        |      passage, system prompt leak, link/HTML/personal data that was not in the context
        v
 [8] RECORD  session (memory), budget, cache (if eligible), metrics, and spans
        |
        v
 answer + citations + tool_calls + retrieved + latency_ms (+ cached, degraded, warning)
```

Each of stages 3 to 7 becomes an OpenTelemetry **span** and a data point in the `assistant_step_duration_seconds` histogram; tokens and cost become counters; the Grafana dashboard (`infra/observability/grafana/dashboards/assistant.json`) shows it all.

## 3. Stage by stage: why it exists, trade-offs, numbers

### 3.1 Ingestion and chunking

**What it does.** Reads the catalog, builds one document per product (description, price, rating, merchant, keywords), splits it into chunks of up to 300 characters with 60 of overlap, and prefixes each chunk with a **contextual header** (`Produto: ... | Categoria: ...`). Generates embeddings, writes them to pgvector, and only reprocesses what changed (content hash).

**Why it exists.** The model and the index work with small passages: a whole document dilutes the signal. The header prevents the "orphan" chunk that does not say which product it is about.

**Trade-offs.** A small chunk is easier to find but delivers little context; a large chunk is the opposite. The modern answer is **parent-document retrieval**: index small pieces and, after finding one, deliver the product's whole document. Measured: with 150-character chunks only **24%** of the passages delivered to the model carried the price; with parent-document, **100%**. The ranking does not change (parent-document does not alter what was found); what changes is what the model is able to answer.

**Ingestion security.** The catalog text comes from merchants, that is, from third parties. Before indexing, sentences that look like instructions to the model ("ignore the previous instructions...") are removed and the product counts as `flagged` in the reindex report. This is the defense against **indirect injection**.

### 3.2 Embeddings, pgvector, and HNSW

An **embedding** turns text into a vector of 256 numbers (here, feature hashing of words, stems, and bigrams: deterministic and model-free). **Cosine similarity** measures the angle between vectors. **HNSW** is a graph index that finds nearby neighbors without comparing against all of them: it gains speed and loses exactness (hence "approximate"). On a 24-product catalog it would make no difference; the choice is for the scale of thousands.

**The trade-off that matters.** A lexical embedding only sees shared words. With a real model (`nomic-embed-text`, for example) "something to listen to music without bothering anyone" moves close to "noise-cancelling headphones" on its own. Here that is covered by the synonym lexicon (3.5), which is a patch, not a substitute.

### 3.3 Hybrid search and RRF

**What it does.** Runs two searches: vector (meaning) and text (Portuguese `tsvector`, accent-insensitive), and merges the positions with **Reciprocal Rank Fusion**: each list contributes `weight / (60 + position)` per item.

**Why it exists.** Vector search finds paraphrases and misses exact terms ("65W", product codes); text search finds exact terms and misses paraphrases. RRF merges by **position** only, so it does not need to normalize the scores (which have incomparable scales).

**Measured.** Weights 1.0/1.0 were the best. Weighting the vector branch (1.5/0.5) dropped hit@3 from 0.923 to 0.910; weighting the text branch (0.5/1.5) did too. With the lexical embedder the two branches agree a lot, so fine-tuning yields little. The weights remain configurable (`vector_weight`, `text_weight`).

### 3.4 Reranker and filters

**Reranker.** Reorders the 10 candidates by the lexical coverage of the question (plus the product name and the original position). Anything with zero coverage gets a score of 0 and is cut: that is what turns "nothing relevant" into "I didn't find it" instead of an invented recommendation. A cross-encoder would plug into the same slot.

**Metadata filters (pre-filter).** Maximum/minimum price, minimum rating, and category are extracted from the text ("up to R$ 100", "rating above 4.8", "the cheapest sports item") and applied **in SQL, before the vector search**. This is crucial: filtering after the search loses results as the catalog grows. Reproducible test: with 200 headphone clones and the question "fone até 100 reais" (headphones up to 100 reais), the pre-filter returns 4 products within the price and the post-filter returns **0**.

### 3.5 Query understanding

This is where the system stops passing the raw question to the search.

- **Intent.** Deterministic rules classify into catalog, stock, order, policy, or out of scope, using the catalog's own vocabulary. Out of scope ("what is the capital of France?") ends with no tool and no context: abstention on unanswerable questions went from 0.765 to 0.882.
- **Synonym expansion (rewrite).** Related terms enter the search at **half the weight** of the originals. It is the biggest retrieval lever measured: MRR **0.870 to 0.913** and hit@1 from 0.756 to 0.808, because it resolves paraphrases with no shared word.
- **Typo correction.** Edit distance against the catalog vocabulary ("tecaldo" becomes "teclado"). Small gain here (+0.013 in hit@1): almost every typo lands in a sentence with other correct words.
- **Negation.** "quero algo de casa, não quero luminária" (I want something for the home, I don't want a lamp) excludes the lamp. The baseline returned the forbidden product in every case; with negation, it never does (negation 0.000 to 1.000).
- **Decomposition.** "fone até R$ 400 e uma mochila até R$ 350" (headphones up to R$ 400 and a backpack up to R$ 350) becomes two searches with their own filters.
- **HyDE.** The model writes a hypothetical answer and the search uses that text. It stays implemented and **off**: measured, it worsened MRR in combination with expansion (0.942 vs. 0.952) and costs an extra LLM call.
- **MMR.** Reduces redundancy among results. **Neutral** on this catalog (one chunk per product already avoids repetition). Useful on catalogs with many near-identical products.

The production configuration is what survived measurement, not what looked most sophisticated: always-on expansion, typo correction, negation, decomposition, parent-document, intent routing.

### 3.6 The agent and the tools

A **plan, act, observe** loop with at most 3 steps and 4 tools: `search_products` (RAG), `get_stock` (inventory), `get_order_status` (ordering), and `get_policy` (returns, shipping, payment). The `Planner` is a port: the default implementation is a set of rules; there is an `LlmPlanner` that asks the model for **JSON validated with pydantic**, checks the tool against an allowlist, and falls back to the rules if the output is invalid. Each tool has a timeout: a slow tool becomes a "took too long" observation instead of freezing the conversation.

**Memory.** The last 6 messages keep the products cited: "does that one have stock?" and "which of them is the cheapest?" resolve the reference. Questions that depend on history never enter the cache.

### 3.7 Semantic cache

**What it does.** Stores the answer in pgvector. A new question only reuses an entry if it has the **same key** (filters, sorting, negations) and a cosine similarity >= 0.92. It expires by TTL (1 hour) and is **invalidated by catalog events** (`ProductPriceChanged`, `ProductUpdated`, `ProductDeleted`, `ProductCreated` on `catalog.events`): it removes the answers that cite the product and, for changes that can alter which products enter the result, the ones that depend on a filter or were "not found".

**What never enters.** Stock and order (live data), questions that depend on history, answers outside grounding, degraded answers.

**Measured** (107 questions from the golden set, 4 passes): 85 eligible, hit rate of 1.000 on the repeated passes, 0.750 overall, **137,556 tokens** (US$ 0.0688 at the reference price) saved. The pass with "por favor... obrigado" (please... thank you) only hit after those words were treated as stop words: the cache inherits the quality of the text normalization.

**A trap the test caught.** "fone com cancelamento" (headphones with cancellation) and "fone sem cancelamento" (headphones without cancellation) have nearly identical embeddings ("sem" is a stop word). That is why the key includes the negation words: without it the cache would return the wrong answer.

### 3.8 Guardrails

- **Direct injection (the user's message).** A detector with 9 categories (override instructions, switch roles, exfiltrate the prompt, forge delimiters, abuse a tool, exfiltration channel, force output, claim authority, manipulate price) in Portuguese and English, after normalizing accents, case, invisible characters, homoglyphs, spaced-out letters, leetspeak, and base64 payloads. A score >= 0.7 blocks before the agent and the model.
- **Indirect injection (product text).** Sanitized at ingestion **and** again when the prompt is assembled (defense in depth): suspicious phrases, fake tags (`</contexto><system>`), markdown images, and links are removed. Worst-case test: a "parrot" LLM that repeats the whole context cannot leak the malicious payload.
- **PII.** CPF, CNPJ, email, phone, card (with Luhn), and tokens are replaced by labels in **logs** (at record creation) and in **span attributes**.
- **Structured output.** `generate_structured` asks for JSON, validates it with pydantic and, if that fails, returns the validation error to the model to repair (up to 2 attempts) before giving up.
- **Verified citations.** Every numeric claim must exist in the passage it cites (or in the tool observation, when it cites nothing). A price swapped between products or invented removes the sentence; if nothing is left, it returns a safe refusal. It also blocks system prompt leaks, links or HTML that were not in the context, and personal data that did not come from the context.
- **Budget.** Tokens and cost per **session** and per **user per day** (`X-User-Id` header, otherwise the IP). When exceeded: 429 with `Retry-After` (or an `error` event on SSE).

The tests catalog 41 attacks (`tests/attacks.py` plus the output cases): 24 direct, 7 indirect (via the catalog), and 10 obedient-model cases.

### 3.9 Streaming, timeouts, and fallback

Three different questions, three different answers:

1. **The client closed the tab.** Starlette cancels the task; the generator closes the connection to the LLM (Ollama stops generating), accounts for the tokens already spent, does not store the incomplete answer, and marks the stream as canceled.
2. **The LLM is slow.** First-token timeout (15 s), idle timeout between tokens (10 s), and total timeout (60 s).
3. **The LLM is down.** Returns the search results, without the model, with catalog prices and `degraded: true` plus a warning. If it is the **search** that is down, it says "I couldn't query the catalog" instead of "I didn't find it": lying that something does not exist is worse than admitting a failure.

### 3.10 Observability

Spans `assistant.chat > understand, cache, rewrite, retrieve, rerank, tool, generate, guard`, with attributes following the `gen_ai.*` convention (model, input and output tokens) and estimated cost. Prometheus metrics: latency per stage, tokens, cost, cache (hit, miss, skip, savings), guardrails, budget, fallbacks, and active and canceled streams. The dashboard has a test that guarantees every query uses a metric that actually exists.

### 3.11 Evaluation

**Golden set:** 111 cases (up from 36) in 15 categories, with a **holdout** of 35 cases written after the rules were frozen. **Metrics:** hit@1/3/5, MRR, nDCG@5, context precision and recall, negation, abstention; and, via a judge behind the `JudgeLlm` interface (deterministic heuristic by default, `LlmJudge` for a model), faithfulness and answer relevancy. **Regression gate:** `python -m assistant.evals --offline --gate` fails if a metric falls below the floor (`evals/thresholds.json`) or more than 0.02 below the baseline (`evals/baseline.json`), and it runs in CI.

## 4. Measured numbers (before and after)

| metric (95 retrieval cases) | baseline | production |
|---|---|---|
| hit@1 | 0.756 | 0.859 |
| hit@3 | 0.923 | 0.962 |
| MRR | 0.870 | 0.952 |
| nDCG@5 | 0.861 | 0.942 |
| context precision | 0.870 | 0.951 |
| context recall | 0.892 | 0.957 |
| negation (forbidden product kept out) | 0.000 | 1.000 |
| abstention (no answer, no context) | 0.765 | 0.882 |
| passages with price in context | 0.771 | 1.000 |
| hit@3 on the holdout | 0.909 | 0.939 |

End to end (111 cases): hit@3 0.965, MRR 0.956, nDCG@5 0.946, faithfulness 1.000, groundedness 1.000, tool accuracy 1.000, answer pass 0.991. On the original 36-case set: hit@3 from 0.893 to 0.964.

## 5. What is simulated and what would change with a real model

| Simulated | With a real model |
|---|---|
| `HashingEmbedder` (lexical) | Semantic embeddings: paraphrases stop depending on the lexicon; HyDE and MMR probably start to pay off. |
| `MockLlm` (generates only from the context) | Fluency, but also hallucination and obedience to injection: the output guardrails stop being theoretical. |
| `HeuristicJudge` | An LLM judge (`LlmJudge`); the heuristic stays as a cheap regression thermometer. |
| Reference token price | Actual usage reported by the provider. |

The Ollama adapters exist and are tested against a fake HTTP server (`tests/fake_ollama.py`): NDJSON streaming, 503 error, connection closed by the client. The real Ollama was not installed on this machine: running and re-evaluating is still pending.

## 6. Fifteen interview questions

**1. What is RAG, and when would you use it instead of fine-tuning?**
Retrieve relevant passages and put them in the prompt so the model answers based on them. Use it when the knowledge changes (catalog, policies) and needs citations and access control. Fine-tuning teaches style and format, not facts that change every day.

**2. Why hybrid search (vector plus text) and not vector alone?**
Vector search finds paraphrases and misses exact terms (code, model, "65W"); text search does the opposite. Merging the two covers both failure modes. Here, RRF fusion avoided normalizing different scales.

**3. How does RRF work, and why does it not need to normalize scores?**
Each list gives the item `weight / (k + position)` and the contributions are summed. Only the position goes in, so scores on incomparable scales (cosine vs. `ts_rank`) do not matter. `k = 60` smooths the difference between the top positions.

**4. Is HNSW exact? What is the trade-off?**
No, it is approximate: a navigable graph that trades recall for speed (parameters `m`, `ef_construction`, `ef_search`). On a small catalog an exact scan is enough; the index is for scale.

**5. How do you choose the chunk size?**
By measuring. A small chunk is easier to find and delivers little; a large one delivers context and dilutes the signal. The strong pattern is to index small and deliver large (parent-document). Here, 150-character chunks left only 24% of the passages with a price; with parent-document, 100%.

**6. Pre-filter or post-filter on metadata?**
Pre-filter, in SQL, before the vector search. A post-filter trims the top-k that was already chosen and can return nothing: in the test with 200 headphone clones, "up to 100 reais" gave 4 results with the pre-filter and 0 with the post-filter.

**7. What are HyDE and query expansion, and when do they hurt?**
Expansion adds related terms; HyDE generates a hypothetical document and searches with it. They help with paraphrases and hurt when they pull in terms from another topic (false positives) or cost an extra LLM call. Here expansion gave +0.044 MRR; HyDE got worse in combination and stayed off.

**8. How do you evaluate a RAG system without just "feeling" it is good?**
A golden set with cases from several categories (paraphrase, negation, typo, adversarial), retrieval metrics (hit@k, MRR, nDCG, context precision and recall) and generation metrics (faithfulness, relevancy), a holdout so you do not tune blindly, and a regression gate in CI.

**9. What does faithfulness measure, and how do you avoid a biased LLM judge?**
Whether the claims in the answer are supported by the context. Reduce bias with a closed rubric, validated structured output, a deterministic judge for cheap regression checks, and periodic calibration of the LLM judge against human labels.

**10. How does the agent work, and how do you limit the risk of tool use?**
A plan, act, observe loop with a step limit. The risk: the model picks a dangerous tool or argument. Mitigation: an allowlist, validated arguments (UUID, pydantic schema), a per-tool timeout, read-only tools, and a fallback to rules when the planner's output is invalid.

**11. What is the difference between direct and indirect injection, and how do you defend against them?**
Direct comes from the user's message; indirect comes from retrieved third-party text (product description, web page, email). Layered defense: a detector on input, sanitization of retrieved text at ingestion and in the prompt, delimiters and an "untrusted data" instruction, output validation, and least privilege on the tools. No single layer is enough.

**12. How do you make sure the answer does not invent a price or number?**
Verify every numeric claim against the passage it cites (or the tool observation), drop the sentence that does not match, and refuse safely if nothing is left. It is a deterministic check, cheap and independent of the model.

**13. How does a semantic cache work, and what is the risk?**
Embed the question, then look up the nearest neighbor above a threshold, with the same filter key. Risks: returning the answer to a similar but different question (negation, number), stale data, and leakage between users. Mitigation: a key with filters and negations, a TTL, invalidation by catalog event, and never caching live data or answers that depend on history.

**14. The user closed the tab in the middle of the stream. What should happen?**
Cancel the generation and close the connection to the provider (so you do not pay for tokens nobody reads), record the tokens already spent, do not store the incomplete answer, and free the stream slot. In async code, that means handling cancellation in the generator and closing the LLM iterator in the `finally` block.

**15. The LLM is down or slow. What does the user see?**
Per-phase timeouts (first token, idle, total) and graceful degradation: the search results, without the model, with a warning and `degraded: true`. If the search itself is down, the answer says so instead of "I didn't find it". Observability (fallback rate by reason) shows whether it has become routine.

## 7. How to run and reproduce

```bash
cd backend/services/assistant
uv run python -m assistant.evals --offline --gate        # end-to-end metrics and gate
uv run python -m assistant.rageval --write-docs ../../../docs/RAG-EVALUATION.md   # variant comparison
uv run python -m assistant.cachebench                    # cache hit rate and savings
uv run python -m assistant.worker_main                   # catalog.events consumer (invalidates cache and reindexes)
uv run pytest                                            # unit, integration (real pgvector), red team
```
