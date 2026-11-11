class ApplicationError(Exception):
    pass


class PaymentNotFound(ApplicationError):
    pass
