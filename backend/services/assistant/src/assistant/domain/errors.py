class AssistantError(Exception):
    pass


class MessageTooLong(AssistantError):
    pass


class SessionNotFound(AssistantError):
    pass


class ToolError(AssistantError):
    pass


class UpstreamUnavailable(AssistantError):
    pass
