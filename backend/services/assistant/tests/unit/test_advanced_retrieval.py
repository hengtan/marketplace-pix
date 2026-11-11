import pytest

from assistant.application.rerank import LexicalReranker
from assistant.application.retrieval import HybridRetriever, RetrievalConfig
from assistant.domain.chunking import RecursiveChunker
from assistant.domain.diversity import cosine, mmr_select
from assistant.domain.filters import FilterParser
from assistant.domain.fusion import reciprocal_rank_fusion
from assistant.domain.models import Filters
from tests.helpers import pid
from tests.memory_store import build_store


def test_weighted_rrf_prefers_the_heavier_ranking() -> None:
    rankings = [["a", "b"], ["b", "a"]]
    assert reciprocal_rank_fusion(rankings, weights=[2.0, 1.0])[0][0] == "a"
    assert reciprocal_rank_fusion(rankings, weights=[1.0, 2.0])[0][0] == "b"
    with pytest.raises(ValueError):
        reciprocal_rank_fusion(rankings, weights=[1.0])


def test_mmr_trades_relevance_for_diversity() -> None:
    vectors = {"a": [1.0, 0.0], "b": [0.99, 0.1], "c": [0.0, 1.0]}
    relevance = {"a": 1.0, "b": 0.95, "c": 0.6}
    assert mmr_select(relevance, vectors, 2, lambda_=1.0) == ["a", "b"]
    assert mmr_select(relevance, vectors, 2, lambda_=0.5) == ["a", "c"]
    assert mmr_select(relevance, vectors, 5, lambda_=0.7)[0] == "a"
    with pytest.raises(ValueError):
        mmr_select(relevance, vectors, 2, lambda_=1.5)
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


async def test_mmr_changes_the_selection_but_keeps_the_best_hit() -> None:
    store, embedder = await build_store()
    plain = HybridRetriever(store, embedder, LexicalReranker())
    diverse = HybridRetriever(
        store, embedder, LexicalReranker(), RetrievalConfig(mmr=True, mmr_lambda=0.3)
    )
    question = "fone bluetooth sem fio para ouvir audio com bateria"
    base = await plain.retrieve(question)
    spread = await diverse.retrieve(question)
    assert spread.passages[0].slug == base.passages[0].slug
    assert {p.slug for p in spread.passages} <= {p.slug for p in base.candidates}


async def test_parent_document_returns_the_whole_product_text() -> None:
    store, embedder = await build_store(chunker=RecursiveChunker(120, 20))
    child = HybridRetriever(store, embedder, LexicalReranker())
    parent = HybridRetriever(
        store, embedder, LexicalReranker(), RetrievalConfig(parent_documents=True)
    )
    question = "teclado mecanico switches"
    small = (await child.retrieve(question)).passages[0]
    full = (await parent.retrieve(question)).passages[0]
    assert small.product_id == full.product_id
    assert len(full.content) > len(small.content)
    assert full.content.startswith("Produto: Teclado Mecânico Forge 75%")
    assert "Preço:" in full.content and "Avaliação:" in full.content


async def test_prefilter_keeps_recall_that_postfilter_loses() -> None:
    store, embedder = await build_store()
    question = "fone bluetooth teclado mouse carregador caixa de som ate 150 reais"
    pre = await HybridRetriever(
        store, embedder, LexicalReranker(), RetrievalConfig(branch_limit=3)
    ).retrieve(question)
    post = await HybridRetriever(
        store, embedder, LexicalReranker(), RetrievalConfig(branch_limit=3, prefilter=False)
    ).retrieve(question)
    assert all(p.price_cents <= 15000 for p in pre.passages)
    assert all(p.price_cents <= 15000 for p in post.passages)
    assert len(pre.passages) >= len(post.passages)


async def test_restricted_search_with_only_shopping_words_browses_remembered_products() -> None:
    store, embedder = await build_store()
    retriever = HybridRetriever(store, embedder, LexicalReranker())
    restrict = Filters(product_ids=(pid("x"),))
    assert (await retriever.retrieve("quanto custa esse?", restrict)).passages == []
    tapete = next(
        c.draft.product_id
        for c in store.chunks.values()
        if c.draft.metadata["slug"] == "tapete-yoga-grip"
    )
    found = await retriever.retrieve("quanto custa esse?", Filters(product_ids=(tapete,)))
    assert [p.slug for p in found.passages] == ["tapete-yoga-grip"]


@pytest.mark.parametrize(
    ("question", "rating"),
    [
        ("casa com nota acima de 4,8", 4.8),
        ("esporte com 4.5 estrelas ou mais", 4.5),
        ("produtos com avaliacao minima de 4,6", 4.6),
        ("acima de 4 estrelas", 4.0),
    ],
)
def test_rating_filter_is_parsed_before_price(question: str, rating: float) -> None:
    parsed = FilterParser({"casa": "Casa", "esporte": "Esporte"}).parse(question)
    assert parsed.filters.min_rating == rating
    assert parsed.filters.min_price_cents is None


def test_filters_matches_every_condition() -> None:
    f = Filters(max_price_cents=100, min_rating=4.0, category="casa")
    assert f.matches(90, "casa", 4.5, pid("a"))
    assert not f.matches(101, "casa", 4.5, pid("a"))
    assert not f.matches(90, "casa", 3.9, pid("a"))
    assert not f.matches(90, "esporte", 4.5, pid("a"))
    assert not f.is_empty and Filters().is_empty


async def test_chunker_variants_change_the_chunk_count() -> None:
    small, _ = await build_store(chunker=RecursiveChunker(120, 20))
    large, _ = await build_store(chunker=RecursiveChunker(300, 60))
    assert len(small.chunks) > len(large.chunks)
