from prometheus_client import Counter

ORDERS_CREATED = Counter("marketplace_orders_created_total", "Orders accepted by the API")
