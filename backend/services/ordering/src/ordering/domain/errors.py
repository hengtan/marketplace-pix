class DomainError(Exception):
    pass


class InvalidMoney(DomainError):
    pass


class InvalidOrder(DomainError):
    pass


class InvalidStateTransition(DomainError):
    pass
