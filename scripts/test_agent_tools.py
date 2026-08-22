import json
import importlib.util
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from py.agent_tools import (  # noqa: E402
    build_tool_protocol_prompt,
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
from py.responses_api import _chat_payload_from_request  # noqa: E402
from py.responses_api import _normalize_message_item  # noqa: E402
from py.responses_api import _output_items_from_result  # noqa: E402
from py.responses_api import _stream_response_api_events  # noqa: E402
from py import deepseek_proxy, gemini_web_proxy, provider_registry, qwen_ai_proxy  # noqa: E402
from py import zai_proxy  # noqa: E402

CATALOG_SCRIPT = os.path.join(ROOT_DIR, "scripts", "generate-codex-catalog.py")
_catalog_spec = importlib.util.spec_from_file_location(
    "generate_codex_catalog", CATALOG_SCRIPT
)
generate_codex_catalog = importlib.util.module_from_spec(_catalog_spec)
_catalog_spec.loader.exec_module(generate_codex_catalog)

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


def test_shell_aliases_resolve_to_available_command_tool():
    content = json.dumps(
        {"tool_calls": [{"name": "shell", "arguments": {"command": "dir"}}]}
    )
    text, calls = extract_tool_calls_from_content(content, _request_config())
    assert text == ""
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "terminal"
    assert json.loads(calls[0]["function"]["arguments"]) == {"command": "dir"}

    text, calls = extract_tool_calls_from_content(
        "tool_call: bash for Get-ChildItem", _request_config()
    )
    assert text == ""
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "terminal"
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "command": "Get-ChildItem"
    }


def test_malformed_tool_fragment_recovers_shell_command():
    content = (
        '"tool_calls":"name":"shell_command","arguments":"command":"gh search repos --topic=creative-coding '
        '--sort=stars\n  --limit=5 --json name,owner,stargazersCount,description,url"'
    )
    text, calls = extract_tool_calls_from_content(content, _request_config())
    assert text == ""
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "terminal"
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "command": "gh search repos --topic=creative-coding --sort=stars --limit=5 --json name,owner,stargazersCount,description,url"
    }


def test_command_tool_arguments_strip_broken_json_tail():
    content = json.dumps(
        {
            "tool_calls": [
                {
                    "name": "terminal",
                    "arguments": {
                        "command": (
                            "Get-CimInstance Win32_Process | Select-Object "
                            'ProcessId, CommandLine | Format-List\\" garbage}]}'
                        )
                    },
                }
            ]
        }
    )
    text, calls = extract_tool_calls_from_content(content, _request_config())
    assert text == ""
    assert len(calls) == 1
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "command": (
            "Get-CimInstance Win32_Process | Select-Object "
            "ProcessId, CommandLine | Format-List"
        )
    }

    text, calls = extract_tool_calls_from_content(
        json.dumps(
            {
                "tool_calls": [
                    {"name": "terminal", "arguments": {"command": "Set-Location C:\\"}}
                ]
            }
        ),
        _request_config(),
    )
    assert text == ""
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "command": "Set-Location C:\\"
    }


