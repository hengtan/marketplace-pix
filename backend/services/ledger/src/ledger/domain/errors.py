class DomainError(Exception):
    pass


class InvalidMoney(DomainError):
    pass


class InvalidAccount(DomainError):
    pass


class UnbalancedTransaction(DomainError):
    pass


class InvalidTransaction(DomainError):
    pass


class InvalidOrderProjection(DomainError):
    pass


class PaymentMismatch(DomainError):
    pass
