**English** | [Português (Brasil)](pt-BR/RAG-AVALIACAO.md)

# RAG Evaluation: Baseline vs. Each Improvement

This document records, with measured numbers, what each technique in the `assistant` retrieval pipeline changes in quality. Everything runs with the lexical embedder (`HashingEmbedder`) and the mock LLM (`MockLlm`), with no API key. The numbers are therefore a **relative comparison between variants** and a regression safety net, not a promise of quality with a real model (see the limitations at the end).

## How to reproduce

```bash
cd backend/services/assistant
uv run python -m assistant.rageval --write-docs ../../../docs/RAG-EVALUATION.md   # comparison table below
uv run python -m assistant.evals --offline                                        # end-to-end evaluation (agent, generation, judge)
uv run python -m assistant.evals --offline --gate                                 # regression gate used in CI
uv run python -m assistant.cachebench                                             # semantic cache hit rate and savings
```

`rageval` creates the `assistant_rageval` database, reindexes the catalog snapshot (24 products) once per chunk configuration, and runs every variant over the same cases. It refuses to wipe any database whose name does not end in `_rageval`.

## The golden set

`evals/cases.yaml` has **111 cases** (up from 36). Each case has a category and a `split` tag:

| category | cases | what it tests |
|---|---|---|
| direct | 24 | question using the catalog's own words |
| paraphrase | 19 | same idea in different words (synonyms, usage, context) |
| adversarial | 16 | prompt injection, out of scope, noise, SQL, emoji, fake price |
| typo | 10 | typing errors |
| multi_hop | 8 | two needs in one question; a question that needs search and then stock |
| negation | 6 | "except", "I don't want", "anything but"; the forbidden product must not appear |
| price, rating, sorting, category | 4, 2, 3, 1 | filters and sorting extracted from the text |
| stock, order, policy, memory, comparison | 4, 4, 4, 4, 2 | tools, store policy, references to earlier messages |

- **dev** (76 cases): used while the techniques were being built and tuned.
- **holdout** (35 cases): written **after** freezing the synonym lexicon and the query rules, with no later rule tweaks to make them pass. It is the most honest read on generalization this set allows. The same person wrote both parts and knows the catalog, so the holdout is optimistic: a real holdout would come from real user questions.

The retrieval harness uses the cases that do not depend on history and expect `search_products` or no tool (95 of 111). `negation` measures whether the forbidden product stayed out; `abstention` measures whether questions with no answer in the catalog returned empty context.

## Metrics

- **hit@k**: at least one expected product among the top k (all of them, in `require_all` cases). **MRR**: mean of 1/rank of the first expected product. **nDCG@5**: rank-discounted gain, with binary relevance.
- **context precision**: average precision (AP) over the passages handed to the model; rewards relevant ones at the top. **context recall**: fraction of the expected products present in the context (capped at the context size, 4).
- **ctx with price**: fraction of delivered passages that contain the product's price, a fact that purchase answers depend on. This is the metric that shows the parent-document gain.
- **faithfulness**: fraction of the answer's verifiable claims (sentences with a number or product name) whose numbers exist in the evidence. **answer relevancy**: lexical and semantic overlap with the question; refusals only count on questions with no answer. Both come from a deterministic heuristic judge behind the `JudgeLlm` interface; an LLM judge drops in without changing the harness.

## Comparison table

Each row ties one technique to the baseline (hybrid + RRF + lexical reranker, the original pipeline). In parentheses, the difference from the baseline. Latency is retrieval-only, measured on a machine shared with other containers: use it as an order of magnitude only.

<!-- rageval:start -->
Retrieval cases evaluated: 95.

