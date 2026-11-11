from prometheus_client import Counter

PAYMENTS_CONFIRMED = Counter(
    "marketplace_payments_confirmed_total", "Payments confirmed after PSP verification"
)

PSP_CANCEL_REFUSED = Counter(
    "marketplace_payments_expiry_psp_refused_total",
    "Expired charges the PSP refused to cancel (they may have been paid)",
)
