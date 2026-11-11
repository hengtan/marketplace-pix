class DomainError(Exception):
    pass


class InvalidContact(DomainError):
    pass


class InvalidMoney(DomainError):
    pass
