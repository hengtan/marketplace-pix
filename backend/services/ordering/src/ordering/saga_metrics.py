from prometheus_client import Counter

SAGA_TIMEOUTS = Counter(
    "marketplace_saga_timeouts_total", "Orders cancelled by the saga timeout process manager"
)
SAGA_LATE_PAYMENTS = Counter(
    "marketplace_saga_late_payments_total",
    "Payments confirmed after the order was cancelled (refund requested)",
)
