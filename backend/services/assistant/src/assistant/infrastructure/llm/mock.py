import re
from collections.abc import AsyncIterator

from assistant.application.ports import ContextItem, Prompt
from assistant.domain.models import Observation
from assistant.domain.text import content_tokens, format_brl, normalize

_METADATA_SENTENCE = re.compile(r"^(Preço|Avaliação|Vendido por|Palavras-chave)")
_SENTENCES = re.compile(r"[^\n]+?[.!?]+(?=\s|$)")
_STATUS_PT = {"PENDING": "aguardando pagamento", "PAID": "pago", "CANCELLED": "cancelado"}

NOT_FOUND = (
    "Não encontrei no catálogo nada que corresponda a isso. "
    "Tente descrever o tipo de produto, a categoria ou uma faixa de preço."
)


def _has(text: str, *needles: str) -> bool:
    return any(n in text for n in needles)


class MockLlm:
    """Deterministic stand-in for a language model. It writes the answer only from the
    structured context and tool observations it receives, so it cannot invent facts."""

    name = "mock"

    async def generate(self, prompt: Prompt) -> str:
        question = normalize(prompt.question)
        orders = [o for o in prompt.observations if o.tool == "get_order_status"]
        stocks = [o for o in prompt.observations if o.tool == "get_stock"]
        if orders:
            return self._order_answer(orders[-1])
        if stocks:
            return self._stock_answer(stocks[-1], prompt.context)
        if not prompt.context:
            return self._not_found(question, prompt.observations)
        items = list(prompt.context)
        if _has(question, "mais barato", "menor preco", "mais em conta", "mais baratinho"):
            return self._cheapest(items)
        if _has(
            question,
            "mais bem avaliado",
            "melhor avaliado",
            "melhor avaliacao",
            "melhor nota",
            "maior nota",
            "mais bem avaliada",
            "melhor avaliada",
        ):
            return self._best_rated(items)
        if _has(question, "compar", "diferenca", "versus", " vs "):
            return self._compare(items, question)
        return self._recommend(items)

    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        for token in re.findall(r"\S+\s*", await self.generate(prompt)):
            yield token

    @staticmethod
    def _not_found(question: str, observations: tuple[Observation, ...]) -> str:
        if "pedido" in question:
            return "Para consultar um pedido, me envie o código completo do pedido."
        for obs in observations:
            max_price: int | None = (obs.data.get("filters") or {}).get("max_price_cents")
            if max_price:
                return (
                    f"Não encontrei produtos com preço de até {format_brl(max_price)}. "
                    "Que tal ampliar a faixa de preço?"
                )
        return NOT_FOUND

    @staticmethod
    def _order_answer(obs: Observation) -> str:
        if not obs.ok:
            return obs.summary
        data = obs.data
        status = _STATUS_PT.get(str(data.get("status")), str(data.get("status")).lower())
        short = str(data.get("order_id", ""))[:8]
        items = int(data.get("items_count", 0))
        noun = "item" if items == 1 else "itens"
        text = (
            f"O pedido {short} está {status}. Total de {format_brl(int(data['total_cents']))} "
            f"com {items} {noun}."
        )
        if data.get("cancel_reason"):
            text += f" Motivo do cancelamento: {data['cancel_reason']}."
        return text

    @staticmethod
    def _stock_answer(obs: Observation, context: tuple[ContextItem, ...]) -> str:
        if not obs.ok:
            return obs.summary
        data = obs.data
        name = str(data["name"])
        available = int(data["available"])
        cite = next(
            (f" [{i.index}]" for i in context if str(i.passage.product_id) == data["product_id"]),
            "",
        )
        if available <= 0:
            return f"{name} está sem estoque no momento{cite}."
        if available <= 5:
            return f"Restam apenas {available} unidades de {name}{cite}. Vale garantir logo."
        return f"Temos {available} unidades de {name} em estoque{cite}."

    @staticmethod
    def _snippet(item: ContextItem) -> str:
        body = item.passage.content.split("\n", 1)[-1]
        for raw in _SENTENCES.findall(body):
            sentence = str(raw).strip()
            if not _METADATA_SENTENCE.match(sentence):
                return sentence
        return ""

    def _cheapest(self, items: list[ContextItem]) -> str:
        best = min(items, key=lambda i: (i.passage.price_cents, i.index))
        p = best.passage
        return (
            f"Entre as opções encontradas, o mais barato é {p.name}, por "
            f"{format_brl(p.price_cents)} [{best.index}]."
        )

    def _best_rated(self, items: list[ContextItem]) -> str:
        best = max(items, key=lambda i: (i.passage.rating, -i.index))
        p = best.passage
        return (
            f"Entre as opções encontradas, o mais bem avaliado é {p.name}, com nota "
            f"{p.rating:.1f} de 5, por {format_brl(p.price_cents)} [{best.index}]."
        )

    def _compare(self, items: list[ContextItem], question: str) -> str:
        asked = set(content_tokens(question))
        ranked = sorted(
            items,
            key=lambda i: (-len(asked & set(content_tokens(i.passage.name))), i.index),
        )
        pair = ranked[:2]
        if len(pair) < 2:
            return self._recommend(items)
        a, b = pair
        cheaper = a if a.passage.price_cents <= b.passage.price_cents else b
        better = a if a.passage.rating >= b.passage.rating else b
        lines = [
            f"- {i.passage.name}: {format_brl(i.passage.price_cents)}, nota "
            f"{i.passage.rating:.1f} de 5 [{i.index}]"
            for i in (a, b)
        ]
        verdict = f"O mais barato é {cheaper.passage.name} [{cheaper.index}]"
        if better is cheaper:
            verdict += " e também é o mais bem avaliado."
        else:
            verdict += f", e o mais bem avaliado é {better.passage.name} [{better.index}]."
        return "Comparando as duas opções:\n" + "\n".join(lines) + "\n" + verdict

    def _recommend(self, items: list[ContextItem]) -> str:
        noun = "opção" if len(items) == 1 else "opções"
        lines = [f"Encontrei {len(items)} {noun} no catálogo:"]
        for i in items:
            p = i.passage
            lines.append(
                f"- {p.name} por {format_brl(p.price_cents)}, nota {p.rating:.1f} de 5 [{i.index}]"
            )
        snippet = self._snippet(items[0])
        if snippet:
            lines.append(f"Sobre {items[0].passage.name}: {snippet} [{items[0].index}]")
        return "\n".join(lines)