def test_tool_protocol_prompt_describes_codex_command_tool():
    prompt = build_tool_protocol_prompt(_request_config())
    assert "Codex exposes emulated client tools" in prompt
    assert "exact names in `Available tools`" in prompt
    assert "Windows command line" in prompt
    assert "current working directory" in prompt
    assert "do not search broad drives such as `C:\\`" in prompt
    assert "Get-CimInstance Win32_Process" in prompt
    assert "do not rely on `Get-Process ... .CommandLine`" in prompt
    assert "Invoke-Item -LiteralPath" in prompt
    assert "For background local servers" in prompt
    assert "Start-Process -PassThru" in prompt
    assert "Stop only that PID" in prompt
    assert "prefer the current PowerShell 7 shell" in prompt
    assert "UTF-8 or non-ASCII text" in prompt
    assert "PowerShell is not bash" in prompt
    assert "`<<EOF`" in prompt
    assert "`bash -lc`" in prompt
    assert "passes the payload as a command argument instead of stdin/heredoc syntax" in prompt
    assert "Tool arguments are JSON" in prompt
    assert "prefer single-quoted PowerShell string literals" in prompt
    assert "Available tool names (use exactly)" in prompt
    assert "`read_file`, `terminal`" in prompt
    assert "Command-capable tools: `terminal`" in prompt
    assert 'name":"terminal","arguments":{"command":"Get-ChildItem"}' in prompt
    assert '"name":"shell_command","arguments":{"command":"dir' not in prompt
    assert "Read relevant files before editing" in prompt
    assert "your first substantive response should normally be a tool call" in prompt
    assert "run `git status --short` before editing" in prompt
    assert "inspect the relevant `git diff -- <path>`" in prompt
    assert "distinguish your changed files from pre-existing dirty files" in prompt
    assert "Do not rewrite entire files" in prompt
    assert "Prefer a focused patch" in prompt
    assert "Do not use `Set-Content`/redirection to rewrite a whole source file" in prompt
    assert "prefer a small exact replacement script" in prompt
    assert "Do not use a full-file `Set-Content` here-string" in prompt
    assert "After every edit, inspect the changed section or file before running validation" in prompt
    assert "re-read the modified file, repair any broken intermediate state" in prompt
    assert "If the same edit method fails twice, switch methods" in prompt
    assert "A successful intermediate tool command is not task completion" in prompt
    assert "A successful file write must normally be followed by reading the file back" in prompt
    assert "Never stop with an empty response after tool results" in prompt
    assert "Never leave a workspace in a known broken intermediate state" in prompt
    assert "avoid fragile nested-quote one-liners" in prompt
    assert "large source text inside a quoted `-Command` argument" in prompt
    assert "after two quoting failures, switch methods" in prompt
    assert "For complex new Windows files containing many quotes" in prompt
    assert "base64 UTF-8 payload decoded by PowerShell" in prompt
    assert "decode it in the same PowerShell process" in prompt
    assert "do not pass `$b64` through a nested `pwsh -Command`" in prompt
    assert "Do not install missing test dependencies such as `pytest`" in prompt
    assert "For new executable projects, especially Rust/C/C++ CLI tasks" in prompt
    assert "do not initialize a git repository or make commits unless the user asks" in prompt
    assert "set `CARGO_TARGET_DIR` to a concrete writable directory" in prompt
    assert "do not delete random target directories to recover" in prompt
    assert "Prefer zero external dependencies for small utilities" in prompt
    assert "keep unit tests focused on pure parser/storage/formatting functions" in prompt
    assert "target" in prompt and "release" in prompt and "name.exe" in prompt
    assert "smoke commands instead of making fragile unit tests depend on a debug exe path" in prompt
    assert "Validation is not complete until the final executable exists" in prompt
    assert "Once the executable smoke test passes, stop the tool loop" in prompt
    assert "do not send standalone progress/status prose while file or command work remains" in prompt
    assert "do not claim that tools are unavailable" in prompt
    assert "Treat the written requirements as a checklist" in prompt
    assert "persisted/pre-existing state" in prompt
    assert "does not prove IDs are never reused after deletion or across persisted state" in prompt
    assert "Before guessing a test runner" in prompt
    assert "Prefer the documented test/build command" in prompt
    assert "do not install pytest or keep guessing module names" in prompt
    assert "Keep validation commands small and composable" in prompt
    assert "over one dense PowerShell line with nested `try/catch`" in prompt
    assert "Treat empty validation output as suspicious" in prompt
    assert "use a fresh output directory such as `out2`" in prompt
    assert "Never retry the same blocked `Remove-Item` command" in prompt
    assert "Treat read-back corruption as failed validation" in prompt
    assert "visibly corrupted non-ASCII text" in prompt
    assert "send a user-facing answer only after the work is complete and verified" in prompt
    assert "never end with an empty assistant message" in prompt
    assert "payload must be the raw patch text only" in prompt
    assert "do not repeat the same `apply_patch` call" in prompt


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


