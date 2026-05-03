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
    provider_has_native_tools,
    should_use_prompt_tool_shim,
)
from py.google_ai_studio_proxy import (  # noqa: E402
    _extract_candidate_content,
    _request_body,
)
from py.http_helpers import (  # noqa: E402
    header_bearer_token,
    proxy_authorized,
)
from py.multimodal import (  # noqa: E402
    prepare_payload_for_provider,
    provider_accepts_native_images,
)
from py.responses_api import _content_to_chat_content  # noqa: E402

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


def test_google_ai_studio_uses_native_tools_not_prompt_shim():
    config = {"tools": [READ_TOOL], "tool_choice": "auto"}
    assert provider_has_native_tools("google-ai-studio") is True
    assert should_use_prompt_tool_shim("google-ai-studio", config) is False


def test_multimodal_preprocess_converts_images_for_text_providers():
    previous_mode = os.environ.get("MULTIMODAL_IMAGE_MODE")
    os.environ["MULTIMODAL_IMAGE_MODE"] = "placeholder"
    try:
        payload = {
            "model": "glm-5",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is in this image?"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.com/cat.png"},
                        },
                    ],
                }
            ],
        }
        prepared = prepare_payload_for_provider("zai", {}, payload)
        content = prepared["messages"][0]["content"]
        assert isinstance(content, str)
        assert "What is in this image?" in content
        assert "[Image 1: https://example.com/cat.png]" in content
        assert prepared["_multimodal_processed"]["image_count"] == 1
    finally:
        if previous_mode is None:
            os.environ.pop("MULTIMODAL_IMAGE_MODE", None)
        else:
            os.environ["MULTIMODAL_IMAGE_MODE"] = previous_mode


def test_multimodal_preprocess_keeps_native_image_payloads():
    payload = {
        "model": "google-ai-studio",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe it"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AAAA"},
                    },
                ],
            }
        ],
    }
    assert (
        provider_accepts_native_images("google-ai-studio", "google-ai-studio") is True
    )
    assert prepare_payload_for_provider("google-ai-studio", {}, payload) is payload


def test_google_ai_studio_request_body_supports_images_and_tools():
    nullable_tool = json.loads(json.dumps(READ_TOOL))
    nullable_tool["function"]["parameters"]["properties"]["path"]["type"] = [
        "string",
        "null",
    ]
    nullable_tool["function"]["parameters"]["properties"]["path"]["nullable"] = True
    body = _request_body(
        {
            "model": "google-ai-studio",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe and maybe read"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,AAAA"},
                        },
                    ],
                }
            ],
            "tools": [nullable_tool],
            "tool_choice": "required",
        }
    )
    parts = body["contents"][0]["parts"]
    assert parts[0] == {"text": "Describe and maybe read"}
    assert parts[1]["inline_data"] == {"mime_type": "image/png", "data": "AAAA"}
    declaration = body["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "read_file"
    assert declaration["parameters"]["properties"]["path"] == {"type": "string"}
    assert body["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"


def test_google_ai_studio_function_call_extraction():
    _text, _reasoning, calls = _extract_candidate_content(
        {
            "content": {
                "parts": [
                    {
                        "functionCall": {
                            "id": "gemini-call-1",
                            "name": "read_file",
                            "args": {"path": "README.md"},
                        }
                    }
                ]
            }
        }
    )
    assert len(calls) == 1
    assert calls[0]["id"] == "gemini-call-1"
    assert calls[0]["function"]["name"] == "read_file"
    assert json.loads(calls[0]["function"]["arguments"]) == {"path": "README.md"}


def test_google_ai_studio_tool_history_includes_function_response_id():
    body = _request_body(
        {
            "model": "google-ai-studio",
            "messages": [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "gemini-call-1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": json.dumps({"path": "README.md"}),
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "gemini-call-1",
                    "name": "read_file",
                    "content": "# README",
                },
            ],
        }
    )
    function_call = body["contents"][0]["parts"][0]["functionCall"]
    function_response = body["contents"][1]["parts"][0]["functionResponse"]
    assert function_call["id"] == "gemini-call-1"
    assert function_response["id"] == "gemini-call-1"
    assert function_response["name"] == "read_file"


def test_responses_input_file_image_is_preserved_as_image_url():
    content = _content_to_chat_content(
        [
            {"type": "input_text", "text": "look"},
            {
                "type": "input_file",
                "filename": "pixel.png",
                "mime_type": "image/png",
                "file_data": "AAAA",
            },
        ]
    )
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "look"}
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AAAA"},
    }


def main():
    test_structured_tool_call()
    test_parallel_tool_calls_can_be_limited()
    test_bare_single_tool_arguments()
    test_empty_arguments_are_valid_json_objects()
    test_normalize_chat_result_to_openai_tool_calls()
    test_proxy_api_key_is_not_reused_as_upstream_bearer()
    test_prepare_prompt_tool_payload_hides_native_tool_schema()
    test_google_ai_studio_uses_native_tools_not_prompt_shim()
    test_multimodal_preprocess_converts_images_for_text_providers()
    test_multimodal_preprocess_keeps_native_image_payloads()
    test_google_ai_studio_request_body_supports_images_and_tools()
    test_google_ai_studio_function_call_extraction()
    test_google_ai_studio_tool_history_includes_function_response_id()
    test_responses_input_file_image_is_preserved_as_image_url()
    print("agent_tools_test: ok")


if __name__ == "__main__":
    main()
