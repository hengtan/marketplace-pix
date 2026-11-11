from assistant.domain.models import AgentOutcome, Citation
from assistant.domain.text import format_brl

DEGRADED_WARNING = (
    "O modelo de resposta está indisponível agora; mostrando só os resultados da busca."
)
SEARCH_UNAVAILABLE = "Não consegui consultar o catálogo agora. Tente novamente em instantes."
UNAVAILABLE = (
    "Não consegui gerar a resposta agora e a busca não trouxe resultados. "
    "Tente novamente em instantes."
)


def build_fallback(outcome: AgentOutcome) -> tuple[str, list[Citation]]:
    """Answer made only from data the agent already collected, with no model involved: the
    products found by the search (with prices from the catalog) or the tool observations."""
    lines: list[str] = []
    citations: list[Citation] = []
    for index, passage in enumerate(outcome.passages, start=1):
        lines.append(
            f"- {passage.name} por {format_brl(passage.price_cents)}, "
            f"nota {passage.rating:.1f} de 5 [{index}]"
        )
        citations.append(Citation(passage.product_id, passage.slug, passage.name, passage.score))
    facts = [o.summary for o in outcome.observations if o.tool != "search_products" and o.ok]
    if not lines and not facts:
        return UNAVAILABLE, []
    head = "Não consegui gerar a resposta completa agora, mas estes são os resultados da busca:"
    body = "\n".join(lines + [f"- {fact}" for fact in facts])
    return f"{head}\n{body}", citations
