from autosurf.domain.models import AutomationHandler


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, AutomationHandler] = {}

    def register(self, handler: AutomationHandler) -> None:
        if handler.type in self._handlers:
            raise ValueError(f"handler already registered: {handler.type}")
        self._handlers[handler.type] = handler

    def get(self, handler_type: str) -> AutomationHandler:
        try:
            return self._handlers[handler_type]
        except KeyError as exc:
            raise ValueError(f"unknown automation handler: {handler_type}") from exc

    def types(self) -> list[str]:
        return sorted(self._handlers)

