class ApplicationError(Exception):
    pass


class OrderProjectionNotFound(ApplicationError):
    """The order projection is not there yet; the consumer must retry later."""


class InvalidQuery(ApplicationError):
    pass