def test_unavailable_tool_request_returns_available_tool_list():
    result = {
        "id": "chatcmpl_test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {"tool_calls": [{"name": "python", "arguments": {}}]}
                    ),
                },
                "finish_reason": "stop",
            }
        ],
    }
    normalized, count = normalize_tool_result(result, _request_config())
    message = normalized["choices"][0]["message"]
    assert count == 0
    assert "Unsupported tool request" in message["content"]
    assert "Requested tool names: `python`" in message["content"]
    assert "Available tool names: `read_file`, `terminal`" in message["content"]


def test_tool_does_not_exist_text_returns_retry_guidance():
    result = {
        "id": "chatcmpl_test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Tool shell_command does not exists. Please run Get-Content README.md yourself.",
                },
                "finish_reason": "stop",
            }
        ],
    }
    normalized, count = normalize_tool_result(result, _request_config())
    message = normalized["choices"][0]["message"]
    assert count == 0
    assert "Unsupported tool request" in message["content"]
    assert "Requested tool names: `shell_command`" in message["content"]
    assert "Available tool names: `read_file`, `terminal`" in message["content"]
    assert "Do not tell the user to run commands manually" in message["content"]


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


def test_prompt_tool_payload_adds_tool_error_recovery_guidance():
    payload = {
        "model": "Qwen3.7-Max",
        "messages": [
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "terminal",
                "content": (
                    "Fatal error: tool apply_patch invoked with incompatible payload\n"
                    "SyntaxError: unterminated string literal\n"
                    "python.exe: No module named pytest"
                ),
            }
        ],
        "tools": [READ_TOOL, SHELL_TOOL],
        "tool_choice": "auto",
    }
    prepared = prepare_prompt_tool_payload(payload, "qwen-ai")
    tool_message = prepared["messages"][1]["content"]
    assert "Do not repeat the same malformed call" in tool_message
    assert "do not repeat the same command" in tool_message
    assert "pytest is not available" in tool_message
    assert "direct Python checks" in tool_message

    payload["messages"][0]["content"] = (
        "ParserError: No characters are allowed after a here-string header "
        "but before the end of the line. ScriptBlock should only be specified "
        "as a value of the Command parameter."
    )
    prepared = prepare_prompt_tool_payload(payload, "qwen-ai")
    tool_message = prepared["messages"][1]["content"]
    assert "PowerShell command failed because of quoting, here-string" in tool_message
    assert "Do not retry those patterns" in tool_message

    payload["messages"][0]["content"] = (
        "Missing file specification after redirection operator. "
        "PowerShell does not support bash heredoc syntax like <<EOF or <<'EOF'."
    )
    prepared = prepare_prompt_tool_payload(payload, "qwen-ai")
    tool_message = prepared["messages"][1]["content"]
    assert "invalid Unix heredoc syntax" in tool_message
    assert "PowerShell does not support `<<EOF`" in tool_message
    assert "base64 payload passed as a command argument" in tool_message


