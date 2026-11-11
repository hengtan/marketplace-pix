class DomainError(Exception):
    pass


class InvalidEmail(DomainError):
    pass


class WeakPassword(DomainError):
    pass


class InvalidRoleAssignment(DomainError):
    pass
