from __future__ import annotations

from typing import Any

import httpx

from .base import LLMError, LLMResponse, Message, ToolCall, ToolSpec

API_VERSION = "2023-06-01"


def to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Anthropic wants tool results inside a *user* turn, and consecutive
    results from one assistant turn grouped into a single message."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
            out.append({"role": "assistant", "content": blocks})
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            last = out[-1] if out else None
            if last and last["role"] == "user" and isinstance(last["content"], list):
                last["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def to_anthropic_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]


def parse_anthropic_response(data: dict[str, Any]) -> LLMResponse:
    if "content" not in data:
        raise LLMError(f"unexpected Anthropic response: {data}")
    texts, calls = [], []
    for block in data["content"]:
        if block.get("type") == "text":
            texts.append(block["text"])
        elif block.get("type") == "tool_use":
            calls.append(ToolCall(id=block["id"], name=block["name"], arguments=block.get("input") or {}))
    usage = data.get("usage") or {}
    return LLMResponse(
        text="\n".join(texts) or None,
        tool_calls=calls,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
    )


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float = 60):
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self.model = model
        self._client = httpx.Client(
            base_url="https://api.anthropic.com/v1",
            headers={"x-api-key": api_key, "anthropic-version": API_VERSION},
            timeout=timeout,
        )

    def chat(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        payload = {
            "model": self.model,
            "max_tokens": 1500,
            "temperature": 0.2,
            "system": system,
            "tools": to_anthropic_tools(tools),
            "messages": to_anthropic_messages(messages),
        }
        resp = self._client.post("/messages", json=payload)
        if resp.status_code >= 400:
            raise LLMError(f"Anthropic API error {resp.status_code}: {resp.text[:500]}")
        return parse_anthropic_response(resp.json())