| variant | hit@1 | hit@3 | MRR | nDCG@5 | ctx prec. | ctx recall | negation | abstention | ctx with price | hit@3 dev | hit@3 holdout | MRR holdout | p50 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline (hybrid + RRF + reranker) | 0.756 | 0.923 | 0.870 | 0.861 | 0.870 | 0.892 | 0.000 | 0.765 | 0.771 | 0.933 | 0.909 | 0.783 | 8 |
| post-filter instead of pre-filter | 0.756 | 0.923 | 0.870 | 0.861 | 0.870 | 0.892 | 0.000 | 0.765 | 0.771 | 0.933 | 0.909 | 0.783 | 6 |
| pre-filter, 5-candidate branches | 0.756 | 0.897 (-0.026) | 0.862 (-0.008) | 0.853 (-0.008) | 0.861 (-0.009) | 0.883 (-0.009) | 0.000 | 0.765 | 0.763 (-0.007) | 0.933 | 0.849 | 0.765 | 7 |
| post-filter, 5-candidate branches | 0.756 | 0.897 (-0.026) | 0.862 (-0.008) | 0.853 (-0.008) | 0.861 (-0.009) | 0.883 (-0.009) | 0.000 | 0.765 | 0.763 (-0.007) | 0.933 | 0.849 | 0.765 | 5 |
| RRF weights 0.5 vector / 1.5 text | 0.756 | 0.910 (-0.013) | 0.869 (-0.001) | 0.858 (-0.003) | 0.870 | 0.888 (-0.004) | 0.000 | 0.765 | 0.802 (+0.031) | 0.933 | 0.879 | 0.780 | 4 |
| RRF weights 1.5 vector / 0.5 text | 0.756 | 0.910 (-0.013) | 0.863 (-0.007) | 0.853 (-0.008) | 0.863 (-0.007) | 0.879 (-0.013) | 0.000 | 0.882 (+0.118) | 0.763 (-0.008) | 0.911 | 0.909 | 0.798 | 7 |
| + typo correction | 0.769 (+0.013) | 0.923 | 0.876 (+0.006) | 0.866 (+0.005) | 0.876 (+0.006) | 0.892 | 0.000 | 0.765 | 0.771 | 0.933 | 0.909 | 0.798 | 8 |
| + synonym expansion (always) | 0.808 (+0.051) | 0.936 (+0.013) | 0.913 (+0.044) | 0.903 (+0.042) | 0.911 (+0.041) | 0.926 (+0.034) | 0.000 | 0.765 | 0.690 (-0.081) | 0.978 | 0.879 | 0.826 | 5 |
| + synonym expansion (adaptive) | 0.782 (+0.026) | 0.936 (+0.013) | 0.901 (+0.031) | 0.890 (+0.030) | 0.902 (+0.032) | 0.918 (+0.026) | 0.000 | 0.765 | 0.742 (-0.029) | 0.978 | 0.879 | 0.795 | 6 |
| + HyDE (hypothetical document) | 0.782 (+0.026) | 0.923 | 0.885 (+0.015) | 0.872 (+0.011) | 0.885 (+0.015) | 0.892 | 0.000 | 0.882 (+0.118) | 0.733 (-0.038) | 0.933 | 0.909 | 0.818 | 7 |
| + negation | 0.808 (+0.051) | 0.949 (+0.026) | 0.908 (+0.038) | 0.897 (+0.037) | 0.908 (+0.038) | 0.923 (+0.031) | 1.000 (+1.000) | 0.765 | 0.794 (+0.023) | 0.933 | 0.970 | 0.874 | 7 |
| + decomposition | 0.756 | 0.923 | 0.876 (+0.006) | 0.864 (+0.003) | 0.873 (+0.003) | 0.892 | 0.000 | 0.765 | 0.771 | 0.933 | 0.909 | 0.798 | 7 |
| + MMR lambda 0.7 | 0.756 | 0.910 (-0.013) | 0.872 (+0.002) | 0.862 (+0.001) | 0.871 (+0.001) | 0.892 | 0.000 | 0.765 | 0.768 (-0.003) | 0.933 | 0.879 | 0.788 | 6 |
| + MMR lambda 0.4 | 0.756 | 0.923 | 0.870 | 0.860 (-0.001) | 0.868 (-0.002) | 0.892 | 0.000 | 0.765 | 0.768 (-0.003) | 0.933 | 0.909 | 0.783 | 7 |
| + intent routing | 0.756 | 0.923 | 0.870 | 0.861 | 0.870 | 0.892 | 0.000 | 0.882 (+0.118) | 0.765 (-0.006) | 0.933 | 0.909 | 0.783 | 12 |
| small chunks (150/30) | 0.769 (+0.013) | 0.923 | 0.882 (+0.013) | 0.871 (+0.010) | 0.883 (+0.014) | 0.892 | 0.000 | 0.765 | 0.243 (-0.528) | 0.933 | 0.909 | 0.813 | 5 |
| parent-document (300/60 chunks) | 0.756 | 0.923 | 0.870 | 0.861 | 0.870 | 0.892 | 0.000 | 0.765 | 1.000 (+0.229) | 0.933 | 0.909 | 0.783 | 9 |
| small chunks + parent-document | 0.769 (+0.013) | 0.923 | 0.882 (+0.013) | 0.871 (+0.010) | 0.883 (+0.014) | 0.892 | 0.000 | 0.765 | 1.000 (+0.229) | 0.933 | 0.909 | 0.813 | 6 |
| combo: adaptive + typo + negation + decomposition | 0.846 (+0.090) | 0.962 (+0.038) | 0.946 (+0.076) | 0.931 (+0.070) | 0.944 (+0.075) | 0.949 (+0.057) | 1.000 (+1.000) | 0.882 (+0.118) | 0.752 (-0.019) | 0.978 | 0.939 | 0.901 | 10 |
| combo: always + typo + negation + decomposition | 0.859 (+0.103) | 0.962 (+0.038) | 0.952 (+0.082) | 0.942 (+0.081) | 0.951 (+0.081) | 0.957 (+0.065) | 1.000 (+1.000) | 0.882 (+0.118) | 0.698 (-0.073) | 0.978 | 0.939 | 0.917 | 9 |
| previous combo + HyDE | 0.846 (+0.090) | 0.962 (+0.038) | 0.942 (+0.073) | 0.931 (+0.071) | 0.941 (+0.072) | 0.944 (+0.052) | 1.000 (+1.000) | 0.941 (+0.176) | 0.685 (-0.086) | 0.978 | 0.939 | 0.894 | 12 |
| previous combo + MMR 0.7 | 0.859 (+0.103) | 0.962 (+0.038) | 0.952 (+0.082) | 0.941 (+0.080) | 0.950 (+0.080) | 0.957 (+0.065) | 1.000 (+1.000) | 0.882 (+0.118) | 0.698 (-0.073) | 0.978 | 0.939 | 0.917 | 6 |
| production (service default configuration) | 0.859 (+0.103) | 0.962 (+0.038) | 0.952 (+0.082) | 0.942 (+0.081) | 0.951 (+0.081) | 0.957 (+0.065) | 1.000 (+1.000) | 0.882 (+0.118) | 1.000 (+0.229) | 0.978 | 0.939 | 0.917 | 7 |

