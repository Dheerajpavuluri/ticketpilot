"""Provider adapters: message conversion, response parsing, and a full agent
run against mocked HTTP for each real API."""

import json

import httpx
import respx

from app import services
from app.agent import run_agent
from app.llm.anthropic_provider import (
    AnthropicProvider,
    parse_anthropic_response,
    to_anthropic_messages,
)
from app.llm.base import ToolCall
from app.llm.openai_provider import OpenAIProvider, parse_openai_response, to_openai_messages

HISTORY = [
    {"role": "user", "content": "ticket"},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            ToolCall("a", "lookup_customer", {"email": "x@example.com"}),
            ToolCall("b", "search_help_center", {"query": "refund"}),
        ],
    },
    {"role": "tool", "tool_call_id": "a", "name": "lookup_customer", "content": '{"found": false}'},
    {"role": "tool", "tool_call_id": "b", "name": "search_help_center", "content": '{"results": []}'},
]


def test_openai_message_shape():
    msgs = to_openai_messages("sys", HISTORY)
    assert msgs[0] == {"role": "system", "content": "sys"}
    call = msgs[2]["tool_calls"][0]
    assert call["function"]["name"] == "lookup_customer"
    assert json.loads(call["function"]["arguments"]) == {"email": "x@example.com"}
    assert [m["role"] for m in msgs[3:]] == ["tool", "tool"]


def test_anthropic_groups_tool_results_into_one_user_turn():
    msgs = to_anthropic_messages(HISTORY)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert [b["type"] for b in msgs[1]["content"]] == ["tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in msgs[2]["content"]] == ["a", "b"]


def test_parse_openai_handles_bad_json_arguments():
    r = parse_openai_response(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [{"id": "1", "function": {"name": "get_order", "arguments": "{not json"}}],
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }
    )
    assert r.tool_calls[0].arguments == {"_raw": "{not json"}
    assert r.input_tokens == 10


def test_parse_anthropic_text_and_tools():
    r = parse_anthropic_response(
        {
            "content": [
                {"type": "text", "text": "Let me check."},
                {"type": "tool_use", "id": "t1", "name": "get_order", "input": {"order_id": "BL-1"}},
            ],
            "usage": {"input_tokens": 50, "output_tokens": 9},
        }
    )
    assert r.text == "Let me check."
    assert r.tool_calls[0].arguments == {"order_id": "BL-1"}
    assert (r.input_tokens, r.output_tokens) == (50, 9)


SUBMIT = {
    "category": "shipping",
    "priority": "medium",
    "sentiment": "neutral",
    "summary": "Where is it",
    "order_id": "BL-48390",
    "draft_reply": "Hi Jordan, it's on the way.",
    "citations": ["track-order"],
    "confidence": 0.9,
    "needs_human": False,
    "escalation_reason": None,
}


@respx.mock
def test_openai_end_to_end(session, cfg):
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "1",
                                        "type": "function",
                                        "function": {
                                            "name": "get_order",
                                            "arguments": '{"order_id": "BL-48390"}',
                                        },
                                    },
                                    {
                                        "id": "2",
                                        "type": "function",
                                        "function": {
                                            "name": "search_help_center",
                                            "arguments": '{"query": "tracking"}',
                                        },
                                    },
                                ],
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 400, "completion_tokens": 30},
                },
            ),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "3",
                                        "type": "function",
                                        "function": {
                                            "name": "submit_triage",
                                            "arguments": json.dumps(SUBMIT),
                                        },
                                    },
                                ],
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 900, "completion_tokens": 120},
                },
            ),
        ]
    )
    t = services.create_ticket(session, "jordan.brooks@example.com", "Where?", "BL-48390 not here")
    provider = OpenAIProvider("sk-test", "gpt-test", "https://api.openai.com/v1")
    r = run_agent(session, t, provider, cfg)

    assert r.finished and not r.needs_human
    assert (r.input_tokens, r.output_tokens) == (1300, 150)
    second = json.loads(route.calls[1].request.content)
    assert [m["role"] for m in second["messages"]][-2:] == ["tool", "tool"]
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-test"


@respx.mock
def test_anthropic_end_to_end(session, cfg):
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "get_order",
                            "input": {"order_id": "BL-48390"},
                        },
                        {
                            "type": "tool_use",
                            "id": "t2",
                            "name": "search_help_center",
                            "input": {"query": "tracking"},
                        },
                    ],
                    "usage": {"input_tokens": 500, "output_tokens": 40},
                },
            ),
            httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "tool_use", "id": "t3", "name": "submit_triage", "input": SUBMIT},
                    ],
                    "usage": {"input_tokens": 1000, "output_tokens": 150},
                },
            ),
        ]
    )
    t = services.create_ticket(session, "jordan.brooks@example.com", "Where?", "BL-48390 not here")
    provider = AnthropicProvider("ak-test", "claude-test")
    r = run_agent(session, t, provider, cfg)

    assert r.finished and r.output.citations == ["track-order"]
    req = route.calls[1].request
    assert req.headers["x-api-key"] == "ak-test"
    body = json.loads(req.content)
    assert body["messages"][-1]["role"] == "user"
    assert len(body["messages"][-1]["content"]) == 2  # both tool results in one turn


@respx.mock
def test_api_error_marks_ticket_failed(session, cfg):
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": {"message": "rate limited"}})
    )
    t = services.create_ticket(session, "jordan.brooks@example.com", "Where?", "BL-48390")
    provider = OpenAIProvider("sk-test", "gpt-test", "https://api.openai.com/v1")
    t = services.triage_ticket(session, t.id, provider, cfg)
    assert t.status == "failed" and "429" in t.error
