class DomainError(Exception):
    pass


class InvalidQuery(DomainError):
    pass


class ProductNotFound(DomainError):
    pass