hit@3 by category, baseline vs. production:

| category | baseline | production |
|---|---|---|
| adversarial | 1.000 | 1.000 |
| category | 1.000 | 1.000 |
| comparison | 1.000 | 1.000 |
| direct | 1.000 | 1.000 |
| multi_hop | 1.000 | 1.000 |
| negation | 0.667 | 1.000 |
| paraphrase | 0.789 | 0.842 |
| price | 1.000 | 1.000 |
| rating | 1.000 | 1.000 |
| sorting | 1.000 | 1.000 |
| typo | 1.000 | 1.000 |
<!-- rageval:end -->

## Reading the results

**What really helped**

- **Synonym expansion** is the biggest single retrieval lever: MRR 0.870 to 0.913 and hit@1 from 0.756 to 0.808. It resolves paraphrases where the query and the document share no word ("something to listen to music" for the headphones). Running it always beat running it only when the first search is weak (adaptive mode, MRR 0.901), with no extra abstention cost; "always" mode also does a single search instead of two.
- **Negation** closes an entire class of errors: the baseline returns the product the user asked to exclude in every negation case (negation 0.000), while the negation variant never does (1.000).
- **Intent routing** does not change the ranking, but makes out-of-scope questions end with no tool and no context: abstention from 0.765 to 0.882.
- **Typo correction** yields little here (+0.013 in hit@1) because the catalog is small and almost every typo lands in a sentence with other correct words. The math changes on larger catalogs, but that was not measured.
- **Parent-document** does not change the ranking by construction: it swaps the retrieved passage for the product's whole document. The effect shows up in "ctx with price": with 150-character chunks only 24% of the delivered passages carry the price; with parent-document, 100%. It is the classic combination: small chunks to find, large context to answer.

**What did not help (and stays off or optional)**

- **HyDE** (hypothetical document): with the template-based generator, MRR goes from 0.870 to 0.885 in isolation, but combined with expansion it loses (0.942 vs. 0.952) and costs one extra generation with a real LLM. Abstention goes up (0.941) because the hypothetical document pushes unrelated queries away. It stays implemented and off by default (`RETRIEVAL_HYDE=false`).
- **MMR**: neutral (MRR 0.872 with lambda 0.7; 0.870 with 0.4). Retrieval already returns one chunk per product, so there is no redundancy to reduce in this catalog. In a catalog with many near-identical products it should pay off; here it does not.
- **Fusion weights**: 1.0/1.0 was the best. Weighting the vector branch (1.5/0.5) hurts hit@3 and MRR; weighting the text branch (0.5/1.5) hurts slightly. With the lexical embedder the two branches already agree a lot.
- **Decomposition** barely shows up in hit@k (MRR +0.006) because the OR search already brings both products of a compound question. It exists for questions with different filters in each half ("headphones up to R$ 400 and a backpack up to R$ 350"), which the baseline cannot separate.

