import pytest

from assistant.domain.chunking import RecursiveChunker
from assistant.domain.text import content_tokens, format_brl, normalize, stem, tokenize

SENTENCES = (
    "Primeira frase do produto com alguns detalhes. "
    "Segunda frase explica o uso diário. "
    "Terceira frase fala da bateria que dura muito. "
    "Quarta frase cita a garantia e o suporte. "
    "Quinta frase encerra a descrição."
)


def test_normalize_removes_accents_and_case() -> None:
    assert normalize("Relógio Çafé ÁÉÍÓÚ") == "relogio cafe aeiou"


def test_tokenize_and_content_tokens_drop_stopwords() -> None:
    assert tokenize("Quero um fone, com ruído!") == ["quero", "um", "fone", "com", "ruido"]
    assert content_tokens("Quero um fone com cancelamento de ruído") == [
        "fone",
        "cancelamento",
        "ruido",
    ]


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("correr", "corrida"),
        ("fone", "fones"),
        ("decorar", "decoracao"),
        ("luminaria", "luminarias"),
    ],
)
def test_stem_connects_related_words(left: str, right: str) -> None:
    assert stem(left) == stem(right)


def test_stem_keeps_unrelated_words_apart() -> None:
    assert stem("franca") != stem("francesa")
    assert stem("capital") != stem("capacidade")


@pytest.mark.parametrize(
    ("cents", "expected"),
    [(34990, "R$ 349,90"), (5, "R$ 0,05"), (129900, "R$ 1.299,00"), (100000000, "R$ 1.000.000,00")],
)
def test_format_brl(cents: int, expected: str) -> None:
    assert format_brl(cents) == expected


def test_chunks_respect_size() -> None:
    chunks = RecursiveChunker(size=100, overlap=30).split(SENTENCES)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


def test_chunks_overlap_repeats_the_tail_of_previous_chunk() -> None:
    chunks = RecursiveChunker(size=110, overlap=50).split(SENTENCES)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        shared = [s for s in previous.split(". ") if s and s in current]
        assert shared, "next chunk should start with the last sentence of the previous one"


def test_zero_overlap_does_not_repeat_sentences() -> None:
    chunks = RecursiveChunker(size=100, overlap=0).split(SENTENCES)
    joined = " ".join(chunks)
    assert joined.count("Segunda frase") == 1


def test_short_text_is_a_single_chunk() -> None:
    assert RecursiveChunker(size=300, overlap=60).split("Texto curto.") == ["Texto curto."]


def test_empty_text_has_no_chunks() -> None:
    assert RecursiveChunker(size=300, overlap=60).split("  \n ") == []


def test_long_sentence_is_split_by_words() -> None:
    text = " ".join(["palavra"] * 60)
    chunks = RecursiveChunker(size=80, overlap=10).split(text)
    assert len(chunks) > 1
    assert all(len(c) <= 80 for c in chunks)


def test_invalid_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        RecursiveChunker(size=100, overlap=80)
    with pytest.raises(ValueError):
        RecursiveChunker(size=5, overlap=0)
