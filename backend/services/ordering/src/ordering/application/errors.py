class ApplicationError(Exception):
    pass


class IdempotencyKeyReused(ApplicationError):
    pass


class OrderNotFound(ApplicationError):
    pass


class UnknownProduct(ApplicationError):
    pass


class CatalogUnavailable(ApplicationError):
    pass
