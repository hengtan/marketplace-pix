from enum import StrEnum


class HandleResult(StrEnum):
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    IGNORED = "IGNORED"
    REJECTED = "REJECTED"
