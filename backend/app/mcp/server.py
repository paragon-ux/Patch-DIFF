"""Internal MCP tool registry for PatchDIFF MVP."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.services.performance_events import span


ToolHandler = Callable[..., dict[str, Any]]


@dataclass(slots=True)
class ToolRegistry:
    _tools: dict[str, ToolHandler] = field(default_factory=dict)

    def register(self, name: str) -> Callable[[ToolHandler], ToolHandler]:
        def decorator(handler: ToolHandler) -> ToolHandler:
            if name in self._tools:
                raise ValueError(f"MCP tool already registered: {name}")
            self._tools[name] = handler
            return handler

        return decorator

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def handler(self, name: str) -> ToolHandler:
        return self._tools[name]

    def call(self, name: str, **kwargs) -> dict[str, Any]:
        with span("rpc", target_id=kwargs.get("target_file_id")):
            return self._tools[name](**kwargs)


registry = ToolRegistry()
