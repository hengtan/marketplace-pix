class ApplicationError(Exception):
    pass


class IdempotencyKeyReused(ApplicationError):
    pass


class OrderNotFound(ApplicationError):
    pass
