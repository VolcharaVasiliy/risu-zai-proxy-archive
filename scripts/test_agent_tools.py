import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from py.agent_tools import (  # noqa: E402
    extract_tool_calls_from_content,
    normalize_tool_result,
    prepare_prompt_tool_payload,
)
from py.http_helpers import (  # noqa: E402
    header_bearer_token,
    proxy_authorized,
)

READ_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}


class FakeHeaders(dict):
    def get(self, name, default=""):
        lowered = str(name or "").lower()
        for key, value in self.items():
            if str(key).lower() == lowered:
                return value
        return default


class FakeHandler:
    def __init__(self, headers):
        self.headers = FakeHeaders(headers)


SHELL_TOOL = {
    "type": "function",
    "function": {
        "name": "terminal",
        "description": "Run a terminal command",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
}


def _request_config(**overrides):
    config = {"tools": [READ_TOOL, SHELL_TOOL], "tool_choice": "auto"}
    config.update(overrides)
    return config


def test_structured_tool_call():
    content = json.dumps(
        {
            "tool_calls": [
                {"name": "read_file", "arguments": {"path": "README.md"}},
                {"name": "terminal", "arguments": {"command": "git status --short"}},
            ]
        }
    )
    text, calls = extract_tool_calls_from_content(content, _request_config())
    assert text == ""
    assert [call["function"]["name"] for call in calls] == ["read_file", "terminal"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"path": "README.md"}


def test_parallel_tool_calls_can_be_limited():
    content = json.dumps(
        {
            "tool_calls": [
                {"name": "read_file", "arguments": {"path": "README.md"}},
                {"name": "terminal", "arguments": {"command": "git status --short"}},
            ]
        }
    )
    _text, calls = extract_tool_calls_from_content(
        content, _request_config(parallel_tool_calls=False)
    )
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "read_file"


def test_bare_single_tool_arguments():
    text, calls = extract_tool_calls_from_content(
        '{"path":"README.md"}', {"tools": [READ_TOOL], "tool_choice": "required"}
    )
    assert text == ""
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "read_file"
    assert json.loads(calls[0]["function"]["arguments"]) == {"path": "README.md"}


def test_empty_arguments_are_valid_json_objects():
    text, calls = extract_tool_calls_from_content(
        '{"tool_calls":[{"name":"read_file","arguments":""}]}', _request_config()
    )
    assert text == ""
    assert len(calls) == 1
    assert calls[0]["function"]["arguments"] == "{}"


def test_normalize_chat_result_to_openai_tool_calls():
    result = {
        "id": "chatcmpl_test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '{"tool_calls":[{"name":"read_file","arguments":{"path":"README.md"}}]}',
                },
                "finish_reason": "stop",
            }
        ],
    }
    normalized, count = normalize_tool_result(result, _request_config())
    message = normalized["choices"][0]["message"]
    assert count == 1
    assert normalized["choices"][0]["finish_reason"] == "tool_calls"
    assert message["content"] == ""
    assert message["tool_calls"][0]["function"]["name"] == "read_file"


def test_proxy_api_key_is_not_reused_as_upstream_bearer():
    previous = os.environ.get("PROXY_API_KEY")
    os.environ["PROXY_API_KEY"] = "client-key"
    try:
        handler = FakeHandler({"Authorization": "Bearer client-key"})
        assert proxy_authorized(handler) is True
        assert header_bearer_token(handler) == ""

        upstream_handler = FakeHandler({"Authorization": "Bearer upstream-token"})
        assert proxy_authorized(upstream_handler) is False
        assert header_bearer_token(upstream_handler) == "upstream-token"
    finally:
        if previous is None:
            os.environ.pop("PROXY_API_KEY", None)
        else:
            os.environ["PROXY_API_KEY"] = previous


def test_prepare_prompt_tool_payload_hides_native_tool_schema():
    payload = {
        "model": "glm-5",
        "messages": [{"role": "user", "content": "read README.md"}],
        "tools": [READ_TOOL],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
    }
    prepared = prepare_prompt_tool_payload(payload, "zai")
    assert "tools" not in prepared
    assert "tool_choice" not in prepared
    assert "parallel_tool_calls" not in prepared
    assert prepared["_agent_tool_shim"]["mode"] == "prompt"
    assert prepared["messages"][0]["role"] == "user"
    assert "OpenAI-compatible agent runtime" in prepared["messages"][0]["content"]


def main():
    test_structured_tool_call()
    test_parallel_tool_calls_can_be_limited()
    test_bare_single_tool_arguments()
    test_empty_arguments_are_valid_json_objects()
    test_normalize_chat_result_to_openai_tool_calls()
    test_proxy_api_key_is_not_reused_as_upstream_bearer()
    test_prepare_prompt_tool_payload_hides_native_tool_schema()
    print("agent_tools_test: ok")


if __name__ == "__main__":
    main()
