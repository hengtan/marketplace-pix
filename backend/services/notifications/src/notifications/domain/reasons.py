from __future__ import annotations

REASON_TRANSLATIONS: dict[str, str] = {
    "out of stock": "estoque insuficiente",
    "payment expired": "o PIX expirou",
    "payment cancelled": "o pagamento foi cancelado",
    "saga timeout": "o pagamento não foi confirmado a tempo",
}

DEFAULT_REASON = "um imprevisto no processamento do pedido"


def translate_reason(reason: str | None) -> str:
    if reason is None or not reason.strip():
        return DEFAULT_REASON
    return REASON_TRANSLATIONS.get(reason.strip().lower(), DEFAULT_REASON)
