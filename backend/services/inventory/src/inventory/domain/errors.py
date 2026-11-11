class DomainError(Exception):
    pass


class InvalidQuantity(DomainError):
    pass


class InsufficientStock(DomainError):
    pass


class InvalidReservation(DomainError):
    pass


class InvalidStateTransition(DomainError):
    pass
