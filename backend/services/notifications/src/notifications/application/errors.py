class ApplicationError(Exception):
    pass


class NotificationNotFound(ApplicationError):
    pass


class OrderContextMissing(ApplicationError):
    """The order projection is not there yet; the event must be retried later."""


class SendError(Exception):
    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent
