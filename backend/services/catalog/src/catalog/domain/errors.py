class DomainError(Exception):
    pass


class InvalidQuery(DomainError):
    pass


class ProductNotFound(DomainError):
    pass


class NotProductOwner(DomainError):
    pass


class DuplicateSlug(DomainError):
    pass


class InvalidProduct(DomainError):
    pass