def test_provider_auth_error_classification():
    gemini_error = RuntimeError(
        'Google AI Studio generation failed: HTTP 400 {"error":{"reason":"API_KEY_INVALID","message":"API key not valid"}}'
    )
    assert provider_registry.is_provider_auth_error(gemini_error) is True
    try:
        provider_registry.raise_provider_auth_if_needed("google-ai-studio", gemini_error)
    except provider_registry.ProviderAuthError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ProviderAuthError")
    assert "Provider authentication/configuration failed for google-ai-studio" in message
    assert "Configure GOOGLE_AI_STUDIO_API_KEY" in message

    zai_error = RuntimeError(
        "401 Client Error: Unauthorized for url: https://chat.z.ai/api/v1/chats/new"
    )
    assert provider_registry.is_provider_auth_error(zai_error) is True
    try:
        provider_registry.raise_provider_auth_if_needed("zai", zai_error)
    except provider_registry.ProviderAuthError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ProviderAuthError")
    assert "Provider authentication/configuration failed for zai" in message
    assert "Configure ZAI_TOKEN" in message

    quota_error = RuntimeError(
        "Google AI Studio generation failed: HTTP 429 quota exceeded for model gemini-3.1-pro"
    )
    assert provider_registry.is_provider_rate_limit_error(quota_error) is True
    try:
        provider_registry.raise_provider_rate_limit_if_needed(
            "google-ai-studio", quota_error
        )
    except provider_registry.ProviderRateLimitError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ProviderRateLimitError")
    assert "Provider rate limit/quota exceeded for google-ai-studio" in message

    gated_error = RuntimeError(
        "Z.ai upstream error: Model not available for current user level (403)"
    )
    assert provider_registry.is_provider_auth_error(gated_error) is True
    localized_gated_error = RuntimeError(
        "Z.ai upstream error: 当前用户无法使用此模型 (403)"
    )
    assert provider_registry.is_provider_auth_error(localized_gated_error) is True
    try:
        provider_registry.raise_provider_auth_if_needed("zai", gated_error)
    except provider_registry.ProviderAuthError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ProviderAuthError")
    assert "account-plan gated" in message


def test_missing_provider_credentials_are_auth_errors():
    assert provider_registry.provider_error_hint("google-ai-studio").startswith(
        "Configure GOOGLE_AI_STUDIO_API_KEY"
    )


def test_zai_upstream_sse_errors_are_reported():
    item = {
        "data": {
            "error": {
                "detail": "Model not available for current user level",
                "code": 403,
            },
            "done": True,
        },
        "error": {
            "detail": "Model not available for current user level",
            "code": 403,
        },
        "done": True,
    }
    try:
        zai_proxy._raise_upstream_error_if_any(item)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected Z.ai upstream error")
    assert "Model not available for current user level" in message
    assert "403" in message

    item = {
        "data": {
            "done": True,
            "error": {
                "detail": "Please refresh the page to update the app, then try again.",
                "error_code": "FRONTEND_CAPTCHA_REQUIRED",
            },
        },
        "done": True,
    }
    try:
        zai_proxy._raise_upstream_error_if_any(item)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected Z.ai upstream captcha error")
    assert "FRONTEND_CAPTCHA_REQUIRED" in message


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


def test_deepseek_vision_keeps_native_image_payloads():
    payload = {
        "model": "deepseek-vision",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Read the photo"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]}],
    }
    assert provider_accepts_native_images("deepseek", "deepseek-vision") is True
    assert provider_accepts_native_images("deepseek", "deepseek-chat") is False
    assert prepare_payload_for_provider("deepseek", {"token": "test"}, payload) is payload
    deepseek_model = next(
        item for item in provider_registry.MODEL_SPECS if item["id"] == "deepseek-vision"
    )
    assert deepseek_model["capabilities"]["native_images"] is True


def test_deepseek_image_resolver_accepts_openai_image_shapes():
    original = deepseek_proxy._upload_and_wait
    uploads = []
    try:
        deepseek_proxy._upload_and_wait = lambda token, raw, filename, mime: uploads.append(
            (token, raw, filename, mime)
        ) or f"file-{len(uploads)}"
        png = "data:image/png;base64,aGVsbG8="
        file_ids = deepseek_proxy._resolve_image_ids("access", [
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": png}},
                {"type": "input_image", "image_url": png},
            ]}
        ])
        assert file_ids == ["file-1"]
        assert uploads[0][1] == b"hello"
        assert uploads[0][2:] == ("image.png", "image/png")
    finally:
        deepseek_proxy._upload_and_wait = original


