import math

from assistant.infrastructure.embedders.hashing import HashingEmbedder


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_dimension_and_name() -> None:
    embedder = HashingEmbedder(256)
    assert embedder.dimension == 256
    assert embedder.name == "hashing-256"
    assert len(embedder.embed_one("fone bluetooth")) == 256


def test_is_deterministic_across_instances() -> None:
    assert HashingEmbedder(256).embed_one("fone bluetooth") == HashingEmbedder(256).embed_one(
        "fone bluetooth"
    )


def test_vector_is_l2_normalized() -> None:
    vector = HashingEmbedder(256).embed_one("cafeteira de prensa francesa")
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-9)


def test_ignores_accents_and_case() -> None:
    embedder = HashingEmbedder(256)
    assert embedder.embed_one("Relógio CAFÉ") == embedder.embed_one("relogio cafe")


def test_empty_text_gives_zero_vector() -> None:
    assert not any(HashingEmbedder(64).embed_one("de a o"))


def test_similar_texts_score_higher_than_unrelated_ones() -> None:
    embedder = HashingEmbedder(256)
    query = embedder.embed_one("fone bluetooth com cancelamento de ruído")
    related = embedder.embed_one("Fone Bluetooth Nova ANC cancelamento ativo de ruído")
    unrelated = embedder.embed_one("Jogo de facas chef em aço inoxidável")
    assert cosine(query, related) > 0.4
    assert cosine(query, related) > cosine(query, unrelated) + 0.3


def test_word_order_matters_a_little_through_bigrams() -> None:
    embedder = HashingEmbedder(512)
    base = embedder.embed_one("caixa de som potente")
    same_order = embedder.embed_one("caixa som potente")
    shuffled = embedder.embed_one("potente som caixa")
    assert cosine(base, same_order) > cosine(base, shuffled)


async def test_embed_batch_matches_single() -> None:
    embedder = HashingEmbedder(128)
    batch = await embedder.embed(["fone", "mochila"])
    assert batch[0] == embedder.embed_one("fone")
    assert batch[1] == embedder.embed_one("mochila")
