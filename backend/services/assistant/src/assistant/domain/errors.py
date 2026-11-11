class AssistantError(Exception):
    pass


class MessageTooLong(AssistantError):
    pass


class SessionNotFound(AssistantError):
    pass


class ToolError(AssistantError):
    pass


class UpstreamUnavailable(AssistantError):
    def __init__(self, message: str = "", retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