def test_deepseek_image_size_limit_is_enforced():
    previous = os.environ.get("DEEPSEEK_MAX_IMAGE_BYTES")
    try:
        os.environ["DEEPSEEK_MAX_IMAGE_BYTES"] = "4"
        try:
            deepseek_proxy._validate_image_bytes(b"12345")
        except ValueError as exc:
            assert "exceeds 4 bytes" in str(exc)
        else:
            raise AssertionError("expected DeepSeek image size error")
    finally:
        if previous is None:
            os.environ.pop("DEEPSEEK_MAX_IMAGE_BYTES", None)
        else:
            os.environ["DEEPSEEK_MAX_IMAGE_BYTES"] = previous


def test_deepseek_content_empty_is_a_ready_image_status():
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"data": {"biz_data": {"files": [{
                "id": "image-id",
                "status": "CONTENT_EMPTY",
                "is_image": True,
            }]}}}

    original_get = deepseek_proxy.requests.get
    original_sleep = deepseek_proxy.time.sleep
    try:
        deepseek_proxy.requests.get = lambda *args, **kwargs: Response()
        deepseek_proxy.time.sleep = lambda _seconds: None
        info = deepseek_proxy._fetch_file_sync("access", "image-id", max_polls=1)
        assert info["status"] == "CONTENT_EMPTY"
    finally:
        deepseek_proxy.requests.get = original_get
        deepseek_proxy.time.sleep = original_sleep


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


def test_responses_request_maps_codex_fields_to_chat_payload():
    _messages, context = _chat_payload_from_request(
        {
            "model": "mistral-small-2603",
            "input": "hello",
            "max_output_tokens": 123,
            "reasoning": {"effort": "high"},
        },
        "mistral",
    )
    chat_payload = context["chat_payload"]
    assert chat_payload["max_tokens"] == 123
    assert chat_payload["reasoning_effort"] == "high"


def test_responses_apply_patch_is_custom_tool_call():
    patch = "*** Begin Patch\n*** Add File: x.txt\n+ok\n*** End Patch"
    result = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_patch",
                            "type": "function",
                            "function": {
                                "name": "apply_patch",
                                "arguments": json.dumps({"input": patch}),
                            },
                        }
                    ],
                }
            }
        ]
    }
    output = _output_items_from_result(result)
    assert output[0]["type"] == "custom_tool_call"
    assert output[0]["call_id"] == "call_patch"
    assert output[0]["name"] == "apply_patch"
    assert output[0]["input"] == patch


def test_responses_streams_custom_tool_input_delta():
    response = {
        "id": "resp_test",
        "object": "response",
        "status": "completed",
        "output": [
            {
                "id": "ctc_test",
                "type": "custom_tool_call",
                "status": "completed",
                "call_id": "call_patch",
                "name": "apply_patch",
                "input": "*** Begin Patch\n*** End Patch",
            }
        ],
        "output_text": "",
    }
    events = list(_stream_response_api_events(response))
    event_types = [event["type"] for event in events]
    assert "response.custom_tool_call_input.delta" in event_types
    done_item = next(
        event["item"]
        for event in events
        if event["type"] == "response.output_item.done"
    )
    assert done_item["type"] == "custom_tool_call"
    assert done_item["input"] == "*** Begin Patch\n*** End Patch"


def test_responses_custom_tool_output_maps_to_tool_message():
    message = _normalize_message_item(
        {
            "type": "custom_tool_call_output",
            "call_id": "call_patch",
            "output": "Exit code: 0",
        }
    )
    assert message == {
        "role": "tool",
        "content": "Exit code: 0",
        "tool_call_id": "call_patch",
    }


def test_catalog_disables_freeform_apply_patch_for_prompt_shim_models():
    prompt_shim_model = generate_codex_catalog._codex_model(
        {
            "id": "Qwen3.7-Max",
            "provider": "qwen-ai",
            "capabilities": {"tools": True, "prompt_tool_shim": True},
        },
        0,
        128_000,
    )
    native_tool_model = generate_codex_catalog._codex_model(
        {
            "id": "google-ai-studio",
            "provider": "google-ai-studio",
            "capabilities": {"tools": True, "native_tools": True},
        },
        0,
        128_000,
    )
    assert "apply_patch_tool_type" not in prompt_shim_model
    assert native_tool_model["apply_patch_tool_type"] == "freeform"


