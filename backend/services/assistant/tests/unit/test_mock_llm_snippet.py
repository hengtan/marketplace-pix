from uuid import uuid4

from assistant.application.ports import ContextItem
from assistant.domain.models import Passage
from assistant.infrastructure.llm.mock import MockLlm


def item(content: str) -> ContextItem:
    passage = Passage(
        chunk_id="c1",
        product_id=uuid4(),
        slug="fone-bluetooth-nova",
        name="Fone Bluetooth Nova ANC",
        category="Tecnologia",
        price_cents=34990,
        rating=4.7,
        content=content,
    )
    return ContextItem(index=1, passage=passage)


HEADER = "Produto: Fone Bluetooth Nova ANC | Categoria: Tecnologia\n"


def test_decimal_numbers_do_not_split_a_sentence():
    content = HEADER + "Tela de 6.5 polegadas com brilho de 1.200 nits. Bateria para o dia todo."

    assert MockLlm._snippet(item(content)) == "Tela de 6.5 polegadas com brilho de 1.200 nits."


def test_metadata_only_chunk_gives_no_snippet_instead_of_a_broken_fragment():
    content = (
        HEADER
        + "Preço: R$ 349,90. Avaliação: 4.7 de 5 em 1284 avaliações. Vendido por Aurora Tech. "
        + "Palavras-chave: fone, bluetooth."
    )

    assert MockLlm._snippet(item(content)) == ""


def test_first_real_sentence_is_returned_after_the_metadata():
    content = HEADER + "Preço: R$ 349,90. Cancelamento ativo de ruído no metrô."

    assert MockLlm._snippet(item(content)) == "Cancelamento ativo de ruído no metrô."
