from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# Conversation messages use one provider-neutral shape:
#   {"role": "user", "content": str}
#   {"role": "assistant", "content": str | None, "tool_calls": [ToolCall, ...]}
#   {"role": "tool", "tool_call_id": str, "name": str, "content": str}
Message = dict[str, Any]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class LLMError(RuntimeError):
    pass


class Provider(Protocol):
    name: str
    model: str

    def chat(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse: ...