**Pre-filter vs. post-filter.** On the 24-product catalog the two tie, because each search branch already returns almost everything. The test `test_prefilter_returns_full_results_where_postfilter_starves` creates 200 clones of the headphones with spread-out prices and asks "fone bluetooth até 100 reais" (bluetooth headphones up to 100 reais) with 20-candidate branches: the pre-filter returns 4 products within the price; the post-filter returns **0**, because the top 20 candidates of each branch are almost never under the cap. Filtering before the vector search is what preserves recall as the catalog grows.

**Production.** The service default is what survived measurement: "always" expansion, typo correction, negation, decomposition, parent-document, and intent routing; HyDE and MMR off. Against the baseline, on the retrieval set: hit@1 0.756 to 0.859, hit@3 0.923 to 0.962, MRR 0.870 to 0.952, nDCG@5 0.861 to 0.942, context precision 0.870 to 0.951, context recall 0.892 to 0.957. On the holdout: hit@3 0.909 to 0.939 and MRR 0.783 to 0.917.

## End-to-end evaluation

Full pipeline (agent, generation, grounding guard, heuristic judge), 111 cases, `python -m assistant.evals --offline`:

| metric | original (36 cases) | current (111 cases) |
|---|---|---|
| hit@3 | 0.893 | 0.965 |
| MRR | 0.893 | 0.956 |
| nDCG@5 | n/a | 0.946 |
| context precision | n/a | 0.955 |
| context recall | n/a | 0.961 |
| negation | n/a | 1.000 |
| faithfulness (judge) | n/a | 1.000 |
| answer relevancy (judge) | n/a | 0.686 |
| groundedness | 1.000 | 1.000 |
| tool accuracy | 1.000 | 1.000 |
| answer pass | 1.000 | 0.991 |

By split: dev hit@3 0.980; holdout hit@3 0.943. In the "original" column the 36 old cases ran on the old pipeline; on those same 36 cases the current pipeline has hit@3 and MRR of 0.964. The "n/a" metrics did not exist. The `answer relevancy` of 0.686 reflects a lexical heuristic judge: it underrates correct answers that recommend the product without repeating the words of the question. Use it to detect drops, not as an absolute grade.

Cases that still fail (all known): `parafrase-exercitar-em-casa`, `p-chuva`, and `p-cheiro` (paraphrases with no overlap that even the lexicon does not cover; they need semantic embeddings) and `a-produto-inexistente` (a product the catalog does not sell, but whose neighboring word triggers the expansion).

## Semantic cache

`python -m assistant.cachebench` replays the 107 history-free questions of the golden set in four passes, with the cache on (similarity threshold 0.92). Stock and order questions never enter the cache (live data), so 22 are "skipped".

| pass | queries | hits | misses | skipped | hit rate | tokens saved |
|---|---|---|---|---|---|---|
| 1. first time | 107 | 0 | 85 | 22 | 0.000 | 0 |
| 2. same question | 107 | 85 | 0 | 22 | 1.000 | 45852 |
| 3. uppercase and punctuation | 107 | 85 | 0 | 22 | 1.000 | 45852 |
| 4. with courtesy words | 107 | 85 | 0 | 22 | 1.000 | 45852 |

Total: hit rate 0.750, 137556 tokens and US$ 0.0688 saved (reference price).

Pass 4 (with "por favor" and "obrigado", i.e. "please" and "thank you") only hits because those words are on the stop-word list: without that, its hit rate was 1.2%, a lesson that the cache depends on the same text cleanup as the embedder. Tokens saved use the four-characters-per-token estimate and the reference price (US$ 0.0005 per thousand input tokens), because the mock model is not billed.

## Limitations

- The embedder is lexical. Paraphrases with no shared word are only resolved by the synonym lexicon, which is handwritten and knows the catalog. With real semantic embeddings (Ollama, `nomic-embed-text`) the rewrite-technique numbers change, and HyDE tends to be worth more.
- 24 products is small: MMR, pre-filter, and typo correction are the techniques most penalized by it.
- The holdout was written by the same author as the lexicon. The judge is heuristic. No number here was measured with a real LLM.
