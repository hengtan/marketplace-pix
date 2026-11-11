from prometheus_client import Counter

PAYMENTS_CONFIRMED = Counter(
    "marketplace_payments_confirmed_total", "Payments confirmed after PSP verification"
)
