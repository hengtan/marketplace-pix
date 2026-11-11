class ApplicationError(Exception):
    pass


class InvalidCredentials(ApplicationError):
    pass


class EmailAlreadyRegistered(ApplicationError):
    pass


class InvalidRefreshToken(ApplicationError):
    pass


class RefreshTokenReuse(InvalidRefreshToken):
    pass


class UserNotFound(ApplicationError):
    pass
