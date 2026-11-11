class DomainError(Exception):
    pass


class InvalidMoney(DomainError):
    pass


class InvalidPayment(DomainError):
    pass


class InvalidStateTransition(DomainError):
    pass