def test_public_model_catalog_hides_alias_duplicates():
    model_ids = [
        item["id"]
        for item in provider_registry.MODEL_SPECS
        if item["provider"] == "gemini-web"
    ]
    assert "gemini-3-flash" in model_ids
    assert "gemini-3-pro" in model_ids
    assert "gemini-web" not in model_ids
    assert gemini_web_proxy.supports_model("gemini-web") is True
    assert gemini_web_proxy.supports_model("gemini-web-3.5-pro") is False


def test_qwen_37_models_are_supported():
    assert "Qwen3.8-Max" in qwen_ai_proxy.SUPPORTED_MODELS
    assert "Qwen3.7-Max" in qwen_ai_proxy.SUPPORTED_MODELS
    assert "Qwen3.7-Plus" in qwen_ai_proxy.SUPPORTED_MODELS
    assert qwen_ai_proxy.supports_model("qwen") is True
    assert qwen_ai_proxy.map_model("qwen") == "qwen3.8-max"
    assert qwen_ai_proxy.map_model("Qwen3.8-Max") == "qwen3.8-max"
    assert qwen_ai_proxy.map_model("Qwen3.7-Max") == "qwen3.7-max"
    assert qwen_ai_proxy.map_model("Qwen3.7-Max-Preview") == "qwen3.7-max"
    assert qwen_ai_proxy.map_model("Qwen3.7-Plus") == "qwen3.7-plus"
    # Qwen currently rejects qwen3.6-flash upstream; the adapter intentionally
    # falls back to the live qwen3.6-plus model.
    assert qwen_ai_proxy.map_model("Qwen3.6-Flash") == "qwen3.6-plus"


def test_provider_manifest_is_consistent_and_safe():
    manifest = provider_registry.PROVIDER_MANIFEST
    ids = [entry["id"] for entry in manifest]
    assert ids == list(provider_registry.PROVIDERS_BY_ID)
    assert len(ids) == len(set(ids))
    assert all(entry["models"] for entry in manifest)
    assert all(entry["runtimes"] for entry in manifest)
    assert set(ids) == set(provider_registry.PROVIDER_ADAPTERS)
    assert all(entry.get("credential_sets") is not None for entry in manifest)

    status = provider_registry.provider_status_payload()
    assert status["object"] == "list"
    assert {entry["id"] for entry in status["data"]} == set(ids)
    public = next(item for item in status["data"] if item["id"] == "uncloseai")
    assert public["ready"] is True
    serialized = json.dumps(status, ensure_ascii=False)
    for secret in ("Bearer ", "cookie=", "api_key="):
        assert secret not in serialized


