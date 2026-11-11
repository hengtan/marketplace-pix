from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyEntry:
    topic: str
    triggers: frozenset[str]
    text: str


POLICIES: tuple[PolicyEntry, ...] = (
    PolicyEntry(
        "pix",
        frozenset({"pix", "pagamento", "pagar", "qr", "copia", "cola", "expira", "expirou"}),
        "O pagamento é feito por PIX. O código de cobrança tem prazo de validade: se o PIX "
        "expirar sem pagamento, o pedido é cancelado e o estoque reservado volta para a venda.",
    ),
    PolicyEntry(
        "troca",
        frozenset(
            {"troca", "trocar", "devolucao", "devolver", "reembolso", "estorno", "arrependimento"}
        ),
        "Você pode desistir da compra em até 7 dias corridos após o recebimento (direito de "
        "arrependimento do Código de Defesa do Consumidor). O valor é devolvido pelo mesmo meio "
        "de pagamento.",
    ),
    PolicyEntry(
        "entrega",
        frozenset({"frete", "entrega", "prazo", "envio", "enviar", "transportadora", "rastreio"}),
        "O prazo e o valor do frete dependem do lojista e são mostrados no fechamento do pedido. "
        "Para acompanhar uma compra já feita, informe o código do pedido.",
    ),
    PolicyEntry(
        "cancelamento",
        frozenset({"cancelar", "desistir"}),
        "Pedidos aguardando pagamento são cancelados automaticamente quando o PIX expira. "
        "Depois de pago, o cancelamento segue a regra de arrependimento de 7 dias.",
    ),
    PolicyEntry(
        "garantia",
        frozenset({"garantia", "defeito", "assistencia", "quebrou", "conserto"}),
        "Todo produto tem garantia legal de 90 dias contra defeitos (Código de Defesa do "
        "Consumidor). Garantias maiores, quando existirem, são informadas pelo lojista.",
    ),
)
POLICY_TRIGGERS = frozenset().union(*(p.triggers for p in POLICIES))
WEAK_POLICY_TRIGGERS = frozenset(
    {"prazo", "entrega", "envio", "enviar", "pagamento", "pagar", "qr", "copia", "cola", "defeito"}
)
