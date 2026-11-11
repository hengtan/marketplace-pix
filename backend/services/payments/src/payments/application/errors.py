class ApplicationError(Exception):
    pass


class PaymentNotFound(ApplicationError):
    pass


class PspUnavailable(ApplicationError):
    def __init__(self, message: str, retry_after_seconds: float = 1.0) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
