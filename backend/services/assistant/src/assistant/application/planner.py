import re
from collections.abc import Sequence
from uuid import UUID

from assistant.application.ports import Action
from assistant.domain.models import Observation, Turn
from assistant.domain.text import STOPWORDS, tokenize

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
STOCK_WORDS = frozenset(
    {
        "estoque",
        "disponivel",
        "disponiveis",
        "disponibilidade",
        "unidades",
        "unidade",
        "quantas",
        "quantos",
        "restam",
        "sobrando",
        "falta",
    }
)
_SINGULAR_REFERENCE = frozenset(
    {"esse", "essa", "desse", "dessa", "deste", "desta", "este", "esta", "dele", "dela", "aquele"}
)
_PLURAL_REFERENCE = frozenset(
    {"deles", "delas", "desses", "dessas", "destes", "destas", "esses", "essas"}
)


class RuleBasedPlanner:
    """Chooses the next tool from the user's intent. Deterministic stand-in for an LLM that
    would pick tools through function calling; the loop around it does not change."""

    async def next_action(
        self,
        message: str,
        history: Sequence[Turn],
        observations: Sequence[Observation],
        intent: str | None = None,
    ) -> Action | None:
        tokens = set(tokenize(message))
        done = {obs.tool for obs in observations}

        if intent == "out_of_scope":
            return None
        if intent == "policy":
            if "get_policy" in done:
                return None
            return Action("get_policy", {"question": message})

        order = _UUID.search(message)
        if order:
            if "get_order_status" in done:
                return None
            return Action("get_order_status", {"order_id": str(UUID(order.group(0)))})

        if intent == "order":
            return None

        remembered = last_products(history)
        if tokens & STOCK_WORDS:
            return self._stock_step(message, tokens, observations, remembered, done)

        if "search_products" in done or _asks_for_order(tokens):
            return None
        arguments: dict[str, object] = {"query": message}
        if remembered and tokens & _PLURAL_REFERENCE:
            arguments["product_ids"] = [str(p) for p in remembered]
        elif remembered and tokens & _SINGULAR_REFERENCE:
            arguments["product_ids"] = [str(remembered[0])]
        return Action("search_products", arguments)

    @staticmethod
    def _stock_step(
        message: str,
        tokens: set[str],
        observations: Sequence[Observation],
        remembered: Sequence[UUID],
        done: set[str],
    ) -> Action | None:
        if "get_stock" in done:
            return None
        searched = next((o for o in reversed(observations) if o.tool == "search_products"), None)
        if searched is not None:
            products = searched.data.get("products") or []
            if not products:
                return None
            top = products[0]
            return Action("get_stock", {"product_id": top["product_id"], "name": top["name"]})
        if remembered and tokens & (_SINGULAR_REFERENCE | _PLURAL_REFERENCE):
            return Action("get_stock", {"product_id": str(remembered[0])})
        words = [
            t
            for t in tokenize(message)
            if t not in STOCK_WORDS and (t not in STOPWORDS or t == "mais")
        ]
        return Action("search_products", {"query": " ".join(words) or message})


def _asks_for_order(tokens: set[str]) -> bool:
    return "pedido" in tokens or "pedidos" in tokens


def last_products(history: Sequence[Turn]) -> list[UUID]:
    for turn in reversed(history):
        if turn.role == "assistant" and turn.product_ids:
            return list(turn.product_ids)
    return []