def test_provider_status_accepts_alternative_credentials(monkeypatch=None):
    previous = dict(os.environ)
    try:
        for name in ("GOOGLE_AI_STUDIO_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(name, None)
        os.environ["GEMINI_API_KEY"] = "test-key"
        status = provider_registry.provider_status_payload()["data"]
        studio = next(item for item in status if item["id"] == "google-ai-studio")
        assert studio["ready"] is True
        assert studio["missing_env"] == []
        assert "GEMINI_API_KEY" in studio["configured_env"]
    finally:
        os.environ.clear()
        os.environ.update(previous)


def test_manifest_resolution_preserves_provider_precedence():
    assert provider_registry.resolve_provider_id("Qwen3.7-Max") == "qwen-ai"
    assert provider_registry.resolve_provider_id("mistral-small-2603") == "mistral"
    assert provider_registry.resolve_provider_id("definitely-unknown-model") == ""


def test_doctor_summary_matches_manifest():
    doctor = provider_registry.doctor_payload()
    assert doctor["providers_total"] == len(provider_registry.PROVIDER_MANIFEST)
    assert doctor["providers_ready"] + doctor["providers_missing_credentials"] == doctor["providers_total"]
    assert set(doctor["runtimes"]) >= {"local", "vercel"}
    assert doctor["checks"]["manifest"] is True


def test_provider_runtime_filter_is_explicit():
    local = provider_registry.provider_status_payload("local")
    vercel = provider_registry.provider_status_payload("vercel")
    assert local["runtime"] == "local"
    assert vercel["runtime"] == "vercel"
    assert all("local" in item["runtimes"] for item in local["data"])
    assert all("vercel" in item["runtimes"] for item in vercel["data"])
    assert len(vercel["data"]) < len(provider_registry.PROVIDER_MANIFEST)
    invalid = provider_registry.doctor_payload("not-a-runtime")
    assert invalid["runtime_valid"] is False
    assert invalid["ok"] is False
    assert "cloudflare" in invalid["supported_runtimes"]


def test_provider_dispatch_table_calls_adapter_without_central_if_chain():
    original = provider_registry.deepseek_proxy.complete_non_stream
    try:
        provider_registry.deepseek_proxy.complete_non_stream = lambda token, payload: (
            {
                "id": "test",
                "model": payload["model"],
                "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            },
            {"adapter": "fake"},
        )
        result, meta = provider_registry.complete_non_stream(
            "deepseek", {"token": "redacted"}, {"model": "deepseek-chat", "messages": []}
        )
        assert result["choices"][0]["message"]["content"] == "ok"
        assert meta == {"adapter": "fake"}
    finally:
        provider_registry.deepseek_proxy.complete_non_stream = original


def main():
    test_structured_tool_call()
    test_parallel_tool_calls_can_be_limited()
    test_bare_single_tool_arguments()
    test_empty_arguments_are_valid_json_objects()
    test_shell_aliases_resolve_to_available_command_tool()
    test_malformed_tool_fragment_recovers_shell_command()
    test_command_tool_arguments_strip_broken_json_tail()
    test_tool_protocol_prompt_describes_codex_command_tool()
    test_normalize_chat_result_to_openai_tool_calls()
    test_unavailable_tool_request_returns_available_tool_list()
    test_tool_does_not_exist_text_returns_retry_guidance()
    test_proxy_api_key_is_not_reused_as_upstream_bearer()
    test_prepare_prompt_tool_payload_hides_native_tool_schema()
    test_prompt_tool_payload_adds_tool_error_recovery_guidance()
    test_provider_auth_error_classification()
    test_missing_provider_credentials_are_auth_errors()
    test_zai_upstream_sse_errors_are_reported()
    test_google_ai_studio_uses_native_tools_not_prompt_shim()
    test_multimodal_preprocess_converts_images_for_text_providers()
    test_multimodal_preprocess_keeps_native_image_payloads()
    test_deepseek_vision_keeps_native_image_payloads()
    test_deepseek_image_resolver_accepts_openai_image_shapes()
    test_deepseek_image_size_limit_is_enforced()
    test_deepseek_content_empty_is_a_ready_image_status()
    test_google_ai_studio_request_body_supports_images_and_tools()
    test_google_ai_studio_function_call_extraction()
    test_google_ai_studio_tool_history_includes_function_response_id()
    test_responses_input_file_image_is_preserved_as_image_url()
    test_responses_request_maps_codex_fields_to_chat_payload()
    test_responses_apply_patch_is_custom_tool_call()
    test_responses_streams_custom_tool_input_delta()
    test_responses_custom_tool_output_maps_to_tool_message()
    test_catalog_disables_freeform_apply_patch_for_prompt_shim_models()
    test_public_model_catalog_hides_alias_duplicates()
    test_qwen_37_models_are_supported()
    test_provider_manifest_is_consistent_and_safe()
    test_provider_status_accepts_alternative_credentials()
    test_manifest_resolution_preserves_provider_precedence()
    test_doctor_summary_matches_manifest()
    test_provider_runtime_filter_is_explicit()
    test_provider_dispatch_table_calls_adapter_without_central_if_chain()
    print("agent_tools_test: ok")


if __name__ == "__main__":
    main()
