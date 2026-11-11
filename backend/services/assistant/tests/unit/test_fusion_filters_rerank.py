import pytest

from assistant.application.rerank import LexicalReranker
from assistant.domain.filters import FilterParser
from assistant.domain.fusion import reciprocal_rank_fusion
from tests.helpers import passage

CATEGORIES = {
    "tecnologia": "Tecnologia",
    "casa": "Casa e decoração",
    "esporte": "Esporte e aventura",
}


def test_rrf_scores_follow_the_formula() -> None:
    fused = dict(reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=60))
    assert fused["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_rewards_agreement_between_rankings() -> None:
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "c"]])
    ids = [item for item, _ in fused]
    assert ids[0] == "b"
    assert set(ids) == {"a", "b", "c"}


def test_rrf_item_in_one_list_only_still_appears() -> None:
    fused = reciprocal_rank_fusion([["a"], []])
    assert fused == [("a", pytest.approx(1 / 61))]


def test_rrf_ties_keep_first_seen_order() -> None:
    fused = reciprocal_rank_fusion([["x"], ["y"]])
    assert [i for i, _ in fused] == ["x", "y"]


@pytest.mark.parametrize(
    ("question", "cents"),
    [
        ("até R$ 300", 30000),
        ("algo ate 300 reais", 30000),
        ("menos de 200", 20000),
        ("abaixo de 150", 15000),
        ("no máximo R$ 99,90", 9990),
        ("até R$ 1.299,00", 129900),
        ("até 1.200", 120000),
    ],
)
def test_parse_max_price(question: str, cents: int) -> None:
    parsed = FilterParser(CATEGORIES).parse(question)
    assert parsed.filters.max_price_cents == cents


def test_parse_min_price_and_residual_text() -> None:
    parsed = FilterParser(CATEGORIES).parse("quero um fone acima de R$ 200")
    assert parsed.filters.min_price_cents == 20000
    assert parsed.filters.max_price_cents is None
    assert "200" not in parsed.text
    assert "fone" in parsed.text


def test_parse_category_by_slug_label_word_and_plural() -> None:
    parser = FilterParser(CATEGORIES)
    assert parser.parse("coisas de tecnologia").filters.category == "tecnologia"
    assert parser.parse("itens de decoração").filters.category == "casa"
    assert parser.parse("equipamentos de esportes").filters.category == "esporte"
    assert parser.parse("algo de aventura").filters.category == "esporte"


def test_parse_without_filters() -> None:
    parsed = FilterParser(CATEGORIES).parse("quero um fone com cancelamento de ruído")
    assert parsed.filters.is_empty
    assert parsed.sort is None


def test_parse_removes_category_word_from_residual() -> None:
    parsed = FilterParser(CATEGORIES).parse("o mais barato de esporte")
    assert parsed.filters.category == "esporte"
    assert parsed.sort == "price_asc"
    assert "esporte" not in parsed.text


def test_parse_sort_by_rating() -> None:
    assert FilterParser(CATEGORIES).parse("qual o mais bem avaliado?").sort == "rating_desc"
    assert FilterParser(CATEGORIES).parse("a melhor avaliação").sort == "rating_desc"


def test_reranker_prefers_the_passage_that_covers_the_question() -> None:
    weak = passage("a", "Mouse Glide", content="Produto: Mouse Glide\nMouse sem fio silencioso.")
    strong = passage(
        "b",
        "Fone Nova ANC",
        content="Produto: Fone Nova ANC\nCancelamento ativo de ruído e bateria longa.",
    )
    ranked = LexicalReranker().rerank("fone com cancelamento de ruído", [weak, strong], 2)
    assert ranked[0].slug == "b"
    assert ranked[0].score > ranked[1].score


def test_reranker_scores_zero_without_overlap_and_limits_output() -> None:
    items = [passage(f"p{i}", f"Produto {i}") for i in range(6)]
    ranked = LexicalReranker().rerank("capital da frança", items, 4)
    assert all(p.score == 0.0 for p in ranked)
    assert len(LexicalReranker().rerank("produto um bom", items, 4)) <= 4


def test_reranker_with_empty_query_returns_nothing() -> None:
    assert LexicalReranker().rerank("de a o", [passage()], 4) == []
