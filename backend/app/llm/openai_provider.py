from __future__ import annotations

import json
from typing import Any

import httpx

from .base import LLMError, LLMResponse, Message, ToolCall, ToolSpec


def to_openai_messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.get("content")}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in m["tool_calls"]
                ]
            out.append(msg)
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
    return out


def to_openai_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
    ]


def parse_openai_response(data: dict[str, Any]) -> LLMResponse:
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"unexpected OpenAI response: {data}") from exc
    calls = []
    for tc in msg.get("tool_calls") or []:
        raw = tc["function"].get("arguments") or "{}"
        try:
            args = json.loads(raw)
        except json.JSONDecodeError:
            args = {"_raw": raw}
        calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=args))
    usage = data.get("usage") or {}
    return LLMResponse(
        text=msg.get("content"),
        tool_calls=calls,
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
    )


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float = 60):
        if not api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        self.model = model
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def chat(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": to_openai_messages(system, messages),
            "tools": to_openai_tools(tools),
            "tool_choice": "auto",
            "temperature": 0.2,
        }
        resp = self._client.post("/chat/completions", json=payload)
        if resp.status_code >= 400:
            raise LLMError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")
        return parse_openai_response(resp.json())
